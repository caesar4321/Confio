// EVM (BSC) wallet — the savings-chain sibling of the Algorand wallet.
//
// V2 (master-secret) ONLY: derived with the same HKDF family as
// deriveWalletV2, EVM domain in the info string. Same master secret on any
// device → the same user.bsc address, no new secrets, no server custody.
// Legacy V1 (OAuth-salt) wallets deliberately have NO EVM sibling — V1
// users never could deposit on BSC, so deriving one would only register a
// confusing address; they get one when V2 migration grants a master secret.
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

/** V2 (master-secret) sibling: same HKDF family as deriveWalletV2, with the
 * EVM domain in the info string. Deterministic per master secret + account;
 * recoverable wherever the master secret is (keychain + Drive backup).
 * secp256k1 keys must be in (0, n); HKDF output is invalid with probability
 * ~2^-128 — loop with a counter-suffixed info for completeness. */
export function deriveEvmKeyFromMasterSecret(
  clientSecret: Uint8Array,
  opts: { accountType: string; accountIndex: number; businessId?: string },
): DerivedEvmWallet {
  const saltInput = opts.businessId
    ? `confio_v2_salt_${opts.accountType}_${opts.businessId}_${opts.accountIndex}`
    : `confio_v2_salt_${opts.accountType}_${opts.accountIndex}`;
  const salt = sha256(utf8ToBytes(saltInput));
  for (let counter = 0; ; counter++) {
    const info = utf8ToBytes(
      `confio|v2|evm|${saltInput}` + (counter > 0 ? `|retry${counter}` : ''),
    );
    const candidate = hkdf(sha256, clientSecret, salt, info, 32);
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
//
// TRANSPORT: the APP routes every call through the Django relay (cUSD
// parity — client signs, server injects; user IPs never touch public BSC
// nodes). Scripts/tests keep the direct fetch default. bscServerRpc.ts
// installs the app transport at first savings use.

export interface BscTransport {
  read: (method: string, params: unknown[]) => Promise<any>;
  submit: (rawTx: string) => Promise<string>; // returns tx hash
}

let transport: BscTransport | null = null;

export const setBscTransport = (t: BscTransport | null): void => {
  transport = t;
};

const directFetch = async (method: string, params: unknown[]): Promise<any> => {
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

const rpcCall = async (method: string, params: unknown[]): Promise<any> =>
  transport ? transport.read(method, params) : directFetch(method, params);

export const bscGetNonce = async (address: string): Promise<bigint> =>
  BigInt(await rpcCall('eth_getTransactionCount', [address, 'pending']));

export const bscGasPrice = async (): Promise<bigint> =>
  BigInt(await rpcCall('eth_gasPrice', []));

export const bscBnbBalance = async (address: string): Promise<bigint> =>
  BigInt(await rpcCall('eth_getBalance', [address, 'latest']));

export const bscSendRawTransaction = async (rawTx: string): Promise<string> =>
  transport ? transport.submit(rawTx) : directFetch('eth_sendRawTransaction', [rawTx]);

export const bscEthCall = async (to: string, data: string): Promise<string> =>
  rpcCall('eth_call', [{ to, data }, 'latest']);

export const bscEstimateGas = async (
  from: string, to: string, data: string, valueWei = 0n,
): Promise<bigint> =>
  BigInt(await rpcCall('eth_estimateGas', [{
    from, to, data: data || undefined,
    value: valueWei ? '0x' + valueWei.toString(16) : undefined,
  }]));

export interface BscReceipt {
  status: string; // '0x1' success, '0x0' revert
  transactionHash: string;
  blockNumber: string;
}

/** Poll for a receipt; throws on revert or timeout. ~2s cadence. */
export const bscWaitForReceipt = async (
  txHash: string, tries = 60,
): Promise<BscReceipt> => {
  for (let i = 0; i < tries; i++) {
    const rec = (await rpcCall('eth_getTransactionReceipt', [txHash])) as BscReceipt | null;
    if (rec) {
      if (rec.status !== '0x1') throw new Error(`bsc tx reverted: ${txHash}`);
      return rec;
    }
    await new Promise((r) => setTimeout(r, 2000));
  }
  throw new Error(`bsc tx timeout: ${txHash}`);
};

// ── Minimal ABI encoding (address + uint256 args only) ──────────────────
// A full ABI lib would bloat the bundle; our calls take only static
// 32-byte-word args, so hand-encoding is exact and dependency-free.

const pad32 = (hexNoPrefix: string): string => hexNoPrefix.toLowerCase().padStart(64, '0');

export const selector = (signature: string): string =>
  '0x' + bytesToHex(keccak_256(utf8ToBytes(signature))).slice(0, 8);

export const encodeAddress = (addr: string): string => pad32(addr.replace(/^0x/, ''));
export const encodeUint = (v: bigint): string => pad32(v.toString(16));

/** encodeCall('subscribeAndMint(uint256,uint256,address)', [amt, min, addr-as-uint-or-address]) */
export const encodeCall = (
  signature: string,
  args: Array<{ type: 'uint' | 'address'; value: bigint | string }>,
): string => {
  const body = args
    .map((a) => (a.type === 'address' ? encodeAddress(a.value as string) : encodeUint(a.value as bigint)))
    .join('');
  return selector(signature) + body;
};

/**
 * Sign + broadcast a state-changing call, waiting for the receipt.
 * gasLimit is estimated ×1.3 unless provided. The signer's key must control
 * `from`. Returns the mined receipt (throws on revert/timeout).
 */
export const sendCall = async (params: {
  from: string;
  privKeyHex: string;
  to: string;
  data: string;
  valueWei?: bigint;
  gasLimit?: bigint;
}): Promise<BscReceipt> => {
  const { from, privKeyHex, to, data } = params;
  const valueWei = params.valueWei ?? 0n;
  const nonce = await bscGetNonce(from);
  // Floor at 0.1 gwei; ×1.2 headroom so a small bump doesn't underprice.
  let gasPriceWei = await bscGasPrice();
  if (gasPriceWei < 100_000_000n) gasPriceWei = 100_000_000n;
  gasPriceWei = (gasPriceWei * 12n) / 10n;
  const gasLimit =
    params.gasLimit ?? ((await bscEstimateGas(from, to, data, valueWei)) * 13n) / 10n;
  const signed = signLegacyTransaction(
    { nonce, gasPriceWei, gasLimit, to, valueWei, data, chainId: BSC_NETWORK.chainId },
    privKeyHex,
  );
  const hash = await bscSendRawTransaction(signed.rawTx);
  return bscWaitForReceipt(hash);
};
