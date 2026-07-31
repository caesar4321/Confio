// BSC payroll — client half of payroll/bsc_flow.py (Phase 2 W3).
//
// Two distinct signing roles, matching the on-chain delegate model:
//
//  admin ops (fund / withdraw / set_delegate): the BUSINESS EOA signs a
//    normal 7702 sponsored batch (bscSend.ts shape). Must run from the
//    business account context — the active wallet IS the business key.
//
//  payout: the executing user signs the server-prepared EIP-712 Payout
//    digest with their OWN PERSONAL key (ConfioPayrollVault verifies it
//    against the on-chain allowlist; the KMS sponsor broadcasts). This is
//    why an employee-delegate can pay out without ever holding the
//    business key.

import { gql } from '@apollo/client';
import {
  BatchCall,
  bscGetNonce,
  hashBatchIntent,
  signIntentDigest,
  signSetCodeAuthorization,
} from './evmWallet';
import {
  delegateNonce,
  fetchSponsored7702Params,
  isDelegatedTo,
} from './sponsored7702';

const PREPARE_ADMIN = gql`
  mutation PrepareBscPayrollAdmin($action: String!, $amount: Decimal, $delegateUserId: ID, $allowed: Boolean) {
    prepareBscPayrollAdmin(action: $action, amount: $amount, delegateUserId: $delegateUserId, allowed: $allowed) {
      success
      error
      calls { to valueWei data }
      intentId
      shares
      delegateAddress
    }
  }
`;

const SUBMIT_ADMIN = gql`
  mutation SubmitBscPayrollAdmin($action: String!, $shares: String, $delegateAddress: String, $allowed: Boolean, $nonce: String!, $deadline: String!, $intentSignature: String!, $authorization: BscPayrollAuthorizationInput) {
    submitBscPayrollAdmin(action: $action, shares: $shares, delegateAddress: $delegateAddress, allowed: $allowed, nonce: $nonce, deadline: $deadline, intentSignature: $intentSignature, authorization: $authorization) {
      success
      error
      authorizationRequired
      transactionHash
    }
  }
`;

const PREPARE_PAYOUT = gql`
  mutation PrepareBscPayrollPayout($payrollItemId: String!) {
    prepareBscPayrollPayout(payrollItemId: $payrollItemId) {
      success
      error
      digest
      deadline
      redeemToUsdt
    }
  }
`;

const SUBMIT_PAYOUT = gql`
  mutation SubmitBscPayrollPayout($payrollItemId: String!, $signature: String!) {
    submitBscPayrollPayout(payrollItemId: $payrollItemId, signature: $signature) {
      success
      error
      transactionHash
    }
  }
`;

export const BSC_PAYROLL_ERRORS: Record<string, string> = {
  bsc_payroll_disabled: 'La nómina digital está en preparación. Inténtalo más tarde.',
  recipient_no_bsc_address:
    'Esta persona aún no puede recibir su pago — le avisamos para que active su cuenta.',
  not_onchain_delegate:
    'Tu cuenta aún no está autorizada para pagar nómina de este negocio. Pide al dueño que te autorice.',
  insufficient_escrow: 'El fondo de nómina no alcanza. Deposita primero.',
  insufficient_balance: 'Saldo insuficiente.',
  payout_expired: 'La autorización expiró. Inténtalo de nuevo.',
  sponsor_busy: 'La red está ocupada. Inténtalo de nuevo en unos segundos.',
  business_no_bsc_address: 'La cuenta del negocio aún no está activada para BSC.',
  delegate_no_bsc_address: 'Esa persona aún no tiene su cuenta activada.',
  simulation_reverted: 'No se pudo procesar el pago. Verifica el fondo de nómina.',
};

const hexToBytes = (hex: string): Uint8Array => {
  const clean = hex.replace(/^0x/, '');
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(clean.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
};

export interface BscPayrollAdminParams {
  action: 'fund' | 'withdraw' | 'set_delegate';
  amountUsd?: string;
  delegateUserId?: string;
  allowed?: boolean;
}

/** Business escrow op, signed by the BUSINESS EOA (active account must be
 * the business). Same prepare → sign → submit(+auth retry) as bscSend. */
export const runBscPayrollAdmin = async (
  params: BscPayrollAdminParams,
): Promise<{ txHash: string }> => {
  const { apolloClient } = await import('../apollo/client');
  const { getActiveEvmWallet } = await import('./secureDeterministicWallet');

  const sponsored = await fetchSponsored7702Params();
  if (!sponsored.enabled || !sponsored.delegateAddress) {
    throw new Error('sponsored_rail_unavailable');
  }
  const wallet = await getActiveEvmWallet();

  const { data } = await apolloClient.mutate({
    mutation: PREPARE_ADMIN,
    variables: {
      action: params.action,
      amount: params.amountUsd,
      delegateUserId: params.delegateUserId,
      allowed: params.allowed ?? true,
    },
  });
  const prep = data?.prepareBscPayrollAdmin;
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

    let authorization;
    if (!(await isDelegatedTo(wallet.address, sponsored.delegateAddress))) {
      const accountNonce = await bscGetNonce(wallet.address);
      authorization = signSetCodeAuthorization(
        sponsored.delegateAddress, accountNonce, wallet.privKeyHex);
    }

    const res = await apolloClient.mutate({
      mutation: SUBMIT_ADMIN,
      variables: {
        action: params.action,
        shares: prep.shares,
        delegateAddress: prep.delegateAddress,
        allowed: params.allowed ?? true,
        nonce: execNonce.toString(),
        deadline: deadline.toString(),
        intentSignature,
        authorization,
      },
    });
    const sub = res.data?.submitBscPayrollAdmin;
    if (sub?.success) return { txHash: sub.transactionHash };
    lastError = sub?.error || 'sponsor rejected';
    if (sub?.authorizationRequired || sub?.error === 'stale_auth_nonce') continue;
    throw new Error(lastError);
  }
  throw new Error(lastError);
};

/** Execute one payroll item on BSC. The digest is signed with the
 * executing user's PERSONAL key regardless of the active (business)
 * context — that key is what the on-chain allowlist knows. */
export const payBscPayrollItem = async (
  payrollItemId: string,
): Promise<{ txHash: string; redeemToUsdt: boolean }> => {
  const { apolloClient } = await import('../apollo/client');
  const { getActiveEvmWallet } = await import('./secureDeterministicWallet');

  const { data } = await apolloClient.mutate({
    mutation: PREPARE_PAYOUT,
    variables: { payrollItemId },
  });
  const prep = data?.prepareBscPayrollPayout;
  if (!prep?.success) throw new Error(prep?.error || 'prepare_failed');

  const personal = await getActiveEvmWallet({ type: 'personal', index: 0 });
  const signature = signIntentDigest(hexToBytes(prep.digest), personal.privKeyHex);

  const res = await apolloClient.mutate({
    mutation: SUBMIT_PAYOUT,
    variables: { payrollItemId, signature },
  });
  const sub = res.data?.submitBscPayrollPayout;
  if (!sub?.success) throw new Error(sub?.error || 'submit_failed');
  return { txHash: sub.transactionHash, redeemToUsdt: !!prep.redeemToUsdt };
};
