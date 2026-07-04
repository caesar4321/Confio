// EVM (BSC) wallet — the savings-chain sibling of the Algorand wallet.
//
// Same non-custodial derivation pipeline as deriveDeterministicAlgorandKey
// (secureDeterministicWallet.ts): identical IKM (OAuth clientSalt) and HKDF
// extract salt (derivationPepper); ONLY the info string differs, using the
// pre-planned domain 'confio/evm/v1' (derivationSpec.ts). Same inputs on any
// device → the same user.bsc address, no new secrets, no server custody.
//
// Signing: BSC legacy type-0 transactions with EIP-155 replay protection
// (universally accepted on BNB chain). Pure functions — no network in the
// derive/sign path; thin JSON-RPC helpers below for nonce/gas/broadcast.
// Validated byte-for-byte against ethers v6:
//   apps/scripts/validate-evm-signer.mts
//
// Dependencies: @noble/curves (secp256k1) + the already-installed
// @noble/hashes — pure JS, Metro-safe, no polyfills.

import { hkdf } from '@noble/hashes/hkdf';
import { sha256 } from '@noble/hashes/sha256';
import { keccak_256 } from '@noble/hashes/sha3';
import { utf8ToBytes, bytesToHex, hexToBytes, concatBytes } from '@noble/hashes/utils';
import { secp256k1 } from '@noble/curves/secp256k1.js';
import { CONFIO_DERIVATION_SPEC } from './derivationSpec';
import type { DeriveWalletOptions } from './secureDeterministicWallet';

// ── Network config ──────────────────────────────────────────────────────
// TODO(cusd+): serve from backend config (mirrors how Algorand network
// selection works); testnet = chainId 97, https://data-seed-prebsc-1-s1.bnbchain.org:8545
export const BSC_NETWORK = {
  chainId: 56n,
  rpcUrl: 'https://bsc-dataseed.bnbchain.org',
};

export interface DerivedEvmWallet {
  address: string; // EIP-55 checksummed
  privKeyHex: string; // 0x-less hex, 32 bytes
}

// ── Derivation ──────────────────────────────────────────────────────────

export function deriveDeterministicEvmKey(opts: DeriveWalletOptions): DerivedEvmWallet {
  const { clientSalt, derivationPepper, provider, accountType, accountIndex, businessId } = opts;

  // Byte-identical IKM/extract construction to the Algorand path — the
  // domain separation lives entirely in the info string.
  const ikm = sha256(utf8ToBytes(`${CONFIO_DERIVATION_SPEC.root}|${clientSalt}`));
  const extractSalt = sha256(
    utf8ToBytes(`${CONFIO_DERIVATION_SPEC.extract}|${derivationPepper}`),
  );

  // secp256k1 keys must be in (0, n); HKDF output is invalid with
  // probability ~2^-128. Loop with a counter-suffixed info for completeness.
  for (let counter = 0; ; counter++) {
    const info = utf8ToBytes(
      `${CONFIO_DERIVATION_SPEC.evmInfoPrefix}|${provider}|${accountType}|${accountIndex}|${businessId ?? ''}` +
        (counter > 0 ? `|retry${counter}` : ''),
    );
    const candidate = hkdf(sha256, ikm, extractSalt, info, 32);
    if (isValidPrivKey(candidate)) {
      return {
        address: privKeyToAddress(candidate),
        privKeyHex: bytesToHex(candidate),
      };
    }
  }
}

const SECP256K1_N = BigInt(
  '0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141',
);

const isValidPrivKey = (k: Uint8Array): boolean => {
  const v = BigInt('0x' + bytesToHex(k));
  return v > 0n && v < SECP256K1_N;
};

export const privKeyToAddress = (priv: Uint8Array): string => {
  const pub = secp256k1.getPublicKey(priv, false); // uncompressed, 65 bytes
  const hash = keccak_256(pub.slice(1));
  return toChecksumAddress(bytesToHex(hash.slice(12)));
};

/** EIP-55 mixed-case checksum */
export const toChecksumAddress = (addrHexNoPrefix: string): string => {
  const lower = addrHexNoPrefix.toLowerCase();
  const hash = bytesToHex(keccak_256(utf8ToBytes(lower)));
  let out = '0x';
  for (let i = 0; i < lower.length; i++) {
    out += parseInt(hash[i], 16) >= 8 ? lower[i].toUpperCase() : lower[i];
  }
  return out;
};

// ── Minimal RLP (all we need for legacy txs) ────────────────────────────

type RlpInput = Uint8Array | RlpInput[];

const rlpEncodeLength = (len: number, offset: number): Uint8Array => {
  if (len < 56) return Uint8Array.from([len + offset]);
  const lenBytes = bigintToMinimalBytes(BigInt(len));
  return concatBytes(Uint8Array.from([lenBytes.length + offset + 55]), lenBytes);
};

export const rlpEncode = (input: RlpInput): Uint8Array => {
  if (input instanceof Uint8Array) {
    if (input.length === 1 && input[0] < 0x80) return input;
    return concatBytes(rlpEncodeLength(input.length, 0x80), input);
  }
  const body = concatBytes(...input.map(rlpEncode));
  return concatBytes(rlpEncodeLength(body.length, 0xc0), body);
};

export const bigintToMinimalBytes = (v: bigint): Uint8Array => {
  if (v < 0n) throw new Error('negative');
  if (v === 0n) return new Uint8Array(0); // RLP integer zero = empty string
  let hex = v.toString(16);
  if (hex.length % 2) hex = '0' + hex;
  return hexToBytes(hex);
};

const hexToBytes0x = (h: string): Uint8Array =>
  hexToBytes(h.startsWith('0x') ? h.slice(2) : h);

// ── Legacy (type-0) transaction signing with EIP-155 ────────────────────

export interface LegacyTxParams {
  nonce: bigint;
  gasPriceWei: bigint;
  gasLimit: bigint;
  to: string; // 0x…
  valueWei: bigint;
  data: string; // 0x… or ''
  chainId?: bigint; // defaults to BSC mainnet
}

export interface SignedTx {
  rawTx: string; // 0x… ready for eth_sendRawTransaction
  txHash: string; // keccak of the signed payload
}

export function signLegacyTransaction(tx: LegacyTxParams, privKeyHex: string): SignedTx {
  const chainId = tx.chainId ?? BSC_NETWORK.chainId;
  const base: RlpInput[] = [
    bigintToMinimalBytes(tx.nonce),
    bigintToMinimalBytes(tx.gasPriceWei),
    bigintToMinimalBytes(tx.gasLimit),
    hexToBytes0x(tx.to),
    bigintToMinimalBytes(tx.valueWei),
    tx.data ? hexToBytes0x(tx.data) : new Uint8Array(0),
  ];

  // EIP-155 preimage: [..., chainId, 0, 0]
  const preimage = rlpEncode([
    ...base,
    bigintToMinimalBytes(chainId),
    new Uint8Array(0),
    new Uint8Array(0),
  ]);
  const msgHash = keccak_256(preimage);

  const priv = hexToBytes(privKeyHex);
  // prehash MUST be false: noble v2 would otherwise sha256 our keccak hash.
  // lowS is mandatory for EVM validity; 'recovered' = [recid] || r || s.
  const sigBytes = secp256k1.sign(msgHash, priv, {
    prehash: false,
    lowS: true,
    format: 'recovered',
  });
  const sig = secp256k1.Signature.fromBytes(sigBytes, 'recovered');
  const v = chainId * 2n + 35n + BigInt(sig.recovery ?? 0);

  const signed = rlpEncode([
    ...base,
    bigintToMinimalBytes(v),
    bigintToMinimalBytes(sig.r),
    bigintToMinimalBytes(sig.s),
  ]);
  return {
    rawTx: '0x' + bytesToHex(signed),
    txHash: '0x' + bytesToHex(keccak_256(signed)),
  };
}

// ── Thin JSON-RPC helpers (nonce / gas / broadcast / balances) ──────────

const rpcCall = async (method: string, params: unknown[]): Promise<any> => {
  const res = await fetch(BSC_NETWORK.rpcUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
  });
  if (!res.ok) throw new Error(`bsc rpc http ${res.status}`);
  const json = await res.json();
  if (json.error) throw new Error(`bsc rpc: ${json.error.message}`);
  return json.result;
};

export const bscGetNonce = async (address: string): Promise<bigint> =>
  BigInt(await rpcCall('eth_getTransactionCount', [address, 'pending']));

export const bscGasPrice = async (): Promise<bigint> =>
  BigInt(await rpcCall('eth_gasPrice', []));

export const bscBnbBalance = async (address: string): Promise<bigint> =>
  BigInt(await rpcCall('eth_getBalance', [address, 'latest']));

export const bscSendRawTransaction = async (rawTx: string): Promise<string> =>
  rpcCall('eth_sendRawTransaction', [rawTx]);
