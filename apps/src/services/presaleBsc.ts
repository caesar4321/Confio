// BSC presale purchase — the client half of presale/bsc_flow.py.
//
// Two-step, server-authoritative: prepare returns the EXACT [approve, buy]
// batch the server stored (and will verify the signature against — this
// client cannot substitute calldata, it can only sign or not sign), then
// submit carries the EIP-712 intent signature and, on first use, the 7702
// authorization. The KMS sponsor pays all gas; the vault's curve alone
// decides the price, capped by maxPayment = the amount the user confirmed.

import { gql } from '@apollo/client';
import {
  BatchCall,
  bscGetNonce,
  bscWaitForReceipt,
  hashBatchIntent,
  signIntentDigest,
  signSetCodeAuthorization,
} from './evmWallet';
import {
  delegateNonce,
  fetchSponsored7702Params,
  isDelegatedTo,
} from './sponsored7702';

const PREPARE = gql`
  mutation PrepareBscPresalePurchase($amountUsd: Decimal!, $acceptedTerms: Boolean!, $notUsAttestation: Boolean!) {
    prepareBscPresalePurchase(amountUsd: $amountUsd, acceptedTerms: $acceptedTerms, notUsAttestation: $notUsAttestation) {
      success
      error
      purchaseId
      calls { to valueWei data }
      confioAmount
      cost
      maxPayment
      avgPrice
      intentId
    }
  }
`;

const SUBMIT = gql`
  mutation SubmitBscPresalePurchase($purchaseId: String!, $nonce: String!, $deadline: String!, $intentSignature: String!, $authorization: BscPresaleAuthorizationInput) {
    submitBscPresalePurchase(purchaseId: $purchaseId, nonce: $nonce, deadline: $deadline, intentSignature: $intentSignature, authorization: $authorization) {
      success
      error
      authorizationRequired
      transactionHash
    }
  }
`;

export interface BscPresaleQuote {
  purchaseId: string;
  confioAmount: string;
  cost: string;
  avgPrice: string;
}

export const buyPresaleBsc = async (
  amountUsd: string | number,
): Promise<{ txHash: string; quote: BscPresaleQuote }> => {
  const { apolloClient } = await import('../apollo/client');
  const { getActiveEvmWallet } = await import('./secureDeterministicWallet');

  const sponsored = await fetchSponsored7702Params();
  if (!sponsored.enabled || !sponsored.delegateAddress) {
    throw new Error('sponsored_rail_unavailable');
  }
  const wallet = await getActiveEvmWallet();

  const { data } = await apolloClient.mutate({
    mutation: PREPARE,
    variables: {
      amountUsd: String(amountUsd),
      acceptedTerms: true,
      notUsAttestation: true,
    },
  });
  const prep = data?.prepareBscPresalePurchase;
  if (!prep?.success) throw new Error(prep?.error || 'prepare_failed');

  const calls: BatchCall[] = (prep.calls || []).map((c: any) => ({
    to: c.to,
    valueWei: BigInt(c.valueWei),
    data: c.data,
  }));

  let lastError = 'unknown';
  for (let attempt = 0; attempt < 2; attempt++) {
    const execNonce = await delegateNonce(wallet.address);
    const deadline = BigInt(Math.floor(Date.now() / 1000) + 600);

    const digest = hashBatchIntent(calls, execNonce, deadline, prep.intentId, wallet.address);
    const intentSignature = signIntentDigest(digest, wallet.privKeyHex);

    // First use (or re-delegation): the authorization tuple rides along.
    // The server re-checks delegation state authoritatively either way.
    // SetCodeAuthorization's shape matches BscPresaleAuthorizationInput.
    let authorization;
    if (!(await isDelegatedTo(wallet.address, sponsored.delegateAddress))) {
      const accountNonce = await bscGetNonce(wallet.address);
      authorization = signSetCodeAuthorization(
        sponsored.delegateAddress, accountNonce, wallet.privKeyHex);
    }

    const res = await apolloClient.mutate({
      mutation: SUBMIT,
      variables: {
        purchaseId: prep.purchaseId,
        nonce: execNonce.toString(),
        deadline: deadline.toString(),
        intentSignature,
        authorization,
      },
    });
    const sub = res.data?.submitBscPresalePurchase;
    if (!sub?.success) {
      lastError = sub?.error || 'sponsor rejected';
      // Nonce races are retryable with fresh reads; policy errors are not.
      if (sub?.authorizationRequired || sub?.error === 'stale_auth_nonce') continue;
      throw new Error(lastError);
    }

    await bscWaitForReceipt(sub.transactionHash as string);
    if ((await delegateNonce(wallet.address)) > execNonce) {
      return {
        txHash: sub.transactionHash,
        quote: {
          purchaseId: prep.purchaseId,
          confioAmount: prep.confioAmount,
          cost: prep.cost,
          avgPrice: prep.avgPrice,
        },
      };
    }
    // Mined but the delegate nonce didn't move: silent 7702 no-op —
    // fresh reads, one more shot (the server marks the purchase failed;
    // a NEW prepare gives a fresh quote/purchase).
    lastError = 'delegation_not_applied';
    throw new Error(lastError);
  }
  throw new Error(lastError);
};
