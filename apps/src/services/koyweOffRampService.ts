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

    for (let attempt = 0; attempt < 2; attempt += 1) {
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

      if (buildResult?.error === 'requires_app_optin' && attempt === 0) {
        const optInResult = await cusdAppOptInService.handleAppOptIn(activeAccount);
        if (!optInResult.success) {
          return { status: 'failed', reason: optInResult.error || 'requires_app_optin' };
        }
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
