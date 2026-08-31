// BSC invite escrow — the client half of send/invite_bsc_flow.py and the
// ConfioInviteEscrow contract. The Algorand equivalent is inviteSendService.ts.
//
// Sending to someone who isn't on Confío yet locks cUSD+, cUSD or CONFIO in the
// escrow under (inviter, inviteId). Three legs, two of which live here:
//
//   create   this file. A sponsored 7702 batch [approve, createInvitation],
//            same prepare→sign→submit shape as bscSend.ts.
//   claim    NOT here. When the invitee verifies their phone the KMS sponsor
//            releases the escrow server-side — the backend is the party that
//            knows which phone belongs to whom.
//   reclaim  this file, after the 7-day window.
//
// The escrow accepts cUSD+, cUSD and CONFIO; USDT is not escrowable.

import { gql } from '@apollo/client';
import {
  BatchCall,
  BscRevertedError,
  bscGetNonce,
  bscWaitForReceipt,
  hashBatchIntent,
  receiptExecutedBatch,
  signIntentDigest,
  signSetCodeAuthorization,
  isOutcomeUnknown,
} from './evmWallet';
import {
  delegateNonce,
  fetchSponsored7702Params,
  isDelegatedTo,
} from './sponsored7702';

const PREPARE_INVITE = gql`
  mutation PrepareBscInvite($phone: String!, $phoneCountry: String, $amount: Decimal!, $tokenType: String!) {
    prepareBscInvite(phone: $phone, phoneCountry: $phoneCountry, amount: $amount, tokenType: $tokenType) {
      success
      error
      inviteId
      calls { to valueWei data }
      intentId
    }
  }
`;

const SUBMIT_INVITE = gql`
  mutation SubmitBscInvite($inviteId: String!, $nonce: String!, $deadline: String!, $intentSignature: String!, $authorization: BscSendAuthorizationInput) {
    submitBscInvite(inviteId: $inviteId, nonce: $nonce, deadline: $deadline, intentSignature: $intentSignature, authorization: $authorization) {
      success
      error
      authorizationRequired
      transactionHash
    }
  }
`;

const RECLAIM_CALLS = gql`
  mutation ReclaimInviteCalls($inviteId: String!) {
    reclaimInviteCalls(inviteId: $inviteId) {
      success
      error
      calls { to valueWei data }
      intentId
    }
  }
`;

const SUBMIT_RECLAIM = gql`
  mutation SubmitBscReclaimInvite($inviteId: String!, $nonce: String!, $deadline: String!, $intentSignature: String!, $authorization: BscSendAuthorizationInput) {
    submitBscReclaimInvite(inviteId: $inviteId, nonce: $nonce, deadline: $deadline, intentSignature: $intentSignature, authorization: $authorization) {
      success
      error
      authorizationRequired
      transactionHash
    }
  }
`;

export type BscInviteToken = 'CUSD_PLUS' | 'CUSD' | 'CONFIO';

export interface BscInviteParams {
  /** International form. The server keys invites by the FULL number. */
  phone: string;
  phoneCountry?: string;
  amount: string | number;
  tokenType: BscInviteToken;
}

export interface BscInviteResult {
  txHash: string;
  /** 0x-prefixed bytes32; also the stable retry key for this invite. */
  inviteId: string;
  /** Broadcast, outcome not yet observed. NOT a failure and NOT retryable —
   *  the escrow row is already the server's to settle. */
  pending?: boolean;
}

/** Stable error codes the UI maps to Spanish copy. */
export const BSC_INVITE_ERRORS: Record<string, string> = {
  bsc_invite_disabled: 'Las invitaciones con dinero están en preparación. Inténtalo más tarde.',
  disabled: 'Las invitaciones con dinero están en preparación. Inténtalo más tarde.',
  sponsored_rail_unavailable: 'Las invitaciones con dinero están en preparación. Inténtalo más tarde.',
  token_not_escrowable: 'Esa moneda no se puede reservar para una invitación.',
  invite_already_pending: 'Ya tienes una invitación pendiente para ese número.',
  // The escrow slot for (this phone, this inviter) is spent on-chain — the id
  // is deterministic and the contract never frees a settled slot, so a new
  // create for the same pair cannot succeed.
  invite_id_spent: 'Ya enviaste una invitación a ese número. Espera a que la reclame.',
  bad_phone_key: 'Ese número no parece válido.',
  no_bsc_address: 'Tu cuenta aún se está activando. Inténtalo en un momento.',
  invalid_amount: 'El monto no es válido.',
  insufficient_balance: 'Saldo insuficiente.',
  permission_denied: 'Tu rol no permite enviar fondos.',
  sponsor_busy: 'La red está ocupada. Inténtalo de nuevo en unos segundos.',
  gas_price_too_high: 'La red está congestionada. Inténtalo de nuevo en unos minutos.',
  invite_not_found: 'No encontramos esa invitación.',
  invite_not_pending: 'Esa invitación ya no está pendiente.',
  invite_not_reclaimable: 'Esa invitación ya no se puede devolver.',
  simulation_reverted: 'No se pudo completar en la red. Inténtalo de nuevo.',
  delegation_not_applied: 'No se pudo firmar en la red. Inténtalo de nuevo.',
};

/** Sign a server-prepared batch and hand the signature back. The client can
 * only sign or not sign — it never substitutes calldata. */
const signBatch = async (
  calls: BatchCall[],
  intentId: string,
  wallet: { address: string; privKeyHex: string },
  delegateAddress: string,
) => {
  // Independent reads, so pay for ONE round trip instead of two. The account
  // nonce stays conditional: it's read only on a first-ever (undelegated) send.
  const [execNonce, delegated] = await Promise.all([
    delegateNonce(wallet.address),
    isDelegatedTo(wallet.address, delegateAddress),
  ]);
  const deadline = BigInt(Math.floor(Date.now() / 1000) + 600);
  const digest = hashBatchIntent(calls, execNonce, deadline, intentId, wallet.address);
  const intentSignature = signIntentDigest(digest, wallet.privKeyHex);

  let authorization;
  if (!delegated) {
    const accountNonce = await bscGetNonce(wallet.address);
    authorization = signSetCodeAuthorization(delegateAddress, accountNonce, wallet.privKeyHex);
  }
  return { execNonce, deadline, intentSignature, authorization };
};

/** Wait for the batch and say whether OUR nonce actually executed. Neither
 * invite mutation returns the server's `execution` verdict (unlike
 * submitBscSend), so the receipt is the only proof available here. */
const settle = async (txHash: string, address: string, execNonce: bigint): Promise<{ pending: boolean }> => {
  let receipt;
  try {
    receipt = await bscWaitForReceipt(txHash);
  } catch (e) {
    // A receipt timeout is NOT a failed invite. The batch is on the network
    // and the server owns the PhoneInvite row. Reporting failure here is what
    // makes a user retry and escrow the money twice.
    if (isOutcomeUnknown(e)) return { pending: true };
    throw e;
  }
  const verdict = receiptExecutedBatch(receipt, address, execNonce);
  if (verdict === 'executed') return { pending: false };
  // Never shown proof either way — same reasoning as the timeout above.
  if (verdict === 'unknown') return { pending: true };
  // Mined without our BatchExecuted: silent 7702 no-op. A fresh prepare is the
  // retry path; the pending row expires and becomes reclaimable either way.
  throw new Error('delegation_not_applied');
};

export const createBscInvite = async (params: BscInviteParams): Promise<BscInviteResult> => {
  const { apolloClient } = await import('../apollo/client');
  const { getActiveEvmWallet } = await import('./secureDeterministicWallet');

  const sponsored = await fetchSponsored7702Params();
  if (!sponsored.enabled || !sponsored.delegateAddress) {
    throw new Error('sponsored_rail_unavailable');
  }
  const wallet = await getActiveEvmWallet();

  const { data } = await apolloClient.mutate({
    mutation: PREPARE_INVITE,
    variables: {
      phone: params.phone,
      phoneCountry: params.phoneCountry || null,
      amount: String(params.amount),
      tokenType: params.tokenType,
    },
  });
  const prep = data?.prepareBscInvite;
  if (!prep?.success) throw new Error(prep?.error || 'prepare_failed');

  const calls: BatchCall[] = (prep.calls || []).map((c: any) => ({
    to: c.to,
    valueWei: BigInt(c.valueWei),
    data: c.data,
  }));

  let lastError = 'unknown';
  for (let attempt = 0; attempt < 2; attempt++) {
    const { execNonce, deadline, intentSignature, authorization } =
      await signBatch(calls, prep.intentId, wallet, sponsored.delegateAddress);

    const res = await apolloClient.mutate({
      mutation: SUBMIT_INVITE,
      variables: {
        inviteId: prep.inviteId,
        nonce: execNonce.toString(),
        deadline: deadline.toString(),
        intentSignature,
        authorization,
      },
    });
    const sub = res.data?.submitBscInvite;
    if (!sub?.success) {
      lastError = sub?.error || 'sponsor rejected';
      // Nonce races are retryable with fresh reads; policy errors are not.
      if (sub?.authorizationRequired || sub?.error === 'stale_auth_nonce') continue;
      throw new Error(lastError);
    }

    const { pending } = await settle(sub.transactionHash as string, wallet.address, execNonce);
    return { txHash: sub.transactionHash, inviteId: prep.inviteId, pending };
  }
  throw new Error(lastError);
};

/** Take an expired invite's money back out of the escrow. */
export const reclaimBscInvite = async (
  inviteId: string,
): Promise<{ success: boolean; error?: string; txid?: string }> => {
  const { apolloClient } = await import('../apollo/client');
  const { getActiveEvmWallet } = await import('./secureDeterministicWallet');

  if (!inviteId) return { success: false, error: 'Falta el ID de la invitación' };
  try {
    const sponsored = await fetchSponsored7702Params();
    if (!sponsored.enabled || !sponsored.delegateAddress) {
      return { success: false, error: BSC_INVITE_ERRORS.sponsored_rail_unavailable };
    }
    const wallet = await getActiveEvmWallet();

    const prepResp = await apolloClient.mutate({
      mutation: RECLAIM_CALLS,
      variables: { inviteId },
    });
    const prep = prepResp.data?.reclaimInviteCalls;
    if (!prep?.success) {
      return {
        success: false,
        error: BSC_INVITE_ERRORS[prep?.error] || 'No se pudo preparar la devolución',
      };
    }
    const calls: BatchCall[] = (prep.calls || []).map((c: any) => ({
      to: c.to,
      valueWei: BigInt(c.valueWei),
      data: c.data,
    }));

    let lastError = 'unknown';
    for (let attempt = 0; attempt < 2; attempt++) {
      const { execNonce, deadline, intentSignature, authorization } =
        await signBatch(calls, prep.intentId, wallet, sponsored.delegateAddress);

      const res = await apolloClient.mutate({
        mutation: SUBMIT_RECLAIM,
        variables: {
          inviteId,
          nonce: execNonce.toString(),
          deadline: deadline.toString(),
          intentSignature,
          authorization,
        },
      });
      const sub = res.data?.submitBscReclaimInvite;
      if (!sub?.success) {
        lastError = sub?.error || 'sponsor rejected';
        if (sub?.authorizationRequired || sub?.error === 'stale_auth_nonce') continue;
        return { success: false, error: BSC_INVITE_ERRORS[lastError] || 'No se pudo devolver la invitación' };
      }
      // The server marks the row 'reclaiming' and its confirm task finalizes
      // from the chain, so a receipt we don't get to see is not a failure.
      return { success: true, txid: sub.transactionHash };
    }
    return { success: false, error: BSC_INVITE_ERRORS[lastError] || 'No se pudo devolver la invitación' };
  } catch (e: any) {
    if (e instanceof BscRevertedError) {
      return { success: false, error: 'La red rechazó la devolución. Inténtalo de nuevo.' };
    }
    return { success: false, error: e?.message || 'Error de red al devolver la invitación' };
  }
};
