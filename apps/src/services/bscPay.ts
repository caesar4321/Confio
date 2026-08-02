// BSC invoice payment — the client half of payments/bsc_flow.py (Phase 2).
//
// Two-step, server-authoritative (bscSend.ts shape): prepare validates the
// invoice server-side and returns the EXACT 2-transfer batch it stored
// ([merchant_net, treasury_fee], atomic under ConfioBatchDelegate.execute)
// — this client can only sign or not sign. Submit carries the EIP-712
// intent signature (+ the 7702 authorization on first use). The KMS
// sponsor pays all gas; the merchant receives net = gross − 0.9% (ceil).

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
  mutation PrepareBscInvoicePayment($invoiceId: String!, $idempotencyKey: String) {
    prepareBscInvoicePayment(invoiceId: $invoiceId, idempotencyKey: $idempotencyKey) {
      success
      error
      paymentId
      calls { to valueWei data }
      tokenType
      intentId
      net
      fee
    }
  }
`;

const SUBMIT = gql`
  mutation SubmitBscInvoicePayment($paymentId: String!, $nonce: String!, $deadline: String!, $intentSignature: String!, $authorization: BscPaymentAuthorizationInput) {
    submitBscInvoicePayment(paymentId: $paymentId, nonce: $nonce, deadline: $deadline, intentSignature: $intentSignature, authorization: $authorization) {
      success
      error
      authorizationRequired
      transactionHash
      execution
    }
  }
`;

export const BSC_PAY_ERRORS: Record<string, string> = {
  merchant_no_bsc_address:
    'Este negocio aún no puede recibir dólares digitales — le avisamos para que active sus cobros.',
  insufficient_balance: 'Saldo insuficiente.',
  invoice_expired: 'Este cobro ya expiró. Pide al negocio un código nuevo.',
  invoice_not_pending: 'Este cobro ya no está disponible.',
  invoice_already_paid: 'Este cobro ya fue pagado.',
  bsc_pay_disabled: 'Los pagos están en preparación. Inténtalo más tarde.',
  // The charge menu is cUSD+ and CONFIO; anything else is an invoice from a
  // rail this build can't settle (or a token not yet configured server-side).
  unsupported_token: 'Este cobro usa una moneda que esta versión no puede pagar. Actualiza Confío.',
  confio_not_configured: 'Los pagos en CONFIO están en preparación. Inténtalo más tarde.',
  sponsor_busy: 'La red está ocupada. Inténtalo de nuevo en unos segundos.',
};

export interface BscPayResult {
  txHash: string;
  paymentId: string;
  tokenType: string;
  net: string;
  fee: string;
}

export const payInvoiceBsc = async (
  invoiceId: string,
  idempotencyKey?: string,
): Promise<BscPayResult> => {
  const { apolloClient } = await import('../apollo/client');
  const { getActiveEvmWallet } = await import('./secureDeterministicWallet');

  const sponsored = await fetchSponsored7702Params();
  if (!sponsored.enabled || !sponsored.delegateAddress) {
    throw new Error('sponsored_rail_unavailable');
  }
  const wallet = await getActiveEvmWallet();

  const { data } = await apolloClient.mutate({
    mutation: PREPARE,
    variables: { invoiceId, idempotencyKey: idempotencyKey || '' },
  });
  const prep = data?.prepareBscInvoicePayment;
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

    let authorization;
    if (!delegated) {
      const accountNonce = await bscGetNonce(wallet.address);
      authorization = signSetCodeAuthorization(
        sponsored.delegateAddress, accountNonce, wallet.privKeyHex);
    }

    const res = await apolloClient.mutate({
      mutation: SUBMIT,
      variables: {
        paymentId: prep.paymentId,
        nonce: execNonce.toString(),
        deadline: deadline.toString(),
        intentSignature,
        authorization,
      },
    });
    const sub = res.data?.submitBscInvoicePayment;
    if (!sub?.success) {
      lastError = sub?.error || 'sponsor rejected';
      if (sub?.authorizationRequired || sub?.error === 'stale_auth_nonce') continue;
      throw new Error(lastError);
    }

    const done = {
      txHash: sub.transactionHash,
      paymentId: prep.paymentId,
      tokenType: prep.tokenType,
      net: prep.net,
      fee: prep.fee,
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
    lastError = 'delegation_not_applied';
    throw new Error(lastError);
  }
  throw new Error(lastError);
};
