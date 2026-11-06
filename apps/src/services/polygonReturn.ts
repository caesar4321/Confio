/**
 * Money stranded on the person's own address on another network (a refund
 * from a top-up or a receive that could not finish) back to their balance.
 *
 * The person signs ONE USDC "ReceiveWithAuthorization": only Relay's receiver
 * contract can use it, Relay pays the network fee out of the amount, and the
 * dollars arrive in the person's balance. The app rebuilds the signed message
 * itself and refuses anything but: from = this wallet, the shown amount, and
 * Relay's known receiver.
 *
 * Run silently by hooks/usePolygonReturn on mount + foreground. Isolated
 * operations: an older server without these fields makes it a no-op, never
 * breaks a shared Home query.
 */
import { gql } from '@apollo/client';
import { keccak_256 } from '@noble/hashes/sha3';
import { bytesToHex, hexToBytes, utf8ToBytes } from '@noble/hashes/utils';
import { signIntentDigest } from './evmWallet';

export type PolygonReturnState = 'none' | 'available' | 'in_progress';

export interface PolygonReturnStatus {
  state: PolygonReturnState;
  amount: string;
  returnId: string | null;
}

export interface Permit {
  returnId: string; amount: string; amountOut: string;
  fromAddress: string; toAddress: string; value: string; validBefore: string; nonce: string;
}

const STATE = gql`query PolygonReturn { polygonReturn { state amount returnId } }`;
const PREPARE = gql`mutation PreparePolygonReturn {
  preparePolygonReturn { success error permit { returnId amount amountOut fromAddress toAddress value validBefore nonce } }
}`;
const SUBMIT = gql`mutation SubmitPolygonReturn($returnId: UUID!, $signature: String!) {
  submitPolygonReturn(returnId: $returnId, signature: $signature) { success error state { state amount returnId } }
}`;

const USDC_POLYGON = '0x3c499c542cef5e3811e1192ce70d8cc03d5c3359';
/** Relay's EIP-3009 receiver. A permit naming anyone else is never signed. */
export const RELAY_RECEIVERS = new Set(['0xccc88a9d1b4ed6b0eaba998850414b24f1c315be']);
const GENERIC = 'No pudimos devolver tu dinero. Intenta de nuevo en unos minutos.';

/** `null` = could not load (keep what was shown); older server = 'none'. */
export const fetchPolygonReturn = async (): Promise<PolygonReturnStatus | null> => {
  try {
    const { apolloClient } = await import('../apollo/client');
    const { data } = await apolloClient.query({ query: STATE, fetchPolicy: 'network-only' });
    return data?.polygonReturn ?? { state: 'none', amount: '0.00', returnId: null };
  } catch (error: any) {
    const unsupported = /Cannot query field ["']?polygonReturn/.test(String(error?.message || ''));
    return unsupported ? { state: 'none', amount: '0.00', returnId: null } : null;
  }
};

const hash = (text: string) => bytesToHex(keccak_256(utf8ToBytes(text)));
const word = (value: string) => BigInt(value).toString(16).padStart(64, '0');
const addr = (value: string) => {
  if (!/^0x[0-9a-fA-F]{40}$/.test(value)) throw new Error('Dirección inválida');
  return value.slice(2).toLowerCase().padStart(64, '0');
};

/** EIP-712 digest of USDC's ReceiveWithAuthorization on Polygon. */
export function receiveAuthorizationDigest(p: Permit): Uint8Array {
  if (!/^0x[0-9a-fA-F]{64}$/.test(p.nonce)) throw new Error('Nonce inválido');
  const domain = bytesToHex(keccak_256(hexToBytes(
    hash('EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)') +
    hash('USD Coin') + hash('2') + word('137') + addr(USDC_POLYGON),
  )));
  const message = bytesToHex(keccak_256(hexToBytes(
    hash('ReceiveWithAuthorization(address from,address to,uint256 value,uint256 validAfter,uint256 validBefore,bytes32 nonce)') +
    addr(p.fromAddress) + addr(p.toAddress) + word(p.value) + word('0') + word(p.validBefore) +
    p.nonce.slice(2).toLowerCase(),
  )));
  return keccak_256(hexToBytes('1901' + domain + message));
}

/** Price the return. Shown to the person before anything is signed. */
export const preparePolygonReturn = async (): Promise<{ permit?: Permit; error?: string }> => {
  try {
    const { apolloClient } = await import('../apollo/client');
    const { data } = await apolloClient.mutate({ mutation: PREPARE });
    const result = data?.preparePolygonReturn;
    if (!result?.success || !result.permit) return { error: result?.error || GENERIC };
    return { permit: result.permit };
  } catch {
    return { error: 'Revisa tu conexión e intenta de nuevo.' };
  }
};

/** Signs only after checking sender, receiver, window and amount itself. */
export const signAndSubmitPolygonReturn = async (permit: Permit): Promise<{ ok: boolean; error?: string }> => {
  try {
    const { getActiveEvmWallet } = await import('./secureDeterministicWallet');
    const wallet = await getActiveEvmWallet();
    const now = Math.floor(Date.now() / 1000);
    if (permit.fromAddress.toLowerCase() !== wallet.address.toLowerCase()) return { ok: false, error: GENERIC };
    if (!RELAY_RECEIVERS.has(permit.toAddress.toLowerCase())) return { ok: false, error: GENERIC };
    const validBefore = Number(permit.validBefore);
    if (!Number.isFinite(validBefore) || validBefore <= now + 30 || validBefore > now + 3600) {
      return { ok: false, error: 'La devolución expiró. Inténtalo de nuevo.' };
    }
    // The amount signed must be exactly the amount shown (USDC, 6 decimals).
    const shownUnits = BigInt(Math.round(Number(permit.amount) * 100)) * 10000n;
    if (BigInt(permit.value) < shownUnits || BigInt(permit.value) >= shownUnits + 10000n) {
      return { ok: false, error: GENERIC };
    }
    const signature = signIntentDigest(receiveAuthorizationDigest(permit), wallet.privKeyHex);
    const { apolloClient } = await import('../apollo/client');
    const { data } = await apolloClient.mutate({ mutation: SUBMIT, variables: { returnId: permit.returnId, signature } });
    const result = data?.submitPolygonReturn;
    if (!result?.success) return { ok: false, error: result?.error || GENERIC };
    return { ok: true };
  } catch {
    return { ok: false, error: 'Revisa tu conexión e intenta de nuevo.' };
  }
};
