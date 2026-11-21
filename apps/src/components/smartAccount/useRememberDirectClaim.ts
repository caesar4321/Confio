// Keeps the device's record for the direct claim path (spec 6.7) current:
// whenever the server answers with a designation or an inherited account, its
// contract address (and the token addresses it reported) are written to the
// keychain-backed emergency store, so "Hacerlo sin Confío" still knows the
// account when the server cannot be reached. Fire and forget: a storage
// failure never touches the screen.
import { useEffect } from 'react';
import type { DirectClaimEntry } from '../../services/emergencyExit/directClaimStore';

type Incoming = Omit<DirectClaimEntry, 'savedAt'>;

export async function rememberDirectClaim(entries: Array<Partial<Incoming> | null>): Promise<void> {
  const usable = entries.filter((e): e is Incoming => !!e && typeof e.account === 'string' && e.account.length > 0);
  if (usable.length === 0) {
    return;
  }
  try {
    const [{ rememberDirectClaimEntries }, { emergencyStore }] = await Promise.all([
      import('../../services/emergencyExit/directClaimStore'),
      import('../../services/emergencyExit/store'),
    ]);
    await rememberDirectClaimEntries(emergencyStore, usable);
  } catch {
    // Best effort: the server path does not depend on it.
  }
}

export function useRememberDirectClaim<T>(
  list: T[] | null | undefined,
  toEntry: (item: T) => Partial<Incoming> | null,
): void {
  useEffect(() => {
    if (!list || list.length === 0) {
      return;
    }
    void rememberDirectClaim(list.map(toEntry));
    // toEntry is a pure mapping written inline at each call site.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [list]);
}
