import { gql } from '@apollo/client';
import { keccak_256 } from '@noble/hashes/sha3';
import { bytesToHex, hexToBytes, utf8ToBytes } from '@noble/hashes/utils';
import { secureRandomBytes } from '../setup/entropyGuard';
import { BatchCall, bscGetNonce, hashBatchIntent, signIntentDigest, signSetCodeAuthorization } from './evmWallet';
import { delegateNonce, fetchSponsored7702Params, isDelegatedTo } from './sponsored7702';

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

const QUOTE = gql`mutation QuotePaymentBridge($instruction: UUID!, $amount: Decimal!, $request: UUID!, $direction: String!) {
  quotePaymentBridge(fundingInstructionId: $instruction, amount: $amount, requestId: $request, direction: $direction) {
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

const hash = (text: string) => bytesToHex(keccak_256(utf8ToBytes(text)));
const word = (value: string) => BigInt(value).toString(16).padStart(64, '0');
const addr = (value: string) => {
  if (!/^0x[0-9a-fA-F]{40}$/.test(value)) throw new Error('Dirección inválida');
  return value.slice(2).toLowerCase().padStart(64, '0');
};

export function polygonAuthorizationDigest(t: BridgeTransfer): Uint8Array {
  const domain = bytesToHex(keccak_256(hexToBytes(
    hash('EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)') +
    hash('USD Coin') + hash('2') + word('137') + addr('0x3c499c542cef5e3811e1192ce70d8cc03d5c3359'),
  )));
  const message = bytesToHex(keccak_256(hexToBytes(
    hash('TransferWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)') +
    addr(t.sourceAddress) + addr(t.depositAddress) + word(t.amountUnits) + word('0') + word(t.deadline) +
    t.authorizationNonce.replace(/^0x/, ''),
  )));
  return keccak_256(hexToBytes('1901' + domain + message));
}

export async function preparePaymentBridge(instruction: string, amount: string, direction: string, request: string): Promise<BridgeTransfer> {
  const { apolloClient } = await import('../apollo/client');
  const quoted = await apolloClient.mutate({ mutation: QUOTE, variables: { instruction, amount, direction, request } });
  const q = quoted.data?.quotePaymentBridge;
  if (!q?.success) throw new Error(q?.errors?.[0] || 'No se pudo calcular el envío');
  const prepared = await apolloClient.mutate({ mutation: PREPARE, variables: { quote: q.quote.internalId } });
  const p = prepared.data?.preparePaymentBridge;
  if (!p?.success) throw new Error(p?.errors?.[0] || 'No se pudo preparar el envío');
  return p.transfer;
}

/** Invoked only by the user's confirmation button. No automatic signing on app open. */
export async function authorizePaymentBridge(t: BridgeTransfer): Promise<BridgeTransfer> {
  const { apolloClient } = await import('../apollo/client');
  const { getActiveEvmWallet } = await import('./secureDeterministicWallet');
  if (t.status !== 'prepared' || BigInt(t.deadline) <= BigInt(Math.floor(Date.now() / 1000) + 30)) {
    throw new Error('Revisa el estado del envío o solicita una nueva cotización');
  }
  const wallet = await getActiveEvmWallet();
  if (wallet.address.toLowerCase() !== t.sourceAddress.toLowerCase()) throw new Error('La cuenta activa cambió');
  let signature: string, nonce = '0', authorization;
  if (t.sourceTokenId === 'POL:USDC') {
    if (t.destinationAddress.toLowerCase() !== wallet.address.toLowerCase()) throw new Error('Destino inválido');
    signature = signIntentDigest(polygonAuthorizationDigest(t), wallet.privKeyHex);
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
