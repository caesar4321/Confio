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
  BscReceiptTimeoutError,
  BscRevertedError,
  bscGetNonce,
  bscWaitForReceipt,
  hashBatchIntent,
  receiptExecutedBatch,
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
      execution
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
    // Independent reads, so pay for ONE round trip instead of two — each is
    // a phone→server→BSC hop and both are always needed. The account nonce
    // stays conditional: it's read only on a first-ever (undelegated) call.
    const [execNonce, delegated] = await Promise.all([
      delegateNonce(wallet.address),
      isDelegatedTo(wallet.address, sponsored.delegateAddress),
    ]);
    const deadline = BigInt(Math.floor(Date.now() / 1000) + 600);

    const digest = hashBatchIntent(calls, execNonce, deadline, prep.intentId, wallet.address);
    const intentSignature = signIntentDigest(digest, wallet.privKeyHex);

    // First use (or re-delegation): the authorization tuple rides along.
    // The server re-checks delegation state authoritatively either way.
    // SetCodeAuthorization's shape matches BscPresaleAuthorizationInput.
    let authorization;
    if (!delegated) {
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

    const done = {
      txHash: sub.transactionHash,
      quote: {
        purchaseId: prep.purchaseId,
        confioAmount: prep.confioAmount,
        cost: prep.cost,
        avgPrice: prep.avgPrice,
      },
    };

    // The sponsor watched the chain before answering; null (it didn't see
    // the tx inside its budget) falls through to our own poll.
    //
    // There is NO "older server omits the field" case: GraphQL validates the
    // whole operation up front, so a server without `execution` fails this
    // ENTIRE mutation with "Cannot query field" and no send happens at all
    // (Codex audit 2026-08-02 [P1]). The server schema must therefore be
    // deployed BEFORE this bundle ships — the normal order, since app
    // releases lag server deploys.
    if (sub.execution === 'executed') return done;
    if (sub.execution === 'reverted') throw new BscRevertedError(sub.transactionHash);
    if (sub.execution !== 'noop') {
      // Proof of execution from the receipt we already hold: the delegate
      // emits BatchExecuted(nonce) as this EOA, which is exactly what a
      // second nonces() read used to ask the chain.
      const receipt = await bscWaitForReceipt(sub.transactionHash as string);
      const verdict = receiptExecutedBatch(receipt, wallet.address, execNonce);
      if (verdict === 'executed') return done;
      // We were never shown proof either way (no logs field, or a log list
      // missing the trailing BatchExecuted). Outcome-unknown, NOT failure —
      // callers must not re-send on it.
      if (verdict === 'unknown') throw new BscReceiptTimeoutError(sub.transactionHash);
    }
    // Mined without our BatchExecuted: silent 7702 no-op —
    // fresh reads, one more shot (the server marks the purchase failed;
    // a NEW prepare gives a fresh quote/purchase).
    lastError = 'delegation_not_applied';
    throw new Error(lastError);
  }
  throw new Error(lastError);
};
