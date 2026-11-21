// What a beneficiary's phone keeps so the direct claim path (spec 6.7) works
// with Confío's server unreachable: the account address (shown on the
// acceptance screen), whose account it is, and token addresses the server
// once reported, keyed by the opaque designation id.
//
// Persisted through the injected KVStore; the app binds it to the keychain
// (store.ts, react-native-keychain), never AsyncStorage. Nothing here is a
// secret, and nothing here is ever sent to the server as authority: the
// address is only the `to` of a transaction the person signs.

import type { KVStore } from './kvStore';
import { isAccountAddress } from './directClaim';

export const DIRECT_CLAIM_STORE_KEY = 'smart_account_direct_claim_v1';
const MAX_ENTRIES = 20;

export interface DirectClaimEntry {
  /** Lowercase contract address. */
  account: string;
  designationId?: string;
  inheritedAccountId?: string;
  ownerName?: string;
  chainName?: string;
  /** Token addresses seen in this account (lowercase). */
  tokens?: string[];
  savedAt: number;
}

const clean = (raw: unknown): DirectClaimEntry | null => {
  const e = raw as Partial<DirectClaimEntry> | null;
  if (!e || !isAccountAddress(e.account)) {
    return null;
  }
  const str = (v: unknown) => (typeof v === 'string' && v.length > 0 && v.length <= 200 ? v : undefined);
  return {
    account: e.account.toLowerCase(),
    designationId: str(e.designationId),
    inheritedAccountId: str(e.inheritedAccountId),
    ownerName: str(e.ownerName),
    chainName: str(e.chainName),
    tokens: Array.isArray(e.tokens)
      ? [...new Set(e.tokens.filter(isAccountAddress).map((t) => t.toLowerCase()))].slice(0, 200)
      : undefined,
    savedAt: typeof e.savedAt === 'number' ? e.savedAt : 0,
  };
};

export async function loadDirectClaimEntries(store: KVStore): Promise<DirectClaimEntry[]> {
  try {
    const raw = await store.get(DIRECT_CLAIM_STORE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return (Array.isArray(parsed) ? parsed : []).map(clean).filter((e): e is DirectClaimEntry => !!e);
  } catch {
    return [];
  }
}

/** Merge entries by account address (a newer value wins field by field). */
export async function rememberDirectClaimEntries(
  store: KVStore,
  incoming: ReadonlyArray<Omit<DirectClaimEntry, 'savedAt'> & { savedAt?: number }>,
  now: number = Date.now(),
): Promise<void> {
  const fresh = incoming
    .map((e) => clean({ ...e, savedAt: e.savedAt ?? now }))
    .filter((e): e is DirectClaimEntry => !!e);
  if (fresh.length === 0) {
    return;
  }
  const current = await loadDirectClaimEntries(store);
  const byAccount = new Map(current.map((e) => [e.account, e]));
  let changed = false;
  for (const e of fresh) {
    const prev = byAccount.get(e.account);
    const merged: DirectClaimEntry = {
      account: e.account,
      designationId: e.designationId ?? prev?.designationId,
      inheritedAccountId: e.inheritedAccountId ?? prev?.inheritedAccountId,
      ownerName: e.ownerName ?? prev?.ownerName,
      chainName: e.chainName ?? prev?.chainName,
      tokens: [...new Set([...(prev?.tokens ?? []), ...(e.tokens ?? [])])],
      savedAt: e.savedAt,
    };
    if (!merged.tokens?.length) {
      delete merged.tokens;
    }
    const comparable = (x: DirectClaimEntry) => JSON.stringify({ ...x, savedAt: 0 });
    if (!prev || comparable(merged) !== comparable(prev)) {
      changed = true;
    }
    byAccount.set(e.account, merged);
  }
  if (!changed) {
    return;
  }
  const next = [...byAccount.values()].sort((x, y) => y.savedAt - x.savedAt).slice(0, MAX_ENTRIES);
  await store.set(DIRECT_CLAIM_STORE_KEY, JSON.stringify(next));
}

/** The entry for a designation, or for an account address. */
export function findDirectClaimEntry(
  entries: readonly DirectClaimEntry[],
  key: { designationId?: string | null; account?: string | null },
): DirectClaimEntry | null {
  if (key.designationId) {
    const hit = entries.find((e) => e.designationId === key.designationId);
    if (hit) {
      return hit;
    }
  }
  if (key.account) {
    const a = key.account.toLowerCase();
    return entries.find((e) => e.account === a) ?? null;
  }
  return null;
}
