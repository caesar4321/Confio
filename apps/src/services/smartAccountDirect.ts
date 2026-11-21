// App glue for the beneficiary's direct claim path (spec 6.7): the device's
// own wallet, the keychain record of the account, the phone's biometric, and
// the pure on-chain sender (emergencyExit/directClaim.ts). Nothing here asks
// Confío's server anything: it must work exactly when the server is gone.
//
// The signer is always the personal wallet (personal_0): a beneficiary is
// named by that wallet's address, and the inherited withdraw goes back to it.
import {
  formatBnbCeil,
  nextDirectStep,
  quoteDirectCall,
  quoteDirectWithdrawAll,
  readDirectAccountState,
  readDirectHoldings,
  sendDirectCall,
  type DirectHolding,
  type DirectRevertName,
  type DirectSendOutcome,
  type DirectStep,
} from './emergencyExit/directClaim';
import { findDirectClaimEntry, loadDirectClaimEntries, type DirectClaimEntry } from './emergencyExit/directClaimStore';

export type { DirectHolding, DirectRevertName, DirectStep };

export async function loadDirectEntry(key: {
  designationId?: string | null;
  account?: string | null;
}): Promise<DirectClaimEntry | null> {
  const { emergencyStore } = await import('./emergencyExit/store');
  return findDirectClaimEntry(await loadDirectClaimEntries(emergencyStore), key);
}

/**
 * What this phone remembers of the accounts it was named beneficiary of, for
 * when Confío's server cannot be reached. Inherited ones (already received)
 * are listed separately by the inherited screens.
 */
export async function loadOfflineDesignations(): Promise<DirectClaimEntry[]> {
  const { emergencyStore } = await import('./emergencyExit/store');
  return (await loadDirectClaimEntries(emergencyStore))
    .filter((e) => !!e.designationId && !e.inheritedAccountId);
}

/** The device record of one inherited account, for the serverless withdraw. */
export async function loadInheritedDirectEntry(inheritedAccountId?: string | null): Promise<DirectClaimEntry | null> {
  const { emergencyStore } = await import('./emergencyExit/store');
  const all = await loadDirectClaimEntries(emergencyStore);
  return (inheritedAccountId ? all.find((e) => e.inheritedAccountId === inheritedAccountId) : null)
    ?? (all.filter((e) => !!e.inheritedAccountId).length === 1 ? all.find((e) => !!e.inheritedAccountId)! : null);
}

/** The personal wallet's address, from the device only. */
export async function ownWalletAddress(): Promise<string | null> {
  const { getEvmAddressForDisplay, getActiveEvmWallet } = await import('./secureDeterministicWallet');
  const cached = await getEvmAddressForDisplay('personal_0').catch(() => null);
  if (cached) {
    return cached;
  }
  try {
    return (await getActiveEvmWallet({ type: 'personal', index: 0 })).address;
  } catch {
    return null;
  }
}

export type DirectGas =
  | { kind: 'enough' }
  | { kind: 'short'; needBnb: string }
  | { kind: 'refused'; error: DirectRevertName | null }
  | { kind: 'none' };

export interface DirectSituation {
  me: string;
  account: string;
  step: DirectStep;
  /** Withdraw only: what the account holds, by product name. */
  holdings: DirectHolding[];
  gas: DirectGas;
}

const callFor = (step: DirectStep) =>
  (step.kind === 'initiate' ? { kind: 'initiateClaim' as const }
    : step.kind === 'execute' ? { kind: 'executeClaim' as const } : null);

/** Read the account from the chain and price the next step (BNB check). */
export async function readDirectSituation(entry: DirectClaimEntry, me: string): Promise<DirectSituation> {
  const state = await readDirectAccountState(entry.account);
  const step = nextDirectStep(state, me, Math.floor(Date.now() / 1000));
  let holdings: DirectHolding[] = [];
  let gas: DirectGas = { kind: 'none' };
  const call = callFor(step);
  if (call) {
    const q = await quoteDirectCall({ from: me, account: entry.account, call });
    gas = !q.ok ? { kind: 'refused', error: q.error }
      : q.quote.balanceWei >= q.quote.needWei ? { kind: 'enough' }
        : { kind: 'short', needBnb: formatBnbCeil(q.quote.needWei - q.quote.balanceWei) };
  } else if (step.kind === 'withdraw') {
    holdings = await readDirectHoldings(entry.account, entry.tokens ?? []);
    if (holdings.length > 0) {
      const q = await quoteDirectWithdrawAll({ from: me, account: entry.account, holdings });
      gas = !q.ok ? { kind: 'refused', error: q.error }
        : q.balanceWei >= q.needWei ? { kind: 'enough' }
          : { kind: 'short', needBnb: formatBnbCeil(q.needWei - q.balanceWei) };
    }
  }
  return { me, account: entry.account, step, holdings, gas };
}

export type DirectRunOutcome =
  | { status: 'cancelled' }
  | { status: 'executed'; done: number; total: number }
  | { status: 'unknown'; done: number; total: number }
  | { status: 'failed'; done: number; total: number; error: DirectRevertName | null; needBnb?: string };

/**
 * Sign on this device and send the next step. The phone's biometric guards
 * it (as in Salida de emergencia). A withdraw sends one transaction per asset,
 * in order, and stops at the first one that does not clearly go through.
 */
export async function runDirectStep(situation: DirectSituation): Promise<DirectRunOutcome> {
  const { biometricAuthService } = await import('./biometricAuthService');
  if (!(await biometricAuthService.authenticateEmergencyExit('Confirmar operación sin Confío'))) {
    return { status: 'cancelled' };
  }
  const { getActiveEvmWallet } = await import('./secureDeterministicWallet');
  const wallet = await getActiveEvmWallet({ type: 'personal', index: 0 });
  if (wallet.address.toLowerCase() !== situation.me.toLowerCase()) {
    return { status: 'failed', done: 0, total: 1, error: null };
  }
  const single = callFor(situation.step);
  const calls = single ? [single]
    : situation.step.kind === 'withdraw'
      ? situation.holdings.map((h) => ({ kind: 'withdraw' as const, token: h.address, amount: h.balance, to: wallet.address }))
      : [];
  const total = calls.length;
  let done = 0;
  for (const call of calls) {
    let out: DirectSendOutcome;
    let signedHash: string | null = null;
    try {
      out = await sendDirectCall({
        wallet, account: situation.account, call,
        onSigned: (h) => { signedHash = h; },
      });
    } catch {
      // Once signed, a throw can never be read as "nothing happened": the
      // transaction may be on the network. Before signing, nothing moved.
      return signedHash
        ? { status: 'unknown', done, total }
        : { status: 'failed', done, total, error: null };
    }
    if (out.status === 'executed') {
      done += 1;
      continue;
    }
    if (out.status === 'unknown') {
      return { status: 'unknown', done, total };
    }
    if (out.status === 'needs_bnb') {
      return { status: 'failed', done, total, error: null, needBnb: formatBnbCeil(out.needWei - out.balanceWei) };
    }
    return { status: 'failed', done, total, error: out.status === 'refused' ? out.error : null };
  }
  return { status: 'executed', done, total };
}
