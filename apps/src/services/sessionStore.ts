import * as Keychain from 'react-native-keychain';
import { recordKeychainRead, resetKeychainDiagnosticForTests, setSessionCacheActive } from './keychainDiagnostic';

/**
 * The signed-in session (access + refresh JWT), held in memory.
 *
 * The keychain stays the source of truth on disk. What changes is who reads
 * it: every GraphQL request used to decrypt the session from the Android
 * keystore twice, and a one-second timer read it again, all behind the
 * keychain library's single lock. On a phone whose keystore answers slowly
 * that queue outgrew the 20 s query deadline and Home never loaded. Requests
 * now read this copy; the keystore is read once per process.
 *
 * The copy can never go stale silently: `setGenericPassword` and
 * `resetGenericPassword` are observed at the library boundary, so EVERY
 * writer of the session service, present or future, wherever it imports the
 * keychain from, updates or drops the copy. If that observer cannot be
 * installed the cache stays off and reads go to the keychain as before.
 */

export const AUTH_KEYCHAIN_SERVICE = 'com.confio.auth';
export const AUTH_KEYCHAIN_USERNAME = 'auth_tokens';

export type SessionCredentials = false | { username: string; password: string; service?: string; storage?: string };

// undefined = not known (read the keychain); false = known signed out.
let cached: SessionCredentials | undefined;
// Bumped when a write or reset of the session service starts and again when
// it ends: a read that overlapped one must not publish what it saw.
let epoch = 0;
// Orders writes and resets among themselves: only the latest may publish.
let writeSeq = 0;
// Writes and resets in flight. When two overlap, which one the keychain
// applied last is not knowable from here, so neither publishes and the next
// read asks the keychain.
let pendingWrites = 0;
let overlapped = false;
let inFlightRead: Promise<SessionCredentials> | null = null;
let inFlightEpoch = -1;
let observerInstalled = false;
const clearedListeners = new Set<() => void>();

const isSessionService = (options: unknown): boolean =>
  !!options && typeof options === 'object' && (options as { service?: unknown }).service === AUTH_KEYCHAIN_SERVICE;

function notifyCleared() {
  clearedListeners.forEach((listener) => {
    try { listener(); } catch { /* one listener must not stop the rest */ }
  });
}

function beginWrite() {
  if (pendingWrites > 0) overlapped = true;
  pendingWrites += 1;
  epoch += 1;
  cached = undefined;
}

function endWrite(published: SessionCredentials | undefined) {
  pendingWrites -= 1;
  // Always assigned, never left as it was: a read that finished while this
  // write was in flight must not survive it. Unknown (undefined) whenever
  // the write overlapped another, failed, or was overtaken.
  cached = overlapped ? undefined : published;
  if (pendingWrites === 0) overlapped = false;
  // A read that overlapped this write may hold the value from before it.
  epoch += 1;
}

/**
 * Start observing session writes; called once at boot (setup/sessionObserver.ts).
 * Until it runs, and if it cannot be installed, nothing is cached and every
 * read goes to the keychain as it always did.
 */
export function installSessionObserver() {
  if (observerInstalled) return;
  const lib = Keychain as unknown as Record<string, any>;
  const originalSet = lib.setGenericPassword;
  const originalReset = lib.resetGenericPassword;
  if (typeof originalSet !== 'function' || typeof originalReset !== 'function') return;

  const observedSet = async (username: string, password: string, options?: unknown) => {
    if (!isSessionService(options)) return originalSet(username, password, options);
    const mine = ++writeSeq;
    // Unknown while the write is in flight: a reader goes to the keychain
    // and queues behind this write, exactly as it did before the cache.
    beginWrite();
    let published: SessionCredentials | undefined;
    try {
      const result = await originalSet(username, password, options);
      if (mine === writeSeq && result !== false) {
        published = { username, password, service: AUTH_KEYCHAIN_SERVICE, storage: 'memory' };
      }
      return result;
    } finally {
      endWrite(published);
      // A write that failed may have removed the entry it was replacing
      // (iOS deletes before it inserts). Listeners re-read, so a session
      // lost that way is noticed now and not at the next foreground.
      if (published === undefined) notifyCleared();
    }
  };
  const observedReset = async (options?: unknown) => {
    if (!isSessionService(options)) return originalReset(options);
    const mine = ++writeSeq;
    beginWrite();
    let published: SessionCredentials | undefined;
    try {
      const result = await originalReset(options);
      if (mine === writeSeq && result !== false) published = false;
      return result;
    } finally {
      endWrite(published);
      // Listeners re-read: a reset that reported failure may still have
      // removed the entry, and a newer write may already have replaced it.
      notifyCleared();
    }
  };

  // The library also exports the same functions on a default object
  // (`import Keychain from ...`); both doors must be observed.
  const targets = [lib, lib.default].filter((target) => target && typeof target === 'object');
  try {
    targets.forEach((target) => {
      target.setGenericPassword = observedSet;
      target.resetGenericPassword = observedReset;
    });
  } catch {
    // Falls through to the check below.
  }
  // Frozen or getter-only exports would leave an original in place: then a
  // writer is invisible and a cached copy could outlive an account switch.
  observerInstalled = targets.every(
    (target) => target.setGenericPassword === observedSet && target.resetGenericPassword === observedReset,
  );
  // Sent with the timings, so the server can tell a build where this did
  // not take effect from one where it did.
  setSessionCacheActive(observerInstalled);
}


async function readFromKeychain(): Promise<SessionCredentials> {
  const startedAt = Date.now();
  let credentials;
  try {
    credentials = await Keychain.getGenericPassword({
      service: AUTH_KEYCHAIN_SERVICE,
      username: AUTH_KEYCHAIN_USERNAME,
    });
  } catch (error) {
    // A keystore that stalls and then refuses is exactly the phone this
    // timing exists to find: count the time it took to fail.
    recordKeychainRead(Date.now() - startedAt, 'error');
    throw error;
  }
  // Reported to the server as a header, so a phone whose keystore is slow
  // identifies itself (services/mobileClientHeaders.ts).
  recordKeychainRead(Date.now() - startedAt, credentials ? (credentials as any).storage : undefined);
  return credentials as SessionCredentials;
}

/**
 * The stored session, in the shape `Keychain.getGenericPassword` returns.
 * Keychain errors propagate: "could not read" is not "signed out".
 */
export async function getSessionCredentials(): Promise<SessionCredentials> {
  if (!observerInstalled) return readFromKeychain();
  if (cached !== undefined) return cached;
  // Share a read only with callers from the same epoch: one that began
  // before a write must not answer a caller that arrived after it.
  if (inFlightRead && inFlightEpoch === epoch) return inFlightRead;
  const mine = epoch;
  const read = readFromKeychain()
    .then((credentials) => {
      // Only a session that was found is remembered. "Nothing there" from a
      // read is not trusted as signed out: iOS can answer empty right after
      // launch, and callers retry it (AuthContext getStoredAuthCredentials).
      // Nor is anything read while a write or reset is in flight: the read
      // may have run before it landed and seen the session it replaces.
      if (mine === epoch && pendingWrites === 0 && credentials) cached = credentials;
      return credentials;
    })
    .finally(() => {
      if (inFlightRead === read) inFlightRead = null;
    });
  inFlightRead = read;
  inFlightEpoch = mine;
  return read;
}

/**
 * Forget the copy, so the next read asks the keychain. For a caller that
 * has just found the keychain does not hold what a write reported storing
 * (the read-back checks after sign-in): memory must not keep vouching for it.
 */
export function invalidateSessionCache() {
  epoch += 1;
  cached = undefined;
}

/** False when the keychain could not be observed: nothing is cached and no reset is announced. */
export function isSessionObserverInstalled(): boolean {
  return observerInstalled;
}

/**
 * Called after any reset of the session entry finishes (sign-out, a rejected
 * refresh token), and after a write that did not take, which may have removed
 * the entry. The session may still be there or already replaced: listeners
 * confirm with `getSessionCredentials()` before acting.
 */
export function onSessionReset(listener: () => void): () => void {
  clearedListeners.add(listener);
  return () => { clearedListeners.delete(listener); };
}

/** Tests only: forget the copy and the timings. */
export function resetSessionStoreForTests() {
  cached = undefined;
  inFlightRead = null;
  epoch += 1;
  writeSeq += 1;
  pendingWrites = 0;
  overlapped = false;
  resetKeychainDiagnosticForTests();
  setSessionCacheActive(observerInstalled);
}
