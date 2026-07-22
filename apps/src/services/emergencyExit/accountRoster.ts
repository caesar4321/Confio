// Local mirror of the user's account roster, for the emergency exit
// (docs/plans/salida-de-emergencia-design.md).
//
// The SERVER is the only enumerator of business accounts — but the exit
// must work exactly when the server can't answer (ban: every authed call
// 403s; outage: nothing answers). Wallet KEYS are not the problem: V2
// derivation is master-secret + (type, businessId, index), fully local.
// Knowing WHICH businessIds exist is. So every successful GetUserAccounts
// mirrors the roster here; bans and outages, by definition, arrive after
// normal use — the roster is already on the device when it's needed.
//
// RN-free by construction (KVStore-injected) so jest covers it.

import type { KVStore } from './reachability';

const ROSTER_KEY = 'confio_emergency_account_roster_v1';

export interface RosterAccount {
  type: 'personal' | 'business';
  index: number;
  businessId?: string;
  name: string;
  /** Employee-accessed business: its wallet derives from the OWNER's
   * master secret, so this device can never (and must never) exit it. */
  isEmployee?: boolean;
}

/** Same account-key grammar as the exit screen / cooloff keys. */
export const rosterAccountKey = (a: { type: string; index: number; businessId?: string }): string =>
  `${a.type}_${a.businessId ?? ''}_${a.index}`;

export const saveAccountRoster = async (store: KVStore, list: RosterAccount[]): Promise<void> =>
  store.set(ROSTER_KEY, JSON.stringify(list));

export const getAccountRoster = async (store: KVStore): Promise<RosterAccount[] | null> => {
  try {
    const raw = await store.get(ROSTER_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
};

/**
 * The accounts this device can actually exit: employee entries dropped
 * (not our keys), deduped by account key, personal first. ALWAYS contains
 * personal_0 — it derives from the local master secret even if the roster
 * never synced (fresh device, immediate ban).
 */
export const exitableAccounts = (roster: RosterAccount[] | null): RosterAccount[] => {
  const seen = new Set<string>();
  const owned = (roster ?? []).filter((a) => !a.isEmployee && (a.type === 'personal' || !!a.businessId));
  const out: RosterAccount[] = [];
  for (const a of owned) {
    const k = rosterAccountKey(a);
    if (!seen.has(k)) {
      seen.add(k);
      out.push(a);
    }
  }
  if (!out.some((a) => a.type === 'personal')) {
    out.unshift({ type: 'personal', index: 0, name: 'Personal' });
  }
  return out.sort((a, b) => (a.type === 'personal' ? 0 : 1) - (b.type === 'personal' ? 0 : 1));
};
