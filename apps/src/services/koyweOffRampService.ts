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

type FundingStatus = 'submitted' | 'skipped' | 'failed';

type FundingResult = {
  status: FundingStatus;
  reason?: string;
  transactionId?: string;
  destinationAddress?: string;
};

const ALGORAND_ADDRESS_REGEX = /\b[A-Z2-7]{58}\b/;
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

const collectStringValues = (value: unknown, sink: string[]) => {
  if (!value) return;
  if (typeof value === 'string') {
    sink.push(value);
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((entry) => collectStringValues(entry, sink));
    return;
  }
  if (typeof value === 'object') {
    Object.values(value as Record<string, unknown>).forEach((entry) => collectStringValues(entry, sink));
  }
};

const extractAlgorandAddress = (paymentDetails: unknown): string | null => {
  const parsed = parsePaymentDetails(paymentDetails);
  if (!parsed) return null;

  const candidates: string[] = [];
  collectStringValues(parsed, candidates);

  for (const candidate of candidates) {
    const match = candidate.match(ALGORAND_ADDRESS_REGEX);
    if (match) {
      return match[0];
    }
  }
  return null;
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
// but hasn't minted. When shares are needed, they are redeemed to the USER'S
// OWN address first and only then transferred out in a single payment. That
// ordering is deliberate: a failure between the two steps leaves everything in
// the user's wallet, never a partial deposit sitting in Koywe's order.
const EVM_ADDRESS_REGEX = /\b0x[0-9a-fA-F]{40}\b/;

const extractEvmAddress = (paymentDetails: unknown): string | null => {
  const parsed = parsePaymentDetails(paymentDetails);
  if (!parsed) return null;
  const candidates: string[] = [];
  collectStringValues(parsed, candidates);
  for (const candidate of candidates) {
    const match = candidate.match(EVM_ADDRESS_REGEX);
    if (match) return match[0];
  }
  return null;
};

export const tryFundKoyweSavingsOffRampInBackground = async ({
  amount,
  paymentDetails,
  vaultAddress,
}: {
  amount: string | number;
  paymentDetails: unknown;
  /** cUSD+ vault proxy; omit when the user holds only raw USDT. */
  vaultAddress?: string | null;
}): Promise<FundingResult> => {
  const destinationAddress = extractEvmAddress(paymentDetails);
  if (!destinationAddress) {
    return { status: 'skipped', reason: 'missing_bsc_destination' };
  }

  const parsedAmount = parseFloat(String(amount));
  if (!Number.isFinite(parsedAmount) || parsedAmount <= 0) {
    return { status: 'failed', reason: 'invalid_amount', destinationAddress };
  }

  try {
    const { installBscServerTransport } = await import('./bscServerRpc');
    installBscServerTransport();
    const {
      transferUsdt, redeemSavingsToUsdt, getVaultShares, USDT_BSC,
    } = await import('./cusdPlusVault');
    const { getActiveEvmWallet } = await import('./secureDeterministicWallet');
    const { selector, encodeAddress, bscEthCall } = await import('./evmWallet');

    const wallet = await getActiveEvmWallet();
    const readUsdtWei = async (): Promise<bigint> => {
      const hex = await bscEthCall(
        USDT_BSC, selector('balanceOf(address)') + encodeAddress(wallet.address),
      );
      return BigInt(hex === '0x' ? '0x0' : hex);
    };

    // SIX-decimal precision scaled to 18dp, because that is exactly the
    // grain the order was created at (SellScreen's formatExactTokenAmount
    // does toFixed(6)). Rounding to cents here would fund an order for
    // 2.995 with 3.00 — paying the provider a different number than the one
    // it quoted, in whichever direction the rounding fell.
    const amountWei = BigInt(Math.round(parsedAmount * 1e6)) * 10n ** 12n;
    let usdtWei = await readUsdtWei();

    if (usdtWei < amountWei) {
      // Short on raw USDT: redeem the gap out of the vault, to OURSELVES.
      if (!vaultAddress) {
        return { status: 'failed', reason: 'insufficient_usdt', destinationAddress };
      }
      const shares = await getVaultShares(vaultAddress, wallet.address);
      if (shares <= 0n) {
        return { status: 'failed', reason: 'insufficient_usdt', destinationAddress };
      }
      // Redeem everything: the remainder re-mints on the next savings resume,
      // and a share-slice computed off a display balance is what previously
      // let the funded amount drift from the ordered amount.
      const minUsdtOut = amountWei - usdtWei;
      await redeemSavingsToUsdt({
        vaultAddress,
        shares,
        minUsdtOut: (minUsdtOut * 99n) / 100n, // 1% slippage floor, as elsewhere
        recipient: wallet.address,
        wallet,
      });
      usdtWei = await readUsdtWei();
      if (usdtWei < amountWei) {
        return { status: 'failed', reason: 'insufficient_usdt', destinationAddress };
      }
    }

    // ONE payment to Koywe, only once the full amount is provably in hand.
    const res = await transferUsdt({ to: destinationAddress, amountWei, wallet });
    return { status: 'submitted', transactionId: res.txHash, destinationAddress };
  } catch (error: any) {
    return {
      status: 'failed',
      reason: error?.message || 'unexpected_funding_error',
      destinationAddress,
    };
  }
};
