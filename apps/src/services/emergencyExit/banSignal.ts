// Ban signal: routes a suspended user to the BlockedAccount announcement.
//
// The backend's SecurityMiddleware answers EVERY authenticated request
// from a banned user with a plain-text 403 ("Your account has been
// suspended…") — before any GraphQL resolver runs. This flag remembers it
// so the app opens on the announcement instead of a broken home screen.
// It has NO effect on Salida de emergencia, which opens only on the
// on-chain heartbeat (docs/plans/salida-de-emergencia-design.md § Phase 3).
// Any later successful authenticated GraphQL response clears it (un-ban).
//
// An in-memory mirror avoids a keychain round-trip per GraphQL response;
// the persisted flag survives restarts (banned users stay banned across
// launches — every request they make keeps 403ing anyway).

import type { KVStore } from './kvStore';

const BAN_KEY = 'confio_emergency_ban_signal_v1';

let memory: boolean | null = null; // null = not yet loaded

// Transition subscribers (false→true only): the app navigates to the
// blocked screen from here, so services never import navigation.
type BanListener = () => void;
const listeners = new Set<BanListener>();
export const onBanSignal = (cb: BanListener): (() => void) => {
  listeners.add(cb);
  return () => listeners.delete(cb);
};

/** Returns true only on the false→true transition, so callers can react
 * (navigate, log) exactly once per ban episode. */
export const markBanSignal = async (store: KVStore): Promise<boolean> => {
  if (memory === true) return false;
  memory = true;
  await store.set(BAN_KEY, '1');
  listeners.forEach((cb) => { try { cb(); } catch { /* listener's problem */ } });
  return true;
};

export const clearBanSignal = async (store: KVStore): Promise<void> => {
  if (memory === false) return;
  memory = false;
  await store.del(BAN_KEY);
};

export const isBanSignaled = async (store: KVStore): Promise<boolean> => {
  if (memory === null) memory = (await store.get(BAN_KEY)) === '1';
  return memory;
};

/** The middleware's exact signature: HTTP 403 with the suspension text.
 * Both must match — bare 403s can come from proxies/WAFs. */
export const looksLikeBanResponse = (statusCode?: number, bodyText?: string): boolean =>
  statusCode === 403 && !!bodyText && bodyText.toLowerCase().includes('suspended');

/** A success may clear the ban ONLY if its request carried auth — the sole
 * proof the security middleware evaluated this user and let them through.
 * Anonymous operations (RefreshToken, GetLegalDocument, …) pass the
 * middleware even while banned, so their 200s prove nothing. Decided from
 * the request headers, never from operation names — a name list rotted
 * silently (Apollo's operationName is the definition name, not the field). */
export const successProvesUnbanned = (headers?: Record<string, unknown>): boolean =>
  !!(headers && (headers.Authorization || headers.authorization));
