// Emergency-exit reachability state machine
// (docs/plans/salida-de-emergencia-design.md).
//
// Principles enforced here, in code, not copy:
//  - The feature's EXISTENCE is never server-gated: this module only
//    decides prominence and wait times. A server faking health while
//    refusing sends can, at worst, impose the normal-state 72h cooloff.
//  - The server can never shorten, extend, or cancel a window: every
//    judgment is client-local, and every duration is measured against
//    chain block timestamps (chainClock), never the device clock.
//  - Faking death only accelerates: outage ≥ 72h ⇒ immediate exit. Both
//    waits are 72h so blocking Confío's domain on the device is never a
//    shorter way out than the normal path (72h + Confío Face).
//  - An independent Worker (workers/outage-status, outageStatus.ts) signs
//    whether IT can reach Confío. Confío hidden from this phone while the
//    Worker sees it up is a local block (a ring, or a national block), not
//    an outage: the normal rules apply. A signed "down since T" dates the
//    outage from T. No verifiable Worker answer ⇒ the phone's own 72h rule.
//  - A ban only counts while Confío answers: the ban route needs the
//    server to confirm the ban and grade Confío Face. A ban flag with
//    Confío unreachable is judged like any other unreachable state.
//
// RN-free by construction: probes take URLs, persistence is an injected
// KV store, and the pure classifier is exported for jest. The screen
// wires API_URL and the keychain-backed store.

import { chainNow, CHAIN_ENDPOINTS } from './chainClock';
import type { OutageStatus } from './outageStatus';

export const OUTAGE_IMMEDIATE_SECONDS = 72 * 3600;
export const NORMAL_COOLOFF_SECONDS = 72 * 3600;

/**
 * How long an elapsed cooloff stays usable before it re-arms.
 *
 * The wait is an anti-coercion device: it defends against whoever is on
 * the phone with the user RIGHT NOW. A cooloff that, once served, unlocked
 * the account forever turned that into a one-time toll — and the cheapest
 * attack became "get them to tap a button that visibly moves no money,
 * come back next week". So an unlock is an INTENT with a shelf life: use
 * it within the window or serve the wait again.
 *
 * Costs a real emergency nothing: ban and 72h-outage set `immediate`,
 * which never reads the cooloff at all. Missing the window only bites in
 * the NORMAL state, where ordinary sends work — worst case is "re-arm and
 * wait again", never "can't reach my money".
 *
 * 72h, not a week: the thing this bounds is the pool of DORMANT armed
 * accounts (armed, forgotten, permanently drainable in one session), and a
 * week is generous to precisely that population. 72h from eligibility
 * still covers the weekend pattern — arm Friday, eligible Saturday, act
 * Monday — which 48h does not.
 */
export const COOLOFF_VALID_SECONDS = 72 * 3600;

/**
 * 'blocked': Confío unreachable from this phone while the Worker, from
 * outside, sees it up. Same rules as 'normal' (cooloff, then face or a
 * second wait), with the face check necessarily unavailable.
 */
export type EmergencyState = 'normal' | 'blocked' | 'outage' | 'offline' | 'banned';

/** How stale a Worker statement may be, against chain time. */
export const OUTAGE_STATUS_FRESH_SECONDS = 30 * 60;

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
  /** Ban signal from the Apollo link (counts only while Confío answers). */
  banned?: boolean;
  /** Verified Worker statement, when one could be fetched. */
  outageStatus?: OutageStatus | null;
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

  if (confioOk && input.banned) {
    // The ban route: no wait, but the exit runs only after the server
    // confirms the ban and Confío Face passes (emergencyFace.ts).
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

  const worker = input.outageStatus;
  if (worker && Math.abs(chainNowSec - worker.checkedAtSec) <= OUTAGE_STATUS_FRESH_SECONDS) {
    if (worker.downSinceSec === null) {
      // Confío is up; only this phone can't see it. No outage window runs.
      return { state: 'blocked', outageStartSec: null, outageSeconds: 0, immediate: false, prominent: false };
    }
    // Confirmed from outside: the outage runs from when the Worker first saw it.
    const since = Math.min(worker.downSinceSec, chainNowSec);
    const seconds = chainNowSec - since;
    const confirmedImmediate = seconds >= OUTAGE_IMMEDIATE_SECONDS;
    return {
      state: 'outage', outageStartSec: since, outageSeconds: seconds,
      immediate: confirmedImmediate, prominent: confirmedImmediate,
    };
  }

  // Confío unreachable, chains reachable, no word from the Worker: the
  // phone's own outage window runs.
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
  opts: { banned?: boolean; fetchOutageStatus?: () => Promise<OutageStatus | null> } = {},
): Promise<ReachabilityResult & { chainNowSec: number | null }> => {
  // Ban signal: set by the Apollo error link when the security middleware
  // 403s an authenticated request, cleared by any later GraphQL success.
  // It only picks the ban route; the server still confirms the ban there.
  let banned = opts.banned;
  if (banned === undefined) {
    const { isBanSignaled } = await import('./banSignal');
    banned = await isBanSignaled(store);
  }
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

  let outageStatus: OutageStatus | null = null;
  if (!confioOk && chainNowSec !== null) {
    const fetchStatus = opts.fetchOutageStatus ?? (await import('./outageStatus')).fetchOutageStatus;
    outageStatus = await fetchStatus();
  }

  const result = classifyReachability({
    confioOk, chainOk, prevOutageStartSec, chainNowSec, banned, outageStatus,
  });

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
  reason: 'immediate' | 'cooloff_elapsed' | 'cooloff_pending' | 'cooloff_expired' | 'no_request' | 'offline';
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

/**
 * Spend the unlock. Call this ONLY after an exit actually broadcast, so
 * the next voluntary exit serves the wait again.
 *
 * Deliberately not called on failure: a partial or failed exit must stay
 * retryable this instant — re-arming mid-emergency, with funds half-moved,
 * would be the cruellest possible moment to impose a day's wait.
 */
export const consumeExitCooloff = async (store: KVStore, accountKey: string): Promise<void> =>
  store.del(cooloffKey(accountKey));

const faceWaiverKey = (accountKey: string) => `confio_emergency_face_waiver_v1:${accountKey}`;

/**
 * The server can never veto an exit. When Confío Face fails or cannot run,
 * the person may continue without it: that spends the current unlock and
 * serves a second full wait, after which the exit needs no face. Local and
 * chain-timed like every other window here.
 */
export const waiveFaceWithNewCooloff = async (store: KVStore, accountKey: string): Promise<void> => {
  await store.del(cooloffKey(accountKey));
  const { requestedAtSec } = await requestExitCooloff(store, accountKey);
  await store.set(faceWaiverKey(accountKey), String(requestedAtSec));
};

const banWaitKey = (accountKey: string) => `confio_emergency_ban_wait_v1:${accountKey}`;

/**
 * A banned account that never did KYC has no face to check, so the server
 * sends it through the normal waiting period instead of the immediate ban
 * route. Remembered locally so the screen shows the wait; it can only slow
 * the exit, and the server is asked again before anything is sent.
 */
export const markBanRouteWait = async (store: KVStore, accountKey: string): Promise<void> =>
  store.set(banWaitKey(accountKey), '1');

export const hasBanRouteWait = async (store: KVStore, accountKey: string): Promise<boolean> =>
  (await store.get(banWaitKey(accountKey))) === '1';

export const clearBanRouteWait = async (store: KVStore, accountKey: string): Promise<void> =>
  store.del(banWaitKey(accountKey));

/** True when the current unlock was served as a face waiver. */
export const hasFaceWaiver = async (store: KVStore, accountKey: string): Promise<boolean> => {
  const [waiver, cooloff] = await Promise.all([
    store.get(faceWaiverKey(accountKey)),
    store.get(cooloffKey(accountKey)),
  ]);
  return !!waiver && waiver === cooloff;
};

/** DEV-ONLY QA helper: backdate the pending cooloff so stage 2 renders
 * without waiting a day. No-op in release builds — the guard is inside
 * so a stray call site can never ship the bypass. */
export const devElapseCooloff = async (store: KVStore, accountKey: string): Promise<void> => {
  // eslint-disable-next-line no-undef
  if (typeof __DEV__ === 'undefined' || !__DEV__) return;
  const raw = await store.get(cooloffKey(accountKey));
  if (!raw) return;
  await store.set(cooloffKey(accountKey), String(parseInt(raw, 10) - NORMAL_COOLOFF_SECONDS - 60));
};

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
  if (elapsed >= NORMAL_COOLOFF_SECONDS + COOLOFF_VALID_SECONDS) {
    // Stale unlock: drop it so the user is offered a fresh wait rather
    // than a dead button. Deleting here (not just reporting) keeps the
    // stored state and the answer from drifting apart.
    await store.del(cooloffKey(accountKey));
    return { eligible: false, reason: 'cooloff_expired', requestedAtSec };
  }
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
