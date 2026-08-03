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
  mutation PrepareBscPayrollAdmin($action: String!, $amount: Decimal, $delegateUserId: ID, $delegateUserIds: [ID], $includeSelf: Boolean, $allowed: Boolean, $tokenType: String) {
    prepareBscPayrollAdmin(action: $action, amount: $amount, delegateUserId: $delegateUserId, delegateUserIds: $delegateUserIds, includeSelf: $includeSelf, allowed: $allowed, tokenType: $tokenType) {
      success
      error
      errorName
      calls { to valueWei data }
      intentId
      shares
      asset
      tokenType
      delegateAddress
      delegateAddresses
    }
  }
`;

const SUBMIT_ADMIN = gql`
  mutation SubmitBscPayrollAdmin($action: String!, $shares: String, $asset: Int, $delegateAddress: String, $delegateAddresses: [String], $allowed: Boolean, $nonce: String!, $deadline: String!, $intentSignature: String!, $authorization: BscPayrollAuthorizationInput) {
    submitBscPayrollAdmin(action: $action, shares: $shares, asset: $asset, delegateAddress: $delegateAddress, delegateAddresses: $delegateAddresses, allowed: $allowed, nonce: $nonce, deadline: $deadline, intentSignature: $intentSignature, authorization: $authorization) {
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
  // Belt to PayrollPendingScreen's braces: the screen switches into the
  // item's business context before paying, so this should be unreachable —
  // but it used to surface as a bare error CODE, and a delegate reading
  // "business_context_required" learns nothing about what to do.
  business_context_required:
    'Cambia a la cuenta de negocio para pagar esta nómina.',
  // Names WHERE the money has to be. A business reading a bare "Saldo
  // insuficiente" over a balance it can see has no way to know the top-up
  // draws on its business account, not on the payroll vault.
  insufficient_balance:
    'Tu cuenta de negocio no tiene ese saldo disponible para mover a la bóveda.',
  payout_expired: 'La autorización expiró. Inténtalo de nuevo.',
  sponsor_busy: 'La red está ocupada. Inténtalo de nuevo en unos segundos.',
  business_no_bsc_address: 'La cuenta del negocio aún no está activada para BSC.',
  delegate_no_bsc_address: 'Esa persona aún no tiene su cuenta activada.',
  simulation_reverted: 'No se pudo procesar el pago. Verifica el fondo de nómina.',
  wage_below_redeem_minimum: 'Este pago es demasiado pequeño para enviarse a esta persona. Debe ser de al menos $1.',
  run_not_due: 'Esta nómina está programada para más adelante.',
  // This run can ONLY be paid from the cUSD+ vault, so a paused rail is not a
  // reason to try the other chain — the money is where it is.
  bsc_payroll_paused:
    'Los pagos de nómina están pausados temporalmente. Tus fondos siguen en la bóveda.',
  run_cap_exceeded: 'Esta nómina supera el límite que configuraste para el período.',
  // Now user-facing: this used to reroute the operation to the legacy chain,
  // which for a BSC business meant funding a vault its payouts never touch.
  sponsored_rail_unavailable:
    'La red está temporalmente fuera de servicio. Tus fondos están seguros — inténtalo de nuevo en unos minutos.',
};

/** Message for a thrown rail error, including the codes that carry a name
 * after a colon (`delegate_no_bsc_address:Ana Pérez`). */
export const bscPayrollErrorMessage = (raw?: string): string => {
  const code = raw || '';
  const [head, ...rest] = code.split(':');
  const name = rest.join(':').trim();
  if (head === 'delegate_no_bsc_address' && name) {
    return `${name} aún no tiene su cuenta activada. Pídele que abra Confío una vez y vuelve a intentar.`;
  }
  return BSC_PAYROLL_ERRORS[head] || code || 'No se pudo completar la operación.';
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
  /** Activation allowlists the owner plus every chosen delegate. One batch,
   * not one per person — the sponsor's daily batch allowance is small. */
  delegateUserIds?: string[];
  /** Allowlist the acting user's own signer too (activation). Resolved from
   * the JWT server-side, so it never depends on the client knowing who it is. */
  includeSelf?: boolean;
  allowed?: boolean;
  /** Which escrow pool to fund or withdraw. The pools are separate money and
   * a business can hold both, so the CALLER names one — the server used to
   * derive it, which hid the whole USDT pool from anyone still holding a
   * single cUSD+ share. Omit to use the business's default pool. */
  tokenType?: 'CUSD_PLUS' | 'USDT';
}

/** Business escrow op, signed by the BUSINESS EOA (active account must be
 * the business). Same prepare → sign → submit(+auth retry) as bscSend. */
export const runBscPayrollAdmin = async (
  params: BscPayrollAdminParams,
): Promise<{ txHash: string }> => {
  const { apolloClient } = await import('../apollo/client');
  const { getActiveEvmWallet } = await import('./secureDeterministicWallet');

  // PREPARE FIRST, relay check second. The order matters: only the server
  // knows whether this business is on the BSC rail. Checking the relay first
  // meant a momentary 7702 outage threw `sponsored_rail_unavailable` before
  // anyone asked, and the callers treated that as "use Algorand" — which for
  // a BSC business deposits real money into the wrong vault, one the payouts
  // never spend from. Prepare answering `bsc_payroll_disabled` is the ONLY
  // legitimate signal to use the legacy rail.
  const { data } = await apolloClient.mutate({
    mutation: PREPARE_ADMIN,
    variables: {
      action: params.action,
      amount: params.amountUsd,
      delegateUserId: params.delegateUserId,
      delegateUserIds: params.delegateUserIds,
      tokenType: params.tokenType,
      includeSelf: params.includeSelf ?? false,
      allowed: params.allowed ?? true,
    },
  });
  const prep = data?.prepareBscPayrollAdmin;
  if (!prep?.success) {
    // Name the person when the server named them: "activate" failing with a
    // bare code told an owner nothing about WHICH delegate has to open the
    // app first.
    if (prep?.error === 'delegate_no_bsc_address' && prep?.errorName) {
      throw new Error(`delegate_no_bsc_address:${prep.errorName}`);
    }
    throw new Error(prep?.error || 'prepare_failed');
  }

  // The server accepted, so this business IS on the BSC rail. A relay outage
  // from here is a "try again", never a reason to move to another chain.
  const sponsored = await fetchSponsored7702Params();
  if (!sponsored.enabled || !sponsored.delegateAddress) {
    throw new Error('sponsored_rail_unavailable');
  }
  const wallet = await getActiveEvmWallet();

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
      mutation: SUBMIT_ADMIN,
      variables: {
        action: params.action,
        shares: prep.shares,
        // Which escrow pool the batch touches. Echoed back verbatim: the
        // server rebuilds the SAME calls from it, and those are the bytes
        // the business signed — a different pool just fails recovery.
        asset: prep.asset ?? 0,
        delegateAddress: prep.delegateAddress,
        delegateAddresses: prep.delegateAddresses,
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
