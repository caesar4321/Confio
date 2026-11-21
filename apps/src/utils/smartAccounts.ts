// Cuenta inteligente entries for the account switcher.
//
// The roster of keyed accounts (personal, business) comes from `userAccounts`.
// Smart entries are built here from the product's own isolated queries, so
// they carry what the switcher needs (the contract address, whose account an
// inherited one was) and an older server simply yields none.
//
// Ids: smart_0 is the viewer's own account; smart_1.. are inherited accounts
// in the order they were received (spec 7.2).
import type { AccountContext, StoredAccount } from './accountManager';

export const SMART_ACCOUNT_NAME = 'Cuenta inteligente';
export const SMART_ACCOUNT_SWITCHER_LABEL = 'Tu cuenta';
export const INHERITED_ACCOUNT_SWITCHER_LABEL = 'Cuenta inteligente · heredada';

type OwnEntry = { status: string; contractAddress: string | null } | null;
type InheritedEntry = {
  inheritedAccountId: string;
  contractAddress: string;
  fromName: string;
  inheritedAt: string;
  /** The server's JWT account_index (1 and up), when it reports one. */
  accountIndex?: number;
};

const isOpen = (status: string | null | undefined) =>
  status === 'active' || status === 'cancel_pending' || status === 'expired';

export function ownSmartStoredAccount(contractAddress?: string | null): StoredAccount {
  return {
    id: 'smart_0',
    type: 'smart',
    index: 0,
    name: SMART_ACCOUNT_NAME,
    avatar: 'C',
    algorandAddress: '',
    createdAt: '',
    isActive: true,
    smart: { inherited: false, contractAddress: contractAddress || undefined },
  };
}

function inheritedStoredAccount(entry: InheritedEntry, index: number): StoredAccount {
  const from = (entry.fromName || '').trim();
  return {
    id: `smart_${index}`,
    type: 'smart',
    index,
    name: from ? `Cuenta de ${from}` : SMART_ACCOUNT_NAME,
    avatar: (from || 'C').charAt(0).toUpperCase(),
    algorandAddress: '',
    createdAt: entry.inheritedAt,
    isActive: true,
    smart: {
      inherited: true,
      contractAddress: entry.contractAddress,
      inheritedAccountId: entry.inheritedAccountId,
      fromName: from || undefined,
    },
  };
}

/** Inherited accounts in the order received: that order IS their index. */
export function orderInherited<T extends { inheritedAt: string; inheritedAccountId: string }>(list: T[]): T[] {
  return [...list].sort((a, b) => {
    const ta = Date.parse(a.inheritedAt);
    const tb = Date.parse(b.inheritedAt);
    if (Number.isFinite(ta) && Number.isFinite(tb) && ta !== tb) {
      return ta - tb;
    }
    return a.inheritedAccountId < b.inheritedAccountId ? -1 : a.inheritedAccountId > b.inheritedAccountId ? 1 : 0;
  });
}

const isIndex = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 1;

/**
 * Each inherited account with the smart_N index it is switched to. The
 * server's `accountIndex` is the authority when EVERY entry carries a valid,
 * distinct one (it is what switchAccountToken accepts). Otherwise (an older
 * server, or a partial answer) the old rule applies: order received, 1-based.
 * Mixing the two could give two accounts the same index, so it is never done.
 */
export function indexInherited<T extends { inheritedAt: string; inheritedAccountId: string; accountIndex?: number }>(
  list: T[],
): Array<{ entry: T; index: number }> {
  const indexes = list.map((e) => e.accountIndex);
  const serverIndexed = list.length > 0
    && indexes.every(isIndex)
    && new Set(indexes).size === list.length;
  if (serverIndexed) {
    return [...list]
      .sort((a, b) => (a.accountIndex as number) - (b.accountIndex as number))
      .map((entry) => ({ entry, index: entry.accountIndex as number }));
  }
  return orderInherited(list).map((entry, i) => ({ entry, index: i + 1 }));
}

export function buildSmartStoredAccounts(own: OwnEntry, inherited: InheritedEntry[]): StoredAccount[] {
  const out: StoredAccount[] = [];
  if (own && isOpen(own.status)) {
    out.push(ownSmartStoredAccount(own.contractAddress));
  }
  indexInherited(inherited).forEach(({ entry, index }) => out.push(inheritedStoredAccount(entry, index)));
  return out;
}

/**
 * The switcher's smart entries after one refresh. Own and inherited come from
 * two isolated reads; a read that failed keeps what was known for its half
 * ("could not ask" is not "has none"), a read that answered replaces it.
 */
export function mergeSmartAccounts(
  previous: StoredAccount[],
  own: { ok: true; data: OwnEntry } | { ok: false },
  inherited: { ok: true; data: InheritedEntry[] } | { ok: false },
): StoredAccount[] {
  const built = buildSmartStoredAccounts(own.ok ? own.data : null, inherited.ok ? inherited.data : []);
  return [
    ...(own.ok ? built.filter((a) => !a.smart?.inherited) : previous.filter((a) => !a.smart?.inherited)),
    ...(inherited.ok ? built.filter((a) => a.smart?.inherited) : previous.filter((a) => a.smart?.inherited)),
  ];
}

/**
 * Smart reads run only from a personal or smart context. From a business one
 * (owner or employee) they are skipped and the known entries kept as they
 * are: a business token's answer is not the person's smart roster.
 */
export const shouldReadSmartAccounts = (context: Pick<AccountContext, 'type'> | null | undefined): boolean =>
  context?.type !== 'business';

/** What the header and the tabs show for a smart context before (or without)
 *  the server's answer: enough to render the right home, never a guess at money. */
export function smartPlaceholderAccount(context: AccountContext): StoredAccount {
  if (context.index === 0) {
    return ownSmartStoredAccount();
  }
  return {
    id: `smart_${context.index}`,
    type: 'smart',
    index: context.index,
    name: SMART_ACCOUNT_NAME,
    avatar: 'C',
    algorandAddress: '',
    createdAt: '',
    isActive: true,
    smart: { inherited: true },
  };
}

/** The line under an account's name in the switcher. */
export function smartSwitcherLabel(account: Pick<StoredAccount, 'smart'>): string {
  return account.smart?.inherited ? INHERITED_ACCOUNT_SWITCHER_LABEL : SMART_ACCOUNT_SWITCHER_LABEL;
}

// ------------------------------------------------ last known smart entries
//
// The switcher's last answer, kept in memory for code outside React (a push
// tap decides which context to open before any screen mounts). Ids only:
// never authority, the server re-checks every switch.
let knownSmart: StoredAccount[] = [];

export function rememberKnownSmartAccounts(list: StoredAccount[]): void {
  knownSmart = list.filter((a) => a.type === 'smart');
}

/** smart_N for an inherited account id, when this session has seen it. */
export function knownInheritedSmartAccountId(inheritedAccountId: string | null | undefined): string | null {
  if (!inheritedAccountId) {
    return null;
  }
  const hit = knownSmart.find((a) => a.smart?.inherited && a.smart.inheritedAccountId === inheritedAccountId);
  return hit ? hit.id : null;
}
