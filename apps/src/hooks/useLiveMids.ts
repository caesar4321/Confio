// Live prices from Hyperliquid's own feed (wss allMids), for the Futuros
// screens: prices on leveraged positions move fast, and members keep a
// screen open to watch them instead of reopening the app.
//
// One shared socket per app: it connects while any screen listens and the
// app is in the foreground, closes otherwise, and reconnects with backoff.
// Display only — nothing is signed from these prices (signing re-reads the
// venue itself, services/perps.ts). Re-renders are capped at one a second.
import { useEffect, useState } from 'react';
import { AppState, AppStateStatus } from 'react-native';

const WS_URL = 'wss://api.hyperliquid.xyz/ws';
const PING_MS = 50_000;
const RENDER_EVERY_MS = 1_000;
const MAX_BACKOFF_MS = 30_000;
// Without a tick for this long the prices are dropped: screens fall back to
// the server's (fresher after a refetch) instead of showing an old one.
const STALE_MS = 15_000;
// No message at all (prices or pong) for this long: the socket is half-open
// (a network change without a close), so it is closed and reconnected.
const SILENT_MS = 60_000;
// A handshake that never completes is given up on and retried.
const CONNECT_TIMEOUT_MS = 15_000;

type Listener = (mids: Record<string, number>) => void;

/** The HIP-3 dex of a coin ('xyz:GOLD' → 'xyz'), '' for core perps. */
const dexOf = (coin: string) => (coin.includes(':') ? coin.split(':')[0] : '');

class MidsFeed {
  private socket: WebSocket | null = null;
  private listeners = new Map<Listener, Set<string>>();
  private mids: Record<string, number> = {};
  private ping: ReturnType<typeof setInterval> | null = null;
  private retry: ReturnType<typeof setTimeout> | null = null;
  private backoff = 1_000;
  private active = AppState.currentState === 'active';
  private subscribed = new Set<string>();
  // Per market group ('' core, 'xyz' …): one group ticking never keeps
  // another group's prices alive.
  private lastTick: Record<string, number> = {};
  private staleCheck: ReturnType<typeof setInterval> | null = null;
  private lastMessage = 0;
  private connectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    AppState.addEventListener('change', (state: AppStateStatus) => {
      this.active = state === 'active';
      this.sync();
    });
  }

  latest(coin: string): number | null {
    return Date.now() - (this.lastTick[dexOf(coin)] ?? 0) <= STALE_MS ? this.mids[coin] ?? null : null;
  }

  /** Forget every price and tell the screens (they fall back to the server's). */
  private drop(dexes?: string[]) {
    if (!dexes) {
      this.mids = {};
      this.lastTick = {};
    } else {
      const gone = new Set(dexes);
      this.mids = Object.fromEntries(Object.entries(this.mids).filter(([coin]) => !gone.has(dexOf(coin))));
      dexes.forEach((d) => { delete this.lastTick[d]; });
    }
    this.listeners.forEach((_dexes, listener) => listener(this.mids));
  }

  add(listener: Listener, dexes: Set<string>) {
    this.listeners.set(listener, dexes);
    this.sync();
  }

  remove(listener: Listener) {
    this.listeners.delete(listener);
    this.sync();
  }

  private wanted(): Set<string> {
    const all = new Set<string>();
    this.listeners.forEach((dexes) => dexes.forEach((d) => all.add(d)));
    return all;
  }

  private sync() {
    const wanted = this.wanted();
    if (!this.active || wanted.size === 0) {
      this.close();
      return;
    }
    if (!this.socket) {
      this.open();
      return;
    }
    if (this.socket.readyState === 1) {
      wanted.forEach((dex) => { if (!this.subscribed.has(dex)) this.subscribe(dex); });
    }
  }

  private subscribe(dex: string) {
    const subscription: Record<string, string> = { type: 'allMids' };
    if (dex) subscription.dex = dex;
    this.socket?.send(JSON.stringify({ method: 'subscribe', subscription }));
    this.subscribed.add(dex);
  }

  private open() {
    if (this.retry) { clearTimeout(this.retry); this.retry = null; }
    let socket: WebSocket;
    try {
      socket = new WebSocket(WS_URL);
    } catch {
      this.scheduleRetry();
      return;
    }
    this.socket = socket;
    this.subscribed.clear();
    this.connectTimer = setTimeout(() => {
      this.connectTimer = null;
      if (this.socket === socket && socket.readyState !== 1) {
        try { socket.close(); } catch { /* closing */ }
        // Some platforms never fire onclose for a socket that never opened.
        if (this.socket === socket) {
          this.cleanup();
          if (this.active && this.wanted().size > 0) this.scheduleRetry();
        }
      }
    }, CONNECT_TIMEOUT_MS);
    socket.onopen = () => {
      // A late callback from a socket already given up on: closed, nothing started.
      if (this.socket !== socket || !this.active) {
        try { socket.close(); } catch { /* closing */ }
        return;
      }
      if (this.connectTimer) { clearTimeout(this.connectTimer); this.connectTimer = null; }
      this.backoff = 1_000;
      this.lastMessage = Date.now();
      this.staleCheck = setInterval(() => {
        const now = Date.now();
        if (now - this.lastMessage > SILENT_MS) {
          // onclose cleans up and schedules the reconnect.
          try { socket.close(); } catch { /* already closing */ }
          return;
        }
        const stale = Object.entries(this.lastTick).filter(([, at]) => now - at > STALE_MS).map(([d]) => d);
        if (stale.length) this.drop(stale);
      }, 5_000);
      this.wanted().forEach((dex) => this.subscribe(dex));
      this.ping = setInterval(() => {
        try { socket.send(JSON.stringify({ method: 'ping' })); } catch { try { socket.close(); } catch { /* closed */ } }
      }, PING_MS);
    };
    socket.onmessage = (event) => {
      if (this.socket !== socket) return;
      this.lastMessage = Date.now();
      let msg: any;
      try { msg = JSON.parse(String(event.data)); } catch { return; }
      const mids = msg?.channel === 'allMids' ? msg?.data?.mids : null;
      if (!mids || typeof mids !== 'object') return;
      const dex = typeof msg?.data?.dex === 'string' ? msg.data.dex : '';
      for (const [coin, px] of Object.entries(mids)) {
        const n = Number(px);
        if (Number.isFinite(n) && n > 0 && dexOf(coin) === dex) this.mids[coin] = n;
      }
      this.lastTick[dex] = Date.now();
      this.listeners.forEach((_dexes, listener) => listener(this.mids));
    };
    socket.onerror = () => { /* onclose follows */ };
    socket.onclose = () => {
      if (this.socket !== socket) return;
      this.cleanup();
      if (this.active && this.wanted().size > 0) this.scheduleRetry();
    };
  }

  private scheduleRetry() {
    if (this.retry) return;
    this.retry = setTimeout(() => { this.retry = null; this.sync(); }, this.backoff);
    this.backoff = Math.min(this.backoff * 2, MAX_BACKOFF_MS);
  }

  private cleanup() {
    if (this.ping) { clearInterval(this.ping); this.ping = null; }
    if (this.connectTimer) { clearTimeout(this.connectTimer); this.connectTimer = null; }
    if (this.staleCheck) { clearInterval(this.staleCheck); this.staleCheck = null; }
    this.socket = null;
    this.subscribed.clear();
    this.drop();
  }

  private close() {
    if (this.retry) { clearTimeout(this.retry); this.retry = null; }
    const socket = this.socket;
    this.cleanup();
    try { socket?.close(); } catch { /* already closed */ }
  }
}

let feed: MidsFeed | null = null;
const shared = () => (feed ??= new MidsFeed());

/** Live mids for these coins while the calling screen is mounted (null until the first tick). */
export const useLiveMids = (coins: string[]): Record<string, number> => {
  const key = [...new Set(coins)].sort().join(',');
  const [mids, setMids] = useState<Record<string, number>>({});
  useEffect(() => {
    const list = key ? key.split(',') : [];
    if (!list.length) {
      setMids({});
      return undefined;
    }
    const f = shared();
    let last = 0;
    let pending: ReturnType<typeof setTimeout> | null = null;
    const pick = (all: Record<string, number>) => {
      const out: Record<string, number> = {};
      list.forEach((c) => { if (all[c] != null) out[c] = all[c]; });
      return out;
    };
    let latest: Record<string, number> = {};
    const listener: Listener = (all) => {
      latest = all;
      const now = Date.now();
      if (!Object.keys(pick(all)).length) {
        // Prices dropped (disconnected, stale): at once, never an old one later.
        if (pending) { clearTimeout(pending); pending = null; }
        setMids({});
      } else if (now - last >= RENDER_EVERY_MS) {
        last = now;
        setMids(pick(all));
      } else if (!pending) {
        pending = setTimeout(() => { pending = null; last = Date.now(); setMids(pick(latest)); },
          RENDER_EVERY_MS - (now - last));
      }
    };
    f.add(listener, new Set(list.map(dexOf)));
    const seeded: Record<string, number> = {};
    list.forEach((c) => { const v = f.latest(c); if (v != null) seeded[c] = v; });
    // Always, even empty: prices from an earlier subscription never linger.
    setMids(seeded);
    return () => {
      if (pending) clearTimeout(pending);
      f.remove(listener);
    };
  }, [key]);
  return mids;
};

/** One coin's live mid, or null. */
export const useLiveMid = (coin: string | null): number | null => {
  const mids = useLiveMids(coin ? [coin] : []);
  return coin ? mids[coin] ?? null : null;
};
