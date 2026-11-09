// EIP-7702 sponsored execution — the client half of cusd_plus/sponsor_7702.
//
// The user's EOA never needs BNB: the client signs an EIP-712 intent over
// the exact call batch (plus, on first use, the one-time authorization
// designating ConfioBatchDelegate at its own address) and the SERVER
// broadcasts a sponsor-paid transaction to the user's EOA. The delegate
// re-verifies the user's signature on-chain, so the sponsor can only
// execute what was signed. Keys never leave the device; same address,
// same balances, normal self-signed txs keep working.
//
// Failure mode handled here: if the authorization's account nonce raced
// (some other tx from this EOA landed between signing and mining), the
// delegation silently doesn't apply and the sponsored tx mines as a no-op.
// Detection = the delegate's intent nonce didn't advance; recovery = one
// retry with freshly read nonces.

import {
  BatchCall,
  BscReceiptTimeoutError,
  BscRevertedError,
  DerivedEvmWallet,
  bscEthCall,
  bscGetCode,
  bscGetNonce,
  bscWaitForReceipt,
  deriveIntentId,
  hashBatchIntent,
  receiptExecutedBatch,
  selector,
  signIntentDigest,
  signSetCodeAuthorization,
  BscReceipt,
} from './evmWallet';
import { bytesToHex } from '@noble/hashes/utils';
import { secureRandomBytes } from '../setup/entropyGuard';

const DELEGATION_PREFIX = '0xef0100';

/** Stable, unguessable id for one user-confirmed economic action. */
export const createSponsoredRequestId = (): string =>
  `gm_${bytesToHex(secureRandomBytes(16, 'a sponsored request id'))}`;

/** Server-served 7702 config (cusdPlusConvertParams). */
export interface Sponsored7702Params {
  enabled: boolean;
  delegateAddress: string | null;
}

export const fetchSponsored7702Params = async (): Promise<Sponsored7702Params> => {
  const { gql } = await import('@apollo/client');
  const { apolloClient } = await import('../apollo/client');
  const { data } = await apolloClient.query({
    query: gql`
      query Sponsored7702Params {
        cusdPlusConvertParams {
          sponsored7702Enabled
          batchDelegateAddress
        }
      }
    `,
    fetchPolicy: 'cache-first',
  });
  const p = data?.cusdPlusConvertParams;
  return {
    enabled: Boolean(p?.sponsored7702Enabled && p?.batchDelegateAddress),
    delegateAddress: p?.batchDelegateAddress || null,
  };
};

/** send/bsc_flow.py gate: the full-dollar send rail (server redeems cUSD+
 * shares to USDT when wallet USDT doesn't cover). A SEPARATE query on
 * purpose: this field is newer than the params query above, and GraphQL
 * validation is all-or-nothing — bundling a not-yet-deployed field there
 * would kill the whole fetch (and with it every send) against an older
 * server. Missing field or any error → false, never a broken query. */
export const fetchBscSendEnabled = async (): Promise<boolean> => {
  try {
    const { gql } = await import('@apollo/client');
    const { apolloClient } = await import('../apollo/client');
    const { data } = await apolloClient.query({
      query: gql`
        query BscSendRail {
          cusdPlusConvertParams {
            bscSendEnabled
          }
        }
      `,
      fetchPolicy: 'cache-first',
    });
    return Boolean(data?.cusdPlusConvertParams?.bscSendEnabled);
  } catch {
    return false;
  }
};

/** Half of the cUSD border fee goes to whoever invited this member, paid
 * on-chain in the same transaction (CusdVault.armReferral). The server says
 * whether this member's batches carry the arm and builds it exactly; a
 * SEPARATE query so an older server (no field) only means "no arm", never a
 * failed batch. Any error → null: the fee simply stays whole. */
export const fetchFeeReferralArm = async (): Promise<BatchCall | null> => {
  try {
    const { gql } = await import('@apollo/client');
    const { apolloClient } = await import('../apollo/client');
    const { data } = await apolloClient.query({
      query: gql`
        query FeeReferralArm {
          feeReferralArm {
            to
            data
          }
        }
      `,
      fetchPolicy: 'network-only',
    });
    const arm = data?.feeReferralArm;
    if (!arm?.to || !arm?.data) return null;
    return { to: arm.to, valueWei: 0n, data: arm.data };
  } catch {
    return null;
  }
};

/** The arm decision per request id: a caller retrying the same economic
 * action after a lost answer must resend the SAME calls (the server also
 * matches replays modulo the arm, this keeps the in-session retry exact). */
const ARM_BY_REQUEST_MAX = 64;
const armByRequest = new Map<string, BatchCall | null>();
const rememberArm = (requestId: string | undefined, arm: BatchCall | null) => {
  if (!requestId) return;
  armByRequest.delete(requestId);
  armByRequest.set(requestId, arm);
  while (armByRequest.size > ARM_BY_REQUEST_MAX) {
    const oldest = armByRequest.keys().next().value;
    if (oldest === undefined) break;
    armByRequest.delete(oldest);
  }
};

/** Server codes that refuse only the referral arm (eligibility changed,
 * first-use delegation, not fee-bearing), and a pre-flight revert of an
 * armed batch: resend the same batch without it. A commission must never
 * block the member's money. */
const isReferralArmRejection = (error?: string | null): boolean =>
  !!error && (error.startsWith('referral_') || error === 'simulation_reverted');

/** Selectors whose calls charge the cUSD border fee (mirror of the server's
 *  fee_referral._fee_bearing_selectors). */
let feeBearingCache: Set<string> | null = null;
const feeBearingSelectors = (): Set<string> => {
  if (!feeBearingCache) {
    feeBearingCache = new Set([
      'mintWithFee(uint256,uint256,address)',
      'redeemWithFee(uint256,uint256,address)',
      'redeemToUsdt(uint256,uint256,address)',
      'subscribeAndMint(uint256,uint256,address)',
      'buyWithSavings((uint256,uint256,bytes32,address,uint256,uint256,uint256,uint8,bytes32),bytes,uint256,uint256,uint256,uint256)',
      'sellToSavings((uint256,uint256,bytes32,address,uint256,uint256,uint256,uint8,bytes32),bytes,uint256,uint256,uint256)',
      'buy(uint8,uint256,uint256,bytes,address,uint256,uint256)',
      'sell(uint8,address,uint256,bytes,uint256,uint256,uint256)',
    ].map((sig) => selector(sig).slice(2)));
  }
  return feeBearingCache;
};

export const delegateNonce = async (eoa: string): Promise<bigint> => {
  // nonces() on the EOA itself; a codeless (not yet delegated) EOA returns
  // empty data — that IS nonce 0.
  const res = await bscEthCall(eoa, selector('nonces()'));
  return res && res !== '0x' ? BigInt(res) : 0n;
};

export const isDelegatedTo = async (eoa: string, delegate: string): Promise<boolean> => {
  const code = ((await bscGetCode(eoa)) || '0x').toLowerCase();
  return code === DELEGATION_PREFIX + delegate.toLowerCase().slice(2);
};

/** What a sponsored batch settled to. `receipt` is present only when THIS
 *  client observed it; when the sponsor reported the execution it saw, the
 *  hash is all we legitimately have — so the type says so rather than
 *  handing back a fabricated receipt. */
export interface SponsoredBatchResultReceipt {
  txHash: string;
  receipt?: BscReceipt;
}

/**
 * Execute `calls` as the user's EOA via a sponsor-paid transaction.
 * Confirms execution actually happened — the sponsor's own observation when
 * it has one, otherwise our own receipt poll — and retries once with fresh
 * nonces on the races the server reports (authorization_required /
 * stale_auth_nonce) or a silent no-op. Throws on policy rejection or
 * exhaustion.
 */
/** Refused before signing: the caller's target expires too soon. Nothing was
 *  broadcast, so callers treat it as a definite "not sent". */
export class SigningWindowClosedError extends Error {
  constructor() {
    super('The funding target expires before this could be signed');
    this.name = 'SigningWindowClosedError';
  }
}

export const executeSponsoredBatch = async (params: {
  wallet: DerivedEvmWallet;
  calls: BatchCall[];
  delegateAddress: string;
  requestId?: string;
  /** Unix seconds the signed batch must not outlive (e.g. a bridge quote's
   *  deadline). The intent deadline is capped to it. */
  notAfter?: number;
}): Promise<SponsoredBatchResultReceipt> => {
  const { sponsorBscBatch } = await import('./bscServerRpc');
  const { wallet, calls: baseCalls, delegateAddress, requestId, notAfter } = params;
  const from = wallet.address;
  // Fee referral arm goes FIRST (the server accepts it nowhere else). The
  // server allows one extra call for it (4 own calls + arm); anything larger
  // or already carrying an arm is left alone.
  const armSelector = selector('armReferral(address,uint256)').slice(2);
  const callSelectors = baseCalls.map((c) => c.data.replace(/^0x/, '').slice(0, 8));
  const alreadyArmed = callSelectors.includes(armSelector);
  // Only batches that pay the cUSD border fee earn commission (server rule:
  // fee_referral._fee_bearing_selectors). Everything else is sent as-is.
  const feeBearing = callSelectors.some((s) => feeBearingSelectors().has(s));
  let arm: BatchCall | null;
  if (alreadyArmed || !feeBearing || baseCalls.length > 4) arm = null;
  else if (requestId && armByRequest.has(requestId)) arm = armByRequest.get(requestId) ?? null;
  else arm = await fetchFeeReferralArm();
  rememberArm(requestId, arm);

  let lastError = 'unknown';
  for (let attempt = 0; attempt < 2; attempt++) {
    const calls = arm ? [arm, ...baseCalls] : baseCalls;
    // A mined no-op legitimately needs a fresh delegate nonce and therefore
    // a fresh idempotency slot. Transport retries of either attempt still
    // reproduce the same suffix and resolve to its original transaction.
    const attemptRequestId = requestId ? `${requestId}_a${attempt}` : undefined;
    // Independent reads, so pay for ONE round trip instead of two — each is
    // a phone→server→BSC hop and both are always needed. The account nonce
    // stays conditional: it's read only on a first-ever (undelegated) call.
    const [execNonce, delegated] = await Promise.all([
      delegateNonce(from),
      isDelegatedTo(from, delegateAddress),
    ]);
    const now = Math.floor(Date.now() / 1000);
    if (notAfter !== undefined && notAfter - now < 30) throw new SigningWindowClosedError();
    const deadline = BigInt(notAfter !== undefined ? Math.min(now + 600, notAfter) : now + 600);

    // Savings rail: no prepare step, so derive intentId the way the server
    // does (from the selectors). Domain flows pass the server's intentId.
    const intentId = deriveIntentId(calls, attemptRequestId);
    const digest = hashBatchIntent(calls, execNonce, deadline, intentId, from);
    const intentSignature = signIntentDigest(digest, wallet.privKeyHex);

    // First use (or re-delegation): the authorization tuple rides along.
    // The server re-checks delegation state authoritatively either way.
    let authorization;
    if (!delegated) {
      const accountNonce = await bscGetNonce(from);
      authorization = signSetCodeAuthorization(delegateAddress, accountNonce, wallet.privKeyHex);
    }

    const res = await sponsorBscBatch({
      calls: calls.map((c) => ({ to: c.to, valueWei: c.valueWei.toString(), data: c.data })),
      nonce: execNonce.toString(),
      deadline: deadline.toString(),
      intentSignature,
      authorization,
      requestId: attemptRequestId,
    });

    if (!res.success) {
      lastError = res.error || 'sponsor rejected';
      if (arm && isReferralArmRejection(res.error)) {
        // Nothing was broadcast; the same attempt slot is free. Drop the arm
        // and resend: a commission must never block the member's money.
        arm = null;
        rememberArm(requestId, null);
        attempt--;
        continue;
      }
      // Nonce races are retryable with fresh reads; policy errors are not.
      if (res.authorizationRequired || res.error === 'stale_auth_nonce') continue;
      throw new Error(`sponsored batch rejected: ${lastError}`);
    }

    const txHash = res.txHash as string;
    // The sponsor watched the chain before answering; null (it didn't see
    // the tx inside its budget) falls through to our own poll. A server
    // without `execution` fails this whole mutation at GraphQL validation
    // rather than omitting the field, so deploy the server first.
    if (res.execution === 'executed') return { txHash };
    if (res.execution === 'reverted') throw new BscRevertedError(txHash);
    if (res.execution !== 'noop') {
      const receipt = await bscWaitForReceipt(txHash);
      // BatchExecuted(nonce) from this EOA is the proof the delegation
      // applied — the same question the second nonces() read used to ask,
      // answered by the receipt we already hold.
      const verdict = receiptExecutedBatch(receipt, from, execNonce);
      if (verdict === 'executed') return { txHash, receipt };
      // No logs field at all: we were never shown whether this executed.
      // Outcome-unknown, NOT failure — cusdPlusVault's callers check
      // isOutcomeUnknown precisely so they don't broadcast a second,
      // self-signed transfer for money that may already have moved.
      if (verdict === 'unknown') throw new BscReceiptTimeoutError(txHash);
    }
    // Mined without our BatchExecuted: the delegation never applied
    // (silent 7702 no-op). Fresh reads, one more shot.
    lastError = 'delegation_not_applied';
  }
  throw new Error(`sponsored batch failed: ${lastError}`);
};
