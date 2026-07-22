// Emergency-exit reachability state machine
// (docs/plans/salida-de-emergencia-design.md).
//
// Principles enforced here, in code, not copy:
//  - The feature's EXISTENCE is never server-gated: this module only
//    decides prominence and wait times. A server faking health while
//    refusing sends can, at worst, impose the normal-state 24h cooloff.
//  - The server can never shorten, extend, or cancel a window: every
//    judgment is client-local, and every duration is measured against
//    chain block timestamps (chainClock), never the device clock.
//  - Faking death only accelerates: outage ≥ 24h ⇒ immediate exit.
//
// RN-free by construction: probes take URLs, persistence is an injected
// KV store, and the pure classifier is exported for jest. The screen
// wires API_URL and the keychain-backed store.

import { chainNow, CHAIN_ENDPOINTS } from './chainClock';

export const OUTAGE_IMMEDIATE_SECONDS = 24 * 3600;
export const NORMAL_COOLOFF_SECONDS = 24 * 3600;

export type EmergencyState = 'normal' | 'outage' | 'offline' | 'banned';

export interface KVStore {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  del(key: string): Promise<void>;
}

export interface ReachabilityInput {
  confioOk: boolean;
  chainOk: boolean;
  /** Persisted chain-ts when the current outage was first observed. */
  prevOutageStartSec: number | null;
  /** null when chains are unreachable (no window can advance). */
  chainNowSec: number | null;
  /** Explicit ban response from a LIVE server (wired when backend ships it). */
  banned?: boolean;
}

export interface ReachabilityResult {
  state: EmergencyState;
  /** Persist this (or clear when null): outage window start, chain time. */
  outageStartSec: number | null;
  outageSeconds: number;
  /** Exit may run with no wait: ban, or outage past the immediate bar. */
  immediate: boolean;
  /** Surface strongly (home + Seguridad top) vs low-key entry. */
  prominent: boolean;
}

/** Pure classifier — the whole timing policy lives here (jest-covered). */
export const classifyReachability = (input: ReachabilityInput): ReachabilityResult => {
  const { confioOk, chainOk, prevOutageStartSec, chainNowSec } = input;

  if (input.banned) {
    // Ban comes from a live server; any wait here would be a de-facto
    // freeze and contradicts the published narrative. Immediate.
    return { state: 'banned', outageStartSec: null, outageSeconds: 0, immediate: true, prominent: true };
  }

  if (confioOk) {
    // Server demonstrably alive ⇒ normal sends exist; outage window resets.
    return { state: 'normal', outageStartSec: null, outageSeconds: 0, immediate: false, prominent: false };
  }

  if (!chainOk || chainNowSec === null) {
    // Airplane mode / no internet: nothing can broadcast, so nothing is
    // gated — but the outage window must NOT advance on unverifiable
    // time, and must not reset either (the outage may be real).
    return {
      state: 'offline',
      outageStartSec: prevOutageStartSec,
      outageSeconds: 0,
      immediate: false,
      prominent: false,
    };
  }

  // Confío unreachable, chains reachable: the outage window runs.
  const start = prevOutageStartSec ?? chainNowSec;
  const outageSeconds = Math.max(0, chainNowSec - start);
  const immediate = outageSeconds >= OUTAGE_IMMEDIATE_SECONDS;
  return { state: 'outage', outageStartSec: start, outageSeconds, immediate, prominent: immediate };
};

// ── Probes ──────────────────────────────────────────────────────────────

const withTimeout = async (url: string, init: RequestInit, timeoutMs: number): Promise<Response> => {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: ctrl.signal });
  } finally {
    clearTimeout(t);
  }
};

/** Any well-formed GraphQL response (even an auth error) proves liveness. */
export const probeConfio = async (graphqlUrl: string, timeoutMs = 8000): Promise<boolean> => {
  try {
    const res = await withTimeout(graphqlUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: '{__typename}' }),
    }, timeoutMs);
    if (!res.ok && res.status >= 500) return false;
    await res.json();
    return true;
  } catch {
    return false;
  }
};

export const probeChains = async (timeoutMs = 8000): Promise<boolean> => {
  for (const rpc of CHAIN_ENDPOINTS.BSC_RPCS) {
    try {
      const res = await withTimeout(rpc, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'eth_blockNumber', params: [] }),
      }, timeoutMs);
      if (res.ok) return true;
    } catch { /* next */ }
  }
  for (const node of CHAIN_ENDPOINTS.ALGOD_NODES) {
    try {
      const res = await withTimeout(`${node}/v2/status`, {}, timeoutMs);
      if (res.ok) return true;
    } catch { /* next */ }
  }
  return false;
};

// ── Persistent evaluation ───────────────────────────────────────────────

const OUTAGE_KEY = 'confio_emergency_outage_start_v1';
const cooloffKey = (accountKey: string) => `confio_emergency_cooloff_v1_${accountKey}`;

export const evaluateEmergencyState = async (
  store: KVStore,
  graphqlUrl: string,
  opts: { banned?: boolean } = {},
): Promise<ReachabilityResult & { chainNowSec: number | null }> => {
  const confioOk = await probeConfio(graphqlUrl);
  let chainNowSec: number | null = null;
  let chainOk = false;
  try {
    chainNowSec = (await chainNow()).sec;
    chainOk = true;
  } catch {
    chainOk = await probeChains(); // reachable but clock endpoints odd — stay conservative
  }

  const prevRaw = await store.get(OUTAGE_KEY);
  const prevOutageStartSec = prevRaw ? parseInt(prevRaw, 10) || null : null;

  const result = classifyReachability({ confioOk, chainOk, prevOutageStartSec, chainNowSec, banned: opts.banned });

  if (result.outageStartSec === null) {
    if (prevOutageStartSec !== null) await store.del(OUTAGE_KEY);
  } else if (result.outageStartSec !== prevOutageStartSec) {
    await store.set(OUTAGE_KEY, String(result.outageStartSec));
  }

  return { ...result, chainNowSec };
};

// ── Normal-state cooloff (per account) ──────────────────────────────────

export interface ExitEligibility {
  eligible: boolean;
  reason: 'immediate' | 'cooloff_elapsed' | 'cooloff_pending' | 'no_request' | 'offline';
  remainingSec?: number;
  requestedAtSec?: number;
}

/** Start (or return the existing) cooloff for this account. Chain-timed. */
export const requestExitCooloff = async (
  store: KVStore,
  accountKey: string,
): Promise<{ requestedAtSec: number }> => {
  const existing = await store.get(cooloffKey(accountKey));
  if (existing) return { requestedAtSec: parseInt(existing, 10) };
  const { sec } = await chainNow();
  await store.set(cooloffKey(accountKey), String(sec));
  return { requestedAtSec: sec };
};

export const cancelExitCooloff = async (store: KVStore, accountKey: string): Promise<void> =>
  store.del(cooloffKey(accountKey));

export const getExitEligibility = async (
  store: KVStore,
  accountKey: string,
  state: ReachabilityResult & { chainNowSec: number | null },
): Promise<ExitEligibility> => {
  if (state.immediate) return { eligible: true, reason: 'immediate' };
  if (state.chainNowSec === null) return { eligible: false, reason: 'offline' };

  const raw = await store.get(cooloffKey(accountKey));
  if (!raw) return { eligible: false, reason: 'no_request' };
  const requestedAtSec = parseInt(raw, 10);
  const elapsed = state.chainNowSec - requestedAtSec;
  if (elapsed >= NORMAL_COOLOFF_SECONDS) {
    return { eligible: true, reason: 'cooloff_elapsed', requestedAtSec };
  }
  return {
    eligible: false,
    reason: 'cooloff_pending',
    requestedAtSec,
    remainingSec: NORMAL_COOLOFF_SECONDS - elapsed,
  };
};
