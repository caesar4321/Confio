import { gql } from '@apollo/client';
import { Buffer } from 'buffer';

import { apolloClient } from '../apollo/client';
import algorandService from './algorandService';
import { cusdAppOptInService } from './cusdAppOptInService';

const BUILD_BURN_AND_SEND = gql`
  mutation BuildBurnAndSend(
    $amount: String!
    $recipientAddress: String!
    $note: String
    $rampProvider: String
    $providerOrderId: String
  ) {
    buildBurnAndSend(
      amount: $amount
      recipientAddress: $recipientAddress
      note: $note
      rampProvider: $rampProvider
      providerOrderId: $providerOrderId
    ) {
      success
      error
      transactions
    }
  }
`;

const SUBMIT_AUTO_SWAP_TRANSACTIONS = gql`
  mutation SubmitAutoSwapTransactions(
    $internalId: String!
    $signedTransactions: [String]!
    $sponsorTransactions: [String]!
    $withdrawalId: String
  ) {
    submitAutoSwapTransactions(
      internalId: $internalId
      signedTransactions: $signedTransactions
      sponsorTransactions: $sponsorTransactions
      withdrawalId: $withdrawalId
    ) {
      success
      error
      txid
    }
  }
`;

// 'unknown' is NOT a failure: the payment was handed to the network and the
// verdict was lost. Callers must never invite a retry on it.
type FundingStatus = 'submitted' | 'skipped' | 'failed' | 'unknown';

type FundingResult = {
  status: FundingStatus;
  reason?: string;
  transactionId?: string;
  destinationAddress?: string;
};

const ALGORAND_ADDRESS_REGEX = /^[A-Z2-7]{58}$/;
const APP_OPT_IN_RETRY_DELAY_MS = 3000;
const BUILD_BURN_AND_SEND_MAX_ATTEMPTS = 5;

const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

const parsePaymentDetails = (value: unknown): Record<string, unknown> | null => {
  if (!value) return null;
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      return parsed && typeof parsed === 'object' ? parsed : null;
    } catch {
      return null;
    }
  }
  return typeof value === 'object' ? (value as Record<string, unknown>) : null;
};

/** Same rule as the BSC rail: only the address the SERVER resolved from a
 *  documented field and validated. A blind scan of the provider blob picks
 *  whatever address-shaped string happens to come first (audit [P1] #5). */
const extractAlgorandAddress = (paymentDetails: unknown): string | null => {
  const parsed = parsePaymentDetails(paymentDetails);
  if (!parsed) return null;
  const vouched = String(parsed.confioDepositAddress || '').trim();
  if (!vouched || !ALGORAND_ADDRESS_REGEX.test(vouched)) return null;
  if (String(parsed.confioDepositNetwork || '').toUpperCase() !== 'ALGO') return null;
  return vouched;
};

export const tryFundKoyweOffRampInBackground = async ({
  amount,
  paymentDetails,
  providerOrderId,
  activeAccount,
}: {
  amount: string | number;
  paymentDetails: unknown;
  providerOrderId: string;
  activeAccount?: any;
}): Promise<FundingResult> => {
  const destinationAddress = extractAlgorandAddress(paymentDetails);
  if (!destinationAddress) {
    return { status: 'skipped', reason: 'missing_algorand_destination' };
  }

  const amountBaseUnits = Math.floor(parseFloat(String(amount)) * 1_000_000).toString();
  if (!Number.isFinite(Number(amountBaseUnits)) || Number(amountBaseUnits) <= 0) {
    return { status: 'failed', reason: 'invalid_amount' };
  }

  try {
    let buildResult: any = null;

    let attemptedAppOptIn = false;
    for (let attempt = 0; attempt < BUILD_BURN_AND_SEND_MAX_ATTEMPTS; attempt += 1) {
      const res = await apolloClient.mutate({
        mutation: BUILD_BURN_AND_SEND,
        variables: {
          amount: amountBaseUnits,
          recipientAddress: destinationAddress,
          rampProvider: 'koywe',
          providerOrderId,
        },
        fetchPolicy: 'no-cache',
      });

      buildResult = res.data?.buildBurnAndSend;
      if (buildResult?.success) {
        break;
      }

      if (buildResult?.error === 'requires_app_optin') {
        if (!attemptedAppOptIn) {
          const optInResult = await cusdAppOptInService.handleAppOptIn(activeAccount);
          if (!optInResult.success) {
            return { status: 'failed', reason: optInResult.error || 'requires_app_optin' };
          }
          attemptedAppOptIn = true;
        }
        await delay(APP_OPT_IN_RETRY_DELAY_MS);
        continue;
      }

      return {
        status: 'failed',
        reason: buildResult?.error || 'build_burn_and_send_failed',
        destinationAddress,
      };
    }

    if (!buildResult?.success || !buildResult?.transactions) {
      return { status: 'failed', reason: 'missing_build_payload', destinationAddress };
    }

    const payload = typeof buildResult.transactions === 'string'
      ? JSON.parse(buildResult.transactions)
      : buildResult.transactions;

    const { internal_id, withdrawal_id, transactions, sponsor_transactions } = payload || {};
    if (!internal_id || !Array.isArray(transactions) || transactions.length === 0) {
      return { status: 'failed', reason: 'invalid_build_payload', destinationAddress };
    }

    const signedUserTransactions: string[] = [];
    for (const txnB64 of transactions) {
      const txnBytes = Uint8Array.from(Buffer.from(String(txnB64), 'base64'));
      const signedBytes = await algorandService.signTransactionBytes(txnBytes);
      signedUserTransactions.push(Buffer.from(signedBytes).toString('base64'));
    }

    const submitRes = await apolloClient.mutate({
      mutation: SUBMIT_AUTO_SWAP_TRANSACTIONS,
      variables: {
        internalId: String(internal_id),
        signedTransactions: signedUserTransactions,
        sponsorTransactions: (sponsor_transactions || []).map((entry: any) =>
          typeof entry === 'string' ? entry : JSON.stringify(entry)
        ),
        withdrawalId: withdrawal_id ? String(withdrawal_id) : undefined,
      },
      fetchPolicy: 'no-cache',
    });

    const submitResult = submitRes.data?.submitAutoSwapTransactions;
    if (!submitResult?.success) {
      return {
        status: 'failed',
        reason: submitResult?.error || 'submit_auto_swap_failed',
        destinationAddress,
      };
    }

    return {
      status: 'submitted',
      transactionId: submitResult.txid || undefined,
      destinationAddress,
    };
  } catch (error: any) {
    return {
      status: 'failed',
      reason: error?.message || 'unexpected_funding_error',
      destinationAddress,
    };
  }
};

// ── Savings rail (cUSD+ / USDT-BSC) ─────────────────────────────────────────
// Koywe's savings off-ramp is the SAME provider and order flow; only the
// funding chain differs. Koywe returns a BSC deposit address instead of an
// Algorand one, and we pay it with USDT-BSC.
//
// Two legs can hold the money: minted cUSD+ shares and raw USDT that landed
// but hasn't minted. Both are spent by ONE sponsored batch — the redeem (to
// the user's own address) and the payment ride the same transaction, so
// there is no window where the shares are burned but the provider is
// unfunded. See fundUsdtDestination.
const EVM_ADDRESS_REGEX = /^0x[0-9a-fA-F]{40}$/;

// Never a valid destination — the same list the server enforces.
const FORBIDDEN_EVM_DESTINATIONS = new Set([
  '0x0000000000000000000000000000000000000000',
  '0x55d398326f99059ff775485246999027b3197955', // USDT-BSC itself
]);

/**
 * The deposit address, taken ONLY from the key the server validated.
 *
 * This used to walk every string in the provider blob and fund the first
 * `0x…`-shaped match. Field order in JSON is not a contract — a response
 * listing a token contract before the deposit address would have sent the
 * withdrawal to that contract, unrecoverably (audit 2026-08-03 [P1] #5).
 * No fallback scan: if the server didn't vouch for an address, we refuse to
 * move money and the order is funded manually instead.
 */
const extractEvmAddress = (paymentDetails: unknown): string | null => {
  const parsed = parsePaymentDetails(paymentDetails);
  if (!parsed) return null;
  const vouched = String(parsed.confioDepositAddress || '').trim();
  if (!vouched || !EVM_ADDRESS_REGEX.test(vouched)) return null;
  if (FORBIDDEN_EVM_DESTINATIONS.has(vouched.toLowerCase())) return null;
  if (String(parsed.confioDepositNetwork || '').toUpperCase() !== 'BSC') return null;
  return vouched;
};

const extractVouchedDepositAmountWei = (paymentDetails: unknown): bigint | null => {
  const parsed = parsePaymentDetails(paymentDetails);
  const raw = String(parsed?.confioDepositAmountWei || '').trim();
  if (!/^[1-9][0-9]*$/.test(raw)) return null;
  try {
    return BigInt(raw);
  } catch {
    return null;
  }
};

const extractVouchedGrossDebitWei = (paymentDetails: unknown): bigint | null => {
  const parsed = parsePaymentDetails(paymentDetails);
  const raw = String(parsed?.confioGrossDebitAmountWei || '').trim();
  if (!/^[1-9][0-9]*$/.test(raw)) return null;
  try {
    return BigInt(raw);
  } catch {
    return null;
  }
};

export const tryFundKoyweSavingsOffRampInBackground = async ({
  amountMicros,
  paymentDetails,
  vaultAddress,
  cusdAddress,
}: {
  /** The order's canonical amount in micro-units — the SAME BigInt the order
   *  was created with, never a re-parsed float (see utils/tokenAmount). */
  amountMicros: bigint;
  paymentDetails: unknown;
  /** cUSD+ vault proxy; omit when the user holds only raw USDT. */
  vaultAddress?: string | null;
  /** Universal cUSD proxy for non-yield balances. */
  cusdAddress?: string | null;
}): Promise<FundingResult> => {
  const destinationAddress = extractEvmAddress(paymentDetails);
  if (!destinationAddress) {
    return { status: 'skipped', reason: 'missing_bsc_destination' };
  }

  if (!amountMicros || amountMicros <= 0n) {
    return { status: 'failed', reason: 'invalid_amount', destinationAddress };
  }
  const { microsToWei } = await import('../utils/tokenAmount');
  // Fee-capable servers vouch for the contract-previewed NET provider
  // amount. Legacy servers omit it, preserving the old exact-input behavior.
  const amountWei = extractVouchedDepositAmountWei(paymentDetails) ?? microsToWei(amountMicros);
  const grossDebitWei = extractVouchedGrossDebitWei(paymentDetails);

  // NOTE: there is NO durable one-payment-per-order guard here yet. A first
  // attempt at one stored its state in RampTransaction.metadata, which the
  // Koywe status sync rebuilds on every poll — a routine poll erased the
  // claim, so the guard looked durable and was not. It was reverted rather
  // than shipped, because a guard that silently stops guarding is worse than
  // no guard: it invites trusting it. The rebuild belongs on its own table.
  //
  // Until then the protections are: no sponsored->legacy fallback, an
  // outcome-unknown verdict that is never reported as a plain failure, and
  // the caller not offering a retry on it.
  try {
    const { installBscServerTransport } = await import('./bscServerRpc');
    installBscServerTransport();
    const { fundUsdtDestination } = await import('./cusdPlusVault');

    // ONE sponsored batch: redeem the shortfall (if any) and pay Koywe
    // together. This avoids leaving shares redeemed while the provider order
    // remains unfunded if a second transaction fails (audit 2026-08-03 [P1]).
    const res = await fundUsdtDestination({
      to: destinationAddress,
      amountWei,
      grossDebitWei,
      vaultAddress,
      cusdAddress,
    });
    return { status: 'submitted', transactionId: res.txHash, destinationAddress };
  } catch (error: any) {
    const { isOutcomeUnknown } = await import('./evmWallet');
    if (isOutcomeUnknown(error)) {
      // Broadcast, verdict lost. NOT 'failed' — the caller must not present
      // this as "nothing happened" and invite a second payment to an order
      // that may already be funded (audit [P1] #2).
      return { status: 'unknown', reason: 'funding_outcome_unknown', destinationAddress };
    }
    if (error?.name === 'InsufficientWithdrawableError') {
      return { status: 'failed', reason: 'insufficient_usdt', destinationAddress };
    }
    return {
      status: 'failed',
      reason: error?.message || 'unexpected_funding_error',
      destinationAddress,
    };
  }
};
