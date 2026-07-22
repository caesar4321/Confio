// Ban signal for the emergency exit (docs/plans/salida-de-emergencia-design.md,
// "Ban work package").
//
// The backend's SecurityMiddleware answers EVERY authenticated request
// from a banned user with a plain-text 403 ("Your account has been
// suspended…") — before any GraphQL resolver runs. Without this signal a
// banned user's emergency screen would read the server as healthy (the
// unauthenticated probe passes the middleware) and impose the 24h
// cooloff: a de-facto one-day freeze, exactly what the design forbids.
//
// Trusting this server-originated signal is safe by construction: the
// flag can only ACCELERATE the exit (banned ⇒ immediate), never delay
// it. Any later successful GraphQL response clears it (un-ban).
//
// An in-memory mirror avoids a keychain round-trip per GraphQL response;
// the persisted flag survives restarts (banned users stay banned across
// launches — every request they make keeps 403ing anyway).

import type { KVStore } from './reachability';

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
