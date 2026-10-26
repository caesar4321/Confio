// Hyperliquid signing with the member's in-app key (Futuros).
//
// Byte-for-byte the official SDK (hyperliquid-python-sdk utils/signing.py),
// pinned by the vectors in __tests__/hyperliquidSigning.test.ts, which the
// server recomputes in cusd_plus/hl_signing.py to recover the signer:
//   L1 actions (order, cancel, updateLeverage, updateIsolatedMargin): an
//     EIP-712 "phantom agent" {source:'a', connectionId} under
//     Exchange/1/1337, connectionId = keccak(msgpack(action) ‖ nonce ‖ 0x00).
//   User-signed actions (sendAsset, userSetAbstraction): plain EIP-712 under
//     HyperliquidSignTransaction/1/<signatureChainId>.
//   Relay's withdrawal authorization: RelayNonceMapping/2/<chainId>.
//
// The server issues every action (cusd_plus/perps_flow.py); the app signs
// exactly that, only filling a fresh nonce where the plan leaves it null.
// No new dependency: msgpack is a small exact subset (maps, arrays, strings,
// non-negative/negative integers, booleans, null), the only shapes actions use.

import { keccak_256 } from '@noble/hashes/sha3';
import { bytesToHex, concatBytes, hexToBytes, utf8ToBytes } from '@noble/hashes/utils';
import { secp256k1 } from '@noble/curves/secp256k1.js';

export interface HlSignature {
  r: string;
  s: string;
  v: number;
}

// ── msgpack (the subset Python's msgpack.packb emits for these actions) ──

const u8 = (...bytes: number[]) => Uint8Array.from(bytes);

const uintBytes = (value: bigint, size: number): Uint8Array => {
  const out = new Uint8Array(size);
  let v = value;
  for (let i = size - 1; i >= 0; i--) {
    out[i] = Number(v & 0xffn);
    v >>= 8n;
  }
  return out;
};

const packInt = (n: number | bigint): Uint8Array => {
  const v = BigInt(n);
  if (v >= 0n) {
    if (v < 128n) return u8(Number(v));
    if (v < 256n) return concatBytes(u8(0xcc), uintBytes(v, 1));
    if (v < 65536n) return concatBytes(u8(0xcd), uintBytes(v, 2));
    if (v < 4294967296n) return concatBytes(u8(0xce), uintBytes(v, 4));
    if (v < 18446744073709551616n) return concatBytes(u8(0xcf), uintBytes(v, 8));
    throw new Error('msgpack: integer too large');
  }
  if (v >= -32n) return u8(Number(v + 256n));
  const twos = (bits: bigint) => (1n << bits) + v;
  if (v >= -128n) return concatBytes(u8(0xd0), uintBytes(twos(8n), 1));
  if (v >= -32768n) return concatBytes(u8(0xd1), uintBytes(twos(16n), 2));
  if (v >= -2147483648n) return concatBytes(u8(0xd2), uintBytes(twos(32n), 4));
  return concatBytes(u8(0xd3), uintBytes(twos(64n), 8));
};

const packStr = (s: string): Uint8Array => {
  const bytes = utf8ToBytes(s);
  const n = bytes.length;
  if (n < 32) return concatBytes(u8(0xa0 | n), bytes);
  if (n < 256) return concatBytes(u8(0xd9, n), bytes);
  if (n < 65536) return concatBytes(u8(0xda), uintBytes(BigInt(n), 2), bytes);
  return concatBytes(u8(0xdb), uintBytes(BigInt(n), 4), bytes);
};

const packLen = (n: number, fix: number, b16: number, b32: number): Uint8Array => {
  if (n < 16) return u8(fix | n);
  if (n < 65536) return concatBytes(u8(b16), uintBytes(BigInt(n), 2));
  return concatBytes(u8(b32), uintBytes(BigInt(n), 4));
};

export const msgpackEncode = (value: unknown): Uint8Array => {
  if (value === null || value === undefined) return u8(0xc0);
  if (value === true) return u8(0xc3);
  if (value === false) return u8(0xc2);
  if (typeof value === 'bigint') return packInt(value);
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) throw new Error('msgpack: only integers are supported');
    return packInt(value);
  }
  if (typeof value === 'string') return packStr(value);
  if (Array.isArray(value)) {
    return concatBytes(packLen(value.length, 0x90, 0xdc, 0xdd), ...value.map(msgpackEncode));
  }
  if (typeof value === 'object') {
    // Insertion order, as Python dicts: the server's plan fixes the order.
    const entries = Object.entries(value as Record<string, unknown>);
    return concatBytes(
      packLen(entries.length, 0x80, 0xde, 0xdf),
      ...entries.flatMap(([k, v]) => [packStr(k), msgpackEncode(v)]),
    );
  }
  throw new Error(`msgpack: unsupported ${typeof value}`);
};

// ── EIP-712 (flat structs of primitive fields; all these types need) ────

type TypedField = { name: string; type: string };

const keccak = (b: Uint8Array) => keccak_256(b);
const word = (b: Uint8Array) => {
  if (b.length > 32) throw new Error('eip712: value too long');
  const out = new Uint8Array(32);
  out.set(b, 32 - b.length);
  return out;
};

const encodeValue = (type: string, value: unknown): Uint8Array => {
  if (type === 'string') return keccak(utf8ToBytes(String(value)));
  if (type === 'bytes32') {
    const hex = String(value).replace(/^0x/, '');
    if (!/^[0-9a-fA-F]{64}$/.test(hex)) throw new Error('eip712: bad bytes32');
    return hexToBytes(hex);
  }
  if (type === 'address') {
    const hex = String(value).replace(/^0x/, '');
    if (!/^[0-9a-fA-F]{40}$/.test(hex)) throw new Error('eip712: bad address');
    return word(hexToBytes(hex));
  }
  if (type === 'bool') return word(u8(value ? 1 : 0));
  if (/^uint(8|16|32|64|128|256)$/.test(type)) {
    const v = BigInt(value as number | string | bigint);
    if (v < 0n) throw new Error('eip712: negative uint');
    return uintBytes(v, 32);
  }
  throw new Error(`eip712: unsupported type ${type}`);
};

const typeString = (name: string, fields: TypedField[]) =>
  `${name}(${fields.map((f) => `${f.type} ${f.name}`).join(',')})`;

const hashStruct = (name: string, fields: TypedField[], message: Record<string, unknown>): Uint8Array =>
  keccak(concatBytes(
    keccak(utf8ToBytes(typeString(name, fields))),
    ...fields.map((f) => {
      if (!(f.name in message)) throw new Error(`eip712: missing ${f.name}`);
      return encodeValue(f.type, message[f.name]);
    }),
  ));

const DOMAIN_FIELDS: TypedField[] = [
  { name: 'name', type: 'string' },
  { name: 'version', type: 'string' },
  { name: 'chainId', type: 'uint256' },
  { name: 'verifyingContract', type: 'address' },
];
const ZERO_ADDRESS = '0x0000000000000000000000000000000000000000';

export const typedDataDigest = (
  domain: { name: string; version: string; chainId: number | bigint },
  primaryType: string,
  fields: TypedField[],
  message: Record<string, unknown>,
): Uint8Array => keccak(concatBytes(
  u8(0x19, 0x01),
  hashStruct('EIP712Domain', DOMAIN_FIELDS, { ...domain, verifyingContract: ZERO_ADDRESS }),
  hashStruct(primaryType, fields, message),
));

export const signDigest = (digest: Uint8Array, privKeyHex: string): HlSignature => {
  const sigBytes = secp256k1.sign(digest, hexToBytes(privKeyHex.replace(/^0x/, '')), {
    prehash: false,
    lowS: true,
    format: 'recovered',
  });
  const sig = secp256k1.Signature.fromBytes(sigBytes, 'recovered');
  return {
    r: '0x' + sig.r.toString(16).padStart(64, '0'),
    s: '0x' + sig.s.toString(16).padStart(64, '0'),
    v: 27 + (sig.recovery ?? 0),
  };
};

// ── Hyperliquid actions ──────────────────────────────────────────────────

// 'noop' spends a nonce and nothing else: how the app retires a signature
// that may have been withheld (Hyperliquid's own invalidation action).
const L1_TYPES = new Set(['order', 'cancel', 'updateLeverage', 'updateIsolatedMargin', 'noop']);

const USER_SIGNED: Record<string, { primary: string; fields: TypedField[] }> = {
  sendAsset: {
    primary: 'HyperliquidTransaction:SendAsset',
    fields: [
      { name: 'hyperliquidChain', type: 'string' },
      { name: 'destination', type: 'string' },
      { name: 'sourceDex', type: 'string' },
      { name: 'destinationDex', type: 'string' },
      { name: 'token', type: 'string' },
      { name: 'amount', type: 'string' },
      { name: 'fromSubAccount', type: 'string' },
      { name: 'nonce', type: 'uint64' },
    ],
  },
  // Bridge2 withdrawal: the Salida de emergencia's own way out (no Relay).
  withdraw3: {
    primary: 'HyperliquidTransaction:Withdraw',
    fields: [
      { name: 'hyperliquidChain', type: 'string' },
      { name: 'destination', type: 'string' },
      { name: 'amount', type: 'string' },
      { name: 'time', type: 'uint64' },
    ],
  },
  userSetAbstraction: {
    primary: 'HyperliquidTransaction:UserSetAbstraction',
    fields: [
      { name: 'hyperliquidChain', type: 'string' },
      { name: 'user', type: 'address' },
      { name: 'abstraction', type: 'string' },
      { name: 'nonce', type: 'uint64' },
    ],
  },
};

/** keccak(msgpack(action) ‖ nonce(8 bytes BE) ‖ 0x00): no vault address. */
export const actionHash = (action: Record<string, unknown>, nonce: number | bigint): Uint8Array =>
  keccak(concatBytes(msgpackEncode(action), uintBytes(BigInt(nonce), 8), u8(0)));

export const isUserSigned = (action: Record<string, unknown>) =>
  typeof action.type === 'string' && action.type in USER_SIGNED;

export const actionDigest = (action: Record<string, unknown>, nonce: number | bigint): Uint8Array => {
  const type = String(action.type);
  if (L1_TYPES.has(type)) {
    return typedDataDigest(
      { name: 'Exchange', version: '1', chainId: 1337 },
      'Agent',
      [{ name: 'source', type: 'string' }, { name: 'connectionId', type: 'bytes32' }],
      { source: 'a', connectionId: '0x' + bytesToHex(actionHash(action, nonce)) },
    );
  }
  const spec = USER_SIGNED[type];
  if (!spec) throw new Error(`hyperliquid: action ${type} is not signable here`);
  const chainId = BigInt(String(action.signatureChainId));
  const own = type === 'withdraw3' ? action.time : action.nonce;
  if (BigInt(String(own)) !== BigInt(nonce)) throw new Error('hyperliquid: nonce mismatch');
  return typedDataDigest(
    { name: 'HyperliquidSignTransaction', version: '1', chainId },
    spec.primary,
    spec.fields,
    action,
  );
};

export const signAction = (
  action: Record<string, unknown>,
  nonce: number | bigint,
  privKeyHex: string,
): HlSignature => signDigest(actionDigest(action, nonce), privKeyHex);

export interface RelayNonceMapping {
  chainId: string;
  wallet: string;
  depositor: string;
  id: string;
  nonce: number;
}

export const signRelayNonceMapping = (
  value: RelayNonceMapping,
  signatureChainId: number | bigint,
  privKeyHex: string,
): HlSignature => signDigest(typedDataDigest(
  { name: 'RelayNonceMapping', version: '2', chainId: signatureChainId },
  'NonceMapping',
  [
    { name: 'chainId', type: 'string' },
    { name: 'wallet', type: 'address' },
    { name: 'depositor', type: 'address' },
    { name: 'id', type: 'bytes32' },
    { name: 'nonce', type: 'uint256' },
  ],
  value as unknown as Record<string, unknown>,
), privKeyHex);

/** Strictly increasing millisecond nonces (Hyperliquid keeps the 100
 *  highest per signer; two actions in the same millisecond must differ). */
let lastNonce = 0;
export const nextNonce = (): number => {
  const now = Date.now();
  lastNonce = now > lastNonce ? now : lastNonce + 1;
  return lastNonce;
};
