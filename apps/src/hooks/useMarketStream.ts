// One market's live candle and best bid/ask from Hyperliquid's own feed
// (wss `candle` + `bbo`), for the candlestick chart: a trader timing an entry
// on 1-5 minute candles needs the forming candle and the real spread.
//
// Its own socket, open only while the chart shows candles and the app is in
// the foreground. Display only, like useLiveMids: nothing is signed from it.
// Re-renders are capped at one a second.
import { useEffect, useState } from 'react';
import { AppState, AppStateStatus } from 'react-native';

import type { PerpOhlc } from '../services/perps';
import type { OhlcInterval } from './usePerps';

const WS_URL = 'wss://api.hyperliquid.xyz/ws';
const PING_MS = 10_000;
const RENDER_EVERY_MS = 1_000;
const MAX_BACKOFF_MS = 30_000;
// Nothing heard for this long: the stream is not shown (a stale spread is
// worse than none; the server's candles take over) …
const STALE_MS = 15_000;
// … and for this long, the socket is closed and opened again.
const SILENT_MS = 30_000;
const KEEP_STREAMED = 10;

export interface Bbo {
  bid: number;
  ask: number;
  at: number; // when it arrived, ms
}

const num = (v: unknown): number | null => {
  const n = typeof v === 'string' ? Number(v) : typeof v === 'number' ? v : NaN;
  return Number.isFinite(n) && n > 0 ? n : null;
};

/** A feed `candle` message → a candle, or null when anything is off. */
export const parseCandle = (data: any, coin: string, interval: string): PerpOhlc | null => {
  if (!data || data.s !== coin || data.i !== interval || typeof data.t !== 'number') return null;
  const [open, high, low, close] = [num(data.o), num(data.h), num(data.l), num(data.c)];
  if (open == null || high == null || low == null || close == null) return null;
  const volume = Number(data.v);
  return { time: data.t, open, high, low, close, volume: Number.isFinite(volume) && volume >= 0 ? volume : 0 };
};

/** A feed `bbo` message → bid/ask, or null when a side is missing or crossed. */
export const parseBbo = (data: any, coin: string, now: number): Bbo | null => {
  if (!data || data.coin !== coin || !Array.isArray(data.bbo)) return null;
  const bid = num(data.bbo[0]?.px);
  const ask = num(data.bbo[1]?.px);
  if (bid == null || ask == null || ask < bid) return null;
  return { bid, ask, at: now };
};

/** History with the streamed candles on top: each replaces the server's copy
 *  of its candle (a closed one keeps its final values) or starts the next. */
export const mergeLive = (history: PerpOhlc[], live: PerpOhlc[]): PerpOhlc[] => {
  if (live.length === 0 || history.length === 0) return history;
  const byTime = new Map(live.map((c) => [c.time, c]));
  const first = history[0].time;
  const merged = history.map((c) => byTime.get(c.time) ?? c);
  const last = merged[merged.length - 1].time;
  const newer = live.filter((c) => c.time > last && c.time >= first).sort((a, b) => a.time - b.time);
  return newer.length || merged.some((c, i) => c !== history[i]) ? [...merged, ...newer] : history;
};

export const useMarketStream = (coin: string | undefined, interval: OhlcInterval, enabled: boolean) => {
  const [live, setLive] = useState<PerpOhlc[]>([]);
  const [bbo, setBbo] = useState<Bbo | null>(null);
  const [lastMessage, setLastMessage] = useState(0);
  const [active, setActive] = useState(AppState.currentState === 'active');
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const sub = AppState.addEventListener('change', (s: AppStateStatus) => setActive(s === 'active'));
    return () => sub.remove();
  }, []);

  useEffect(() => {
    setLive([]);
    setBbo(null);
    setLastMessage(0);
    if (!coin || !enabled || !active) return undefined;
    let socket: WebSocket | null = null;
    let closed = false;
    let backoff = 1_000;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let ping: ReturnType<typeof setInterval> | null = null;
    let heard = 0; // last message on the current socket (prices, quotes or pong); 0 = none yet
    let opened = 0; // when the current socket was started (the handshake's own clock)
    const streamed = new Map<number, PerpOhlc>();
    let dirty = false;
    let pendingBbo: Bbo | null = null;
    let dropBbo = false;

    const restart = () => {
      // Handlers off first: a half-open socket may never fire onclose.
      const ws = socket;
      socket = null;
      if (ping) clearInterval(ping);
      ping = null;
      // Nothing from the old socket outlives it: a candle that closed during the
      // gap would keep its partial values over the server's final ones.
      heard = 0;
      streamed.clear();
      dirty = true;
      pendingBbo = null;
      dropBbo = true;
      if (ws) {
        ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
        try { ws.close(); } catch { /* already gone */ }
      }
      if (closed) return;
      retry = setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
    };

    const flush = setInterval(() => {
      const t = Date.now();
      // Silent too long (a network change without a close): start over.
      if (socket && t - Math.max(heard, opened) > SILENT_MS) restart();
      if (dirty) {
        dirty = false;
        setLive([...streamed.values()].sort((a, b) => a.time - b.time));
      }
      if (dropBbo) setBbo(null);
      dropBbo = false;
      if (pendingBbo) setBbo(pendingBbo);
      pendingBbo = null;
      setLastMessage(heard);
      setNow(t);
    }, RENDER_EVERY_MS);

    function connect() {
      if (closed) return;
      const ws = new WebSocket(WS_URL);
      socket = ws;
      opened = Date.now(); // the handshake gets SILENT_MS too; nothing is fresh until a message
      ws.onopen = () => {
        backoff = 1_000;
        ws.send(JSON.stringify({ method: 'subscribe', subscription: { type: 'candle', coin, interval } }));
        ws.send(JSON.stringify({ method: 'subscribe', subscription: { type: 'bbo', coin } }));
        ping = setInterval(() => { try { ws.send(JSON.stringify({ method: 'ping' })); } catch { /* the silence check restarts */ } }, PING_MS);
      };
      ws.onmessage = (event) => {
        heard = Date.now();
        let msg: any;
        try { msg = JSON.parse(String(event.data)); } catch { return; }
        if (msg?.channel === 'candle') {
          const candle = parseCandle(msg.data, coin!, interval);
          if (candle) {
            streamed.set(candle.time, candle);
            // Only the latest few matter: older ones are in the server's history by then.
            if (streamed.size > KEEP_STREAMED) streamed.delete(Math.min(...streamed.keys()));
            dirty = true;
          }
        } else if (msg?.channel === 'bbo') {
          const quote = parseBbo(msg.data, coin!, heard);
          if (quote) pendingBbo = quote;
          else if (msg.data?.coin === coin) {
            // This market's book lost a side (or crossed): no quote beats an old one.
            pendingBbo = null;
            dropBbo = true;
          }
        }
      };
      ws.onclose = () => restart();
      ws.onerror = () => restart();
    }
    connect();

    return () => {
      closed = true;
      clearInterval(flush);
      if (retry) clearTimeout(retry);
      restart();
    };
  }, [coin, interval, enabled, active]);

  // Fresh while the socket talks (a quiet market's quote can stand still and be right).
  const fresh = lastMessage > 0 && now - lastMessage <= STALE_MS;
  return { live: fresh ? live : [], bbo: fresh ? bbo : null };
};
