import { gql } from '@apollo/client';
import { keccak_256 } from '@noble/hashes/sha3';
import { bytesToHex, utf8ToBytes } from '@noble/hashes/utils';
import { secureRandomBytes } from '../setup/entropyGuard';
import { BatchCall, bscGetNonce, hashBatchIntent, signIntentDigest, signSetCodeAuthorization } from './evmWallet';
import { delegateNonce, fetchSponsored7702Params, isDelegatedTo } from './sponsored7702';
import { receiveAuthorizationDigest, RELAY_RECEIVERS } from './polygonReturn';

export const BRIDGE_AVAILABILITY = gql`query PaymentBridgeAvailability {
  paymentBridgeAvailability { toProvider toWallet hasHistory }
  paymentBridgeInstructions { internalId country holderName canFund }
}`;

export interface BridgeTransfer {
  providerCredited: boolean;
  internalId: string; status: string; sourceTokenId: string;
  sourceAddress: string; destinationAddress: string; depositAddress: string;
  amountUnits: string; amountOut: string; amountOutMin: string;
  deadline: string; intentId: string; authorizationNonce: string;
  feeUnits: string; grossRedeemUnits: string; walletUsdtUnits: string;
  sourceTxHash: string; destinationTxHash: string; actualOutUnits: string;
  calls: { to: string; value: string; data: string }[];
}

export const FIELDS = gql`fragment PaymentBridgeFields on PaymentBridgeTransferType {
  internalId status providerCredited sourceTokenId sourceAddress destinationAddress depositAddress
  amountUnits amountOut amountOutMin deadline intentId authorizationNonce
  feeUnits grossRedeemUnits walletUsdtUnits sourceTxHash destinationTxHash actualOutUnits
  calls { to value data }
}`;

export const BRIDGE_HISTORY = gql`query MyPaymentBridges($offset: Int!, $limit: Int!) {
  myPaymentBridges(offset: $offset, limit: $limit) { ...PaymentBridgeFields }
} ${FIELDS}`;

const QUOTE = gql`mutation QuotePaymentBridge($instruction: UUID!, $amount: Decimal!, $request: UUID!, $direction: String!, $destination: UUID) {
  quotePaymentBridge(fundingInstructionId: $instruction, amount: $amount, requestId: $request, direction: $direction, destinationId: $destination) {
    success errors quote { internalId }
  }
}`;
const PREPARE = gql`mutation PreparePaymentBridge($quote: UUID!) {
  preparePaymentBridge(quoteId: $quote) { success errors transfer { ...PaymentBridgeFields } }
} ${FIELDS}`;
const SUBMIT = gql`mutation SubmitPaymentBridge($transfer: UUID!, $signature: String!, $nonce: String!, $authorization: BridgeAuthorizationInput) {
  submitPaymentBridge(transferId: $transfer, signature: $signature, nonce: $nonce, authorization: $authorization) {
    success errors transfer { ...PaymentBridgeFields }
  }
} ${FIELDS}`;

export function bridgeRequestId(): string {
  const raw = secureRandomBytes(16, 'a payment bridge request');
  raw[6] = (raw[6] & 15) | 64; raw[8] = (raw[8] & 63) | 128;
  const hex = bytesToHex(raw);
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** Stable across app restarts and response loss; one return bridge per journey. */
export function journeyReturnBridgeRequestId(provider: 'infinia' | 'cobre', journeyId: string): string {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(journeyId)) {
    throw new Error('Referencia de pago inválida');
  }
  const raw = keccak_256(utf8ToBytes(`confio:journey-return:v1:${provider}:${journeyId.toLowerCase()}`)).slice(0, 16);
  raw[6] = (raw[6] & 15) | 128; // UUIDv8: application-defined stable identifier.
  raw[8] = (raw[8] & 63) | 128;
  const hex = bytesToHex(raw);
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

const PERMIT = gql`query PaymentBridgePermit($id: UUID!) {
  paymentBridge(internalId: $id) { status deadline amountUnits sourceAddress permitReceiver permitNonce }
}`;

/** Polygon -> wallet: the USDC ReceiveWithAuthorization Relay executes (and
 * pays gas for). Read live, never from the screen's copy of the transfer:
 * a refused hand-off rebinds a fresh permit with a new deadline. Queried
 * alone so an older server only makes this refuse. */
async function polygonPermitDigest(t: BridgeTransfer, wallet: string): Promise<Uint8Array> {
  const { apolloClient } = await import('../apollo/client');
  const { data } = await apolloClient.query({ query: PERMIT, variables: { id: t.internalId }, fetchPolicy: 'network-only' });
  const live = data?.paymentBridge;
  const receiver = live?.permitReceiver, nonce = live?.permitNonce;
  if (!receiver || !nonce || !RELAY_RECEIVERS.has(String(receiver).toLowerCase())) throw new Error('Ruta no disponible');
  if (live.status !== 'prepared' || BigInt(live.deadline) <= BigInt(Math.floor(Date.now() / 1000) + 30)) {
    throw new Error('Revisa el estado del envío o solicita una nueva cotización');
  }
  if (String(live.sourceAddress).toLowerCase() !== wallet.toLowerCase() || live.amountUnits !== t.amountUnits) {
    throw new Error('Revisa el estado del envío o solicita una nueva cotización');
  }
  return receiveAuthorizationDigest({
    returnId: t.internalId, amount: '0', amountOut: t.amountOut,
    fromAddress: wallet, toAddress: receiver, value: live.amountUnits, validBefore: live.deadline, nonce,
  });
}

function preparationError(message: string): Error {
  // Only these explicit server rejections occur before a transfer is saved.
  // Transport errors must keep the original request for idempotent recovery.
  const refreshable = new Set([
    'Bridge quote expired; request a new quote with a new request id',
    'Bridge quote expired while pricing; try again',
    'Bridge quote expired while saving; try again',
    'Quote expired; request a fresh quote',
    'Quote expired during preparation; request a fresh quote',
    'Bridge price changed; request a fresh quote',
    'Funding exceeds the reviewed total; request a fresh quote',
    'Conversion fee changed; request a fresh quote within your total',
    'Conversion fee changed; request a new quote',
    'Wallet balance changed; request a new quote',
    'Savings balance changed; request a new quote',
    'Fee token or amount changed; request a new quote',
    'Account fees changed; request a new quote',
  ]);
  return Object.assign(new Error(message), {quoteRefreshRequired: refreshable.has(message)});
}

export async function preparePaymentBridge(instruction: string, amount: string, direction: string, request: string, destination?: string): Promise<BridgeTransfer> {
  const { apolloClient } = await import('../apollo/client');
  const quoted = await apolloClient.mutate({ mutation: QUOTE, variables: { instruction, amount, direction, request, destination } });
  const q = quoted.data?.quotePaymentBridge;
  if (!q?.success) throw preparationError(q?.errors?.[0] || 'No se pudo calcular el envío');
  const prepared = await apolloClient.mutate({ mutation: PREPARE, variables: { quote: q.quote.internalId } });
  const p = prepared.data?.preparePaymentBridge;
  if (!p?.success) throw preparationError(p?.errors?.[0] || 'No se pudo preparar el envío');
  return p.transfer;
}

/** Invoked only by the user's confirmation button. No automatic signing on app open. */
export async function authorizePaymentBridge(t: BridgeTransfer): Promise<BridgeTransfer> {
  const { apolloClient } = await import('../apollo/client');
  const { getActiveEvmWallet } = await import('./secureDeterministicWallet');
  // Polygon returns re-read their live status and deadline before signing.
  const polygon = t.sourceTokenId === 'POL:USDC';
  if (t.status !== 'prepared' || (!polygon && BigInt(t.deadline) <= BigInt(Math.floor(Date.now() / 1000) + 30))) {
    throw new Error('Revisa el estado del envío o solicita una nueva cotización');
  }
  const wallet = await getActiveEvmWallet();
  if (wallet.address.toLowerCase() !== t.sourceAddress.toLowerCase()) throw new Error('La cuenta activa cambió');
  let signature: string, nonce = '0', authorization;
  if (t.sourceTokenId === 'POL:USDC') {
    if (t.destinationAddress.toLowerCase() !== wallet.address.toLowerCase()) throw new Error('Destino inválido');
    signature = signIntentDigest(await polygonPermitDigest(t, wallet.address), wallet.privKeyHex);
  } else if (t.sourceTokenId === 'BSC:USDT') {
    const params = await fetchSponsored7702Params();
    if (!params.enabled || !params.delegateAddress) throw new Error('El envío no está disponible');
    const [n, delegated] = await Promise.all([delegateNonce(wallet.address), isDelegatedTo(wallet.address, params.delegateAddress)]);
    nonce = n.toString();
    const calls: BatchCall[] = t.calls.map(c => ({ to: c.to, valueWei: BigInt(c.value), data: c.data }));
    signature = signIntentDigest(hashBatchIntent(calls, n, BigInt(t.deadline), t.intentId, wallet.address), wallet.privKeyHex);
    if (!delegated) authorization = signSetCodeAuthorization(params.delegateAddress, await bscGetNonce(wallet.address), wallet.privKeyHex);
  } else throw new Error('Ruta no disponible');
  // On a network error, retain t.internalId and refresh server history. Never
  // create a replacement transfer or automatically sign a new nonce.
  const response = await apolloClient.mutate({ mutation: SUBMIT,
    variables: { transfer: t.internalId, signature, nonce, authorization } });
  const result = response.data?.submitPaymentBridge;
  if (!result?.success) throw new Error(result?.errors?.[0] || 'Consulta el estado antes de volver a intentar');
  return result.transfer;
}


const ONE_BRIDGE = gql`query PaymentBridge($id: UUID!) { paymentBridge(internalId: $id) { ...PaymentBridgeFields } } ${FIELDS}`;
export async function fetchPaymentBridge(id: string): Promise<BridgeTransfer> {
  const { apolloClient } = await import('../apollo/client');
  const response = await apolloClient.query({ query: ONE_BRIDGE, variables: { id }, fetchPolicy: 'network-only' });
  if (!response.data?.paymentBridge) throw new Error('Envío no encontrado');
  return response.data.paymentBridge;
}
