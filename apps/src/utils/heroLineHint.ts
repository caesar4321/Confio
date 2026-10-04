// Remembers, per account, whether Home showed the month line last time, so a
// cold launch can reserve its row before data arrives and Enviar/Recibir
// never move (design 2A, cold-launch amendment 2026-10-04).
//
// Only booleans keyed by the app's account id: no amounts leave the device
// state. Keychain, not AsyncStorage (project rule). Read once at import so
// the answer is usually ready by the time Home mounts; Home waits for it
// (heroLineHintReady) before its first layout decision.
import * as Keychain from 'react-native-keychain';

const SERVICE = 'com.confio.heroLineHint';
let hints: Record<string, boolean> = {};
let loaded = false;
// What the Keychain actually holds; a failed write leaves memory "dirty" so
// the next call retries even if the answer did not change.
let persisted = '{}';
let writing = false;

export const heroLineHintReady: Promise<void> = (async () => {
  try {
    const creds = await Keychain.getGenericPassword({ service: SERVICE });
    if (creds && creds.password) {
      const parsed = JSON.parse(creds.password);
      if (parsed && typeof parsed === 'object') {
        // Answers recorded while this read was in flight are newer: they win.
        hints = { ...parsed, ...hints };
        persisted = creds.password;
      }
    }
  } catch {
    // No stored hint = old behavior (no reserved row), never an error. Keep
    // any answers recorded meanwhile.
  } finally {
    loaded = true;
    flush(); // writes any answers recorded before the read finished
  }
})();

export function isHeroLineHintLoaded(): boolean {
  return loaded;
}

export function hadHeroLine(accountKey: string): boolean {
  return hints[accountKey] === true;
}

function flush() {
  // Before the stored hints are read, a write would drop other accounts' ones.
  if (!loaded) return;
  const json = JSON.stringify(hints);
  if (writing || json === persisted) return;
  writing = true;
  Keychain.setGenericPassword('hints', json, {
    service: SERVICE,
    accessible: Keychain.ACCESSIBLE.AFTER_FIRST_UNLOCK,
  })
    .then((ok) => (ok ? (persisted = json, true) : false))
    .catch(() => false)
    .then((ok) => {
      writing = false;
      // A change made while this write was in flight goes out now; after a
      // failure the next set retries (no tight loop on a broken Keychain).
      if (ok) flush();
    });
}

export function setHadHeroLine(accountKey: string, shown: boolean) {
  // Explicit, even for false: a missing key reads as false, but before the
  // stored hints load an explicit false must still override a stored true.
  if (hints[accountKey] !== shown) hints = { ...hints, [accountKey]: shown };
  flush();
}
