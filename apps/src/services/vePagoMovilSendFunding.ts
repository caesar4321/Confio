// Funding a Pago Móvil send that already exists as an order: claim its one
// funding, pay it from the person's own wallet, tell the server. The same
// steps, in the same order and with the same guards, as the send screen's
// own (VePagoMovilSendScreen `fund`), for a send approved from the chat.
import { gql } from '@apollo/client';
import { REPORT_VE_SEND_FUNDING, START_VE_SEND_FUNDING, VE_SEND_ORDER, type VeSendOrder } from './vePagoMovilSend';

// The Retiro funding path redeems from these; served, never hardcoded.
const FUNDING_PARAMS = gql`
  query VePagoMovilSendFundingParams {
    cusdPlusConvertParams { vaultAddress cusdAddress }
  }
`;

const GENERIC = 'No pudimos conectar. Intenta de nuevo en unos segundos.';

/** Nothing left the wallet: the message says so, and it is safe to try again. */
export class NothingSentError extends Error {}

/**
 * 'sent': the dollars left and the order knows. 'unknown': they were
 * broadcast and no verdict came back; the chain decides, and the order must
 * not be paid again. Throws NothingSentError when nothing was sent.
 */
export async function fundVePagoMovilSend(orderId: string): Promise<'sent' | 'unknown'> {
  const { apolloClient } = await import('../apollo/client');
  const { getActiveEvmWallet } = await import('./secureDeterministicWallet');
  const { fundUsdtDestination } = await import('./cusdPlusVault');
  const { isOutcomeUnknown } = await import('./evmWallet');

  const params = await apolloClient.query({ query: FUNDING_PARAMS, fetchPolicy: 'cache-first' }).catch(() => null);
  const vaultAddress: string = params?.data?.cusdPlusConvertParams?.vaultAddress || '';
  const cusdAddress: string = params?.data?.cusdPlusConvertParams?.cusdAddress || '';
  // The funding claim is single-use: never spend it before the redeem
  // contracts are known.
  if (!cusdAddress) {
    throw new NothingSentError(GENERIC);
  }
  // Pin the signer before the single-use claim: the personal wallet, and
  // only if it is the wallet this order was made for. An account switch
  // mid-flow can then never debit another wallet.
  const wallet = await getActiveEvmWallet({ type: 'personal', index: 0 });
  const order = await apolloClient.query({ query: VE_SEND_ORDER, variables: { orderId }, fetchPolicy: 'network-only' })
    .catch(() => null);
  const expected = order?.data?.vePagomovilSendOrder?.wallet;
  if (!expected || wallet.address.toLowerCase() !== String(expected).toLowerCase()) {
    throw new NothingSentError('Este envío pertenece a otra cuenta. No se envió nada.');
  }
  const start = await apolloClient.mutate({ mutation: START_VE_SEND_FUNDING, variables: { orderId }, fetchPolicy: 'no-cache' })
    .catch(() => null);
  const claimed: VeSendOrder | undefined = start?.data?.startVePagomovilSendFunding;
  if (!claimed?.success || !claimed.funding || claimed.funding.network !== 'BSC'
      || !/^0x[0-9a-fA-F]{40}$/.test(claimed.funding.depositAddress)
      || !/^[1-9][0-9]*$/.test(claimed.funding.depositAmountWei)) {
    throw new NothingSentError(claimed?.error || GENERIC);
  }
  // A bridge target expires: never sign for one that is about to (e.g. the
  // phone slept after the claim). Nothing is sent; the send can be cancelled.
  if (claimed.funding.expiresAt && claimed.funding.expiresAt * 1000 < Date.now() + 60_000) {
    throw new NothingSentError('El envío venció antes de firmarlo. No se envió nada; cancélalo y vuelve a intentarlo.');
  }
  let txHash: string | null = null;
  let outcome: 'sent' | 'unknown' = 'sent';
  try {
    // The audited Retiro batch (redeem with fee + exact transfer), signed
    // by the pinned wallet.
    const res = await fundUsdtDestination({
      to: claimed.funding.depositAddress,
      amountWei: BigInt(claimed.funding.depositAmountWei),
      grossDebitWei: claimed.funding.grossDebitAmountWei ? BigInt(claimed.funding.grossDebitAmountWei) : null,
      vaultAddress: vaultAddress || null,
      cusdAddress,
      wallet,
      // Never signed to outlive the bridge target.
      notAfter: claimed.funding.expiresAt ? claimed.funding.expiresAt - 30 : undefined,
    });
    txHash = res.txHash;
  } catch (fundError: any) {
    if (!isOutcomeUnknown(fundError)) {
      // Refused before anything was broadcast.
      throw new NothingSentError(fundError?.name === 'InsufficientWithdrawableError'
        ? 'No tienes saldo suficiente. No se envió nada.'
        : 'No se envió nada. Tu dinero sigue en tu cuenta. Podrás cancelar este envío en unos minutos.');
    }
    // Broadcast, verdict lost: never a failure, the chain decides.
    outcome = 'unknown';
  }
  await apolloClient.mutate({ mutation: REPORT_VE_SEND_FUNDING, variables: { orderId, txHash }, fetchPolicy: 'no-cache' })
    .catch(() => null);
  return outcome;
}
