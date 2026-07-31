// BSC dollar send — the client half of send/bsc_flow.py (Phase 2 of the
// cUSD phase-out; presaleBsc.ts shape).
//
// Two-step, server-authoritative: prepare resolves the recipient and picks
// the call shape SERVER-side (cUSD+ transfer / atomic redeem-to-USDT /
// raw USDT transfer), returning the EXACT single-call batch it stored —
// this client can only sign or not sign, never substitute calldata. Submit
// carries the EIP-712 intent signature (+ the 7702 authorization on first
// use). The KMS sponsor pays all gas.
//
// recipient_no_bsc_address is the coverage cold-start: the server already
// nudged the recipient by push; surface a friendly Spanish message.

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
  mutation PrepareBscSend($amount: Decimal!, $recipientUserId: ID, $recipientPhone: String, $recipientAddress: String, $memo: String, $idempotencyKey: String, $tokenType: String) {
    prepareBscSend(amount: $amount, recipientUserId: $recipientUserId, recipientPhone: $recipientPhone, recipientAddress: $recipientAddress, memo: $memo, idempotencyKey: $idempotencyKey, tokenType: $tokenType) {
      success
      error
      sendId
      calls { to valueWei data }
      tokenType
    }
  }
`;

const SUBMIT = gql`
  mutation SubmitBscSend($sendId: String!, $nonce: String!, $deadline: String!, $intentSignature: String!, $authorization: BscSendAuthorizationInput) {
    submitBscSend(sendId: $sendId, nonce: $nonce, deadline: $deadline, intentSignature: $intentSignature, authorization: $authorization) {
      success
      error
      authorizationRequired
      transactionHash
    }
  }
`;

export interface BscSendParams {
  amount: string | number;
  recipientUserId?: string;
  recipientPhone?: string;
  recipientAddress?: string;
  memo?: string;
  idempotencyKey?: string;
  /** Explicit token request (shapes D/E): 'CUSD_PLUS' sends the token
   * itself to any address, 'CONFIO' sends BEP-20 CONFIO (amount = token
   * count). Absent = dollar-value send, server picks the shape. */
  tokenType?: 'CUSD_PLUS' | 'CONFIO';
}

export interface BscSendResult {
  txHash: string;
  sendId: string;
  /** What actually moved on-chain: CUSD_PLUS (shares) or USDT. */
  tokenType: string;
}

/** Stable error codes the UI maps to Spanish copy. */
export const BSC_SEND_ERRORS: Record<string, string> = {
  recipient_no_bsc_address:
    'Tu contacto aún no puede recibir dólares — le avisamos para que abra la app y active su cuenta.',
  recipient_not_on_confio:
    'Ese número no está en Confío todavía.',
  invalid_recipient_address: 'La dirección no es válida.',
  self_send_not_allowed: 'Esa dirección es tuya — elige otro destinatario.',
  insufficient_balance: 'Saldo insuficiente.',
  bsc_send_disabled: 'Los envíos están en preparación. Inténtalo más tarde.',
  sponsor_busy: 'La red está ocupada. Inténtalo de nuevo en unos segundos.',
};

export const sendBscDollar = async (params: BscSendParams): Promise<BscSendResult> => {
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
      amount: String(params.amount),
      recipientUserId: params.recipientUserId,
      recipientPhone: params.recipientPhone,
      recipientAddress: params.recipientAddress,
      memo: params.memo || '',
      idempotencyKey: params.idempotencyKey || '',
      tokenType: params.tokenType || null,
    },
  });
  const prep = data?.prepareBscSend;
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

    const digest = hashBatchIntent(calls, execNonce, deadline, wallet.address);
    const intentSignature = signIntentDigest(digest, wallet.privKeyHex);

    let authorization;
    if (!(await isDelegatedTo(wallet.address, sponsored.delegateAddress))) {
      const accountNonce = await bscGetNonce(wallet.address);
      authorization = signSetCodeAuthorization(
        sponsored.delegateAddress, accountNonce, wallet.privKeyHex);
    }

    const res = await apolloClient.mutate({
      mutation: SUBMIT,
      variables: {
        sendId: prep.sendId,
        nonce: execNonce.toString(),
        deadline: deadline.toString(),
        intentSignature,
        authorization,
      },
    });
    const sub = res.data?.submitBscSend;
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
        sendId: prep.sendId,
        tokenType: prep.tokenType,
      };
    }
    // Mined but the delegate nonce didn't move: silent 7702 no-op. The
    // send row stays SUBMITTED until the confirm task fails it; a fresh
    // prepare is the retry path.
    lastError = 'delegation_not_applied';
    throw new Error(lastError);
  }
  throw new Error(lastError);
};
