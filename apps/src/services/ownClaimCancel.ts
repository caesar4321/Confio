// Spec 6.4: while the beneficiary has a claim pending on the owner's own
// Cuenta inteligente, ANY signature of the owner cancels it. The personal
// wallet's sponsored batches therefore carry one trailing
// `account.cancelClaim()` call while such a claim is known.
//
// Source of truth: `smartAccountClaimAlert.contractAddress`, read in its own
// isolated query (an older server without the field, or any failed read,
// means "append nothing": a send must never break over this). The answer is
// cached briefly so a send does not pay a round trip each time, and the
// claim-alert host, which already polls, primes the "no claim" answer.
import type { BatchCall } from './evmWallet';

const HEX_ADDRESS = /^0x[0-9a-fA-F]{40}$/;
/** A looked-up answer (claim or not) is reused this long. */
export const OWN_CLAIM_TTL_MS = 60 * 1000;
/** The host's poll interval: its "no claim" answer holds until the next poll. */
export const OWN_CLAIM_HOST_TTL_MS = 5 * 60 * 1000;

let cache: { contract: string | null; until: number } | null = null;
let inflight: Promise<string | null> | null = null;

/** The claim-alert host's answer: no claim primes "none"; a claim forces a lookup. */
export function noteOwnPendingClaim(hasClaim: boolean, now: number = Date.now()): void {
  if (!hasClaim) {
    cache = { contract: null, until: now + OWN_CLAIM_HOST_TTL_MS };
  } else if (!cache || cache.contract === null) {
    cache = null;
  }
}

/** The claim was cancelled (or a cancel was refused): ask again next time. */
export function forgetOwnPendingClaim(): void {
  cache = null;
}

async function lookUpContract(): Promise<string | null> {
  try {
    const { gql } = await import('@apollo/client');
    const { apolloClient } = await import('../apollo/client');
    const { data } = await apolloClient.query({
      query: gql`
        query SmartAccountClaimAlertContract {
          smartAccountClaimAlert {
            contractAddress
          }
        }
      `,
      fetchPolicy: 'network-only',
    });
    const contract = data?.smartAccountClaimAlert?.contractAddress;
    return typeof contract === 'string' && HEX_ADDRESS.test(contract) ? contract : null;
  } catch {
    return null;
  }
}

/** The own account's address while a claim is pending on it; else null. */
export async function ownPendingClaimContract(
  now: number = Date.now(),
  opts: { fresh?: boolean } = {},
): Promise<string | null> {
  if (opts.fresh) {
    // The server said a claim is pending: bypass the cached answer AND any
    // lookup already in flight (it may predate the claim).
    cache = null;
    const contract = await lookUpContract();
    cache = { contract, until: Date.now() + OWN_CLAIM_TTL_MS };
    return contract;
  }
  if (cache && cache.until > now) {
    return cache.contract;
  }
  if (!inflight) {
    inflight = lookUpContract().finally(() => { inflight = null; });
  }
  const contract = await inflight;
  cache = { contract, until: Date.now() + OWN_CLAIM_TTL_MS };
  return contract;
}

async function activeContextIsPersonal(): Promise<boolean> {
  try {
    const { AuthService } = await import('./authService');
    const ctx = await AuthService.getInstance().getActiveAccountContext();
    return ctx?.type === 'personal';
  } catch {
    return false;
  }
}

/**
 * The trailing `cancelClaim()` call for a personal-wallet batch, or null:
 * not in the personal context, no claim known, or the batch already calls
 * the account (a server-built Cuenta inteligente batch).
 */
export async function ownClaimCancelCall(
  baseCalls: readonly BatchCall[],
  deps: { isPersonalContext?: () => Promise<boolean>; fresh?: boolean } = {},
): Promise<BatchCall | null> {
  if (!(await (deps.isPersonalContext ?? activeContextIsPersonal)())) {
    return null;
  }
  const contract = await ownPendingClaimContract(Date.now(), { fresh: deps.fresh });
  if (!contract) {
    return null;
  }
  const target = contract.toLowerCase();
  if (baseCalls.some((c) => c.to.toLowerCase() === target)) {
    return null;
  }
  const { selector } = await import('./evmWallet');
  return { to: contract, valueWei: 0n, data: selector('cancelClaim()') };
}

/** Test helper: forget everything. */
export function resetOwnClaimCacheForTests(): void {
  cache = null;
  inflight = null;
}
