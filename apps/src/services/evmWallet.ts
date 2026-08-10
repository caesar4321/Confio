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

export interface BscLog {
  address: string;
  topics: string[];
  data: string;
}

export interface BscReceipt {
  status: string; // '0x1' success, '0x0' revert
  transactionHash: string;
  blockNumber: string;
  logs?: BscLog[];
}

/** keccak256("BatchExecuted(uint256,uint256)") — ConfioBatchDelegate emits
 *  it, as the user's own EOA, with the consumed intent nonce as topic 1. */
export const BATCH_EXECUTED_TOPIC =
  '0x' + bytesToHex(keccak_256(utf8ToBytes('BatchExecuted(uint256,uint256)')));

/**
 * Did THIS receipt actually execute our batch?
 *
 * A 7702 silent no-op mines with status 0x1 while executing nothing (the
 * authorization's account nonce raced, so the EOA stayed codeless and the
 * call hit an address with no code). The proof of real execution is the
 * exact BatchExecuted(nonce) from the user's own address — which the
 * receipt we already hold carries. Reading it here replaces a second
 * `nonces()` round trip that asked the chain the same question.
 *
 * ABSENCE OF THE LOG IS NOT PROOF OF NON-EXECUTION (Codex audit 2026-08-02
 * [P1]). 'unknown' exists because the alternative is the double-send bug:
 * a batch that DID execute, reported as failed, retried by the user, and
 * settled twice. Only an affirmative `logs: []` earns 'noop' — that is the
 * ONLY shape a real no-op can have, since a delegation that never applied
 * left a codeless EOA that could not emit anything.
 *
 * A non-empty log list without our event is ALSO 'unknown', not 'noop':
 * ConfioBatchDelegate emits BatchExecuted LAST, after the call loop, so any
 * response that drops trailing logs drops exactly this event while keeping
 * the inner transfers — indistinguishable from "something else executed".
 *
 * Comparisons are case-insensitive: hex casing is not guaranteed across
 * nodes, and a case mismatch reads as "did not execute" — the dangerous way
 * to be wrong.
 */
export type BatchExecutionVerdict = 'executed' | 'noop' | 'unknown';

export const receiptExecutedBatch = (
  receipt: BscReceipt, eoa: string, execNonce: bigint,
): BatchExecutionVerdict => {
  const logs = receipt.logs;
  if (!logs) return 'unknown'; // not shown the evidence ≠ evidence of absence
  if (logs.length === 0) return 'noop'; // affirmatively zero logs = real no-op
  const want = '0x' + execNonce.toString(16).padStart(64, '0');
  const from = eoa.toLowerCase();
  const hit = logs.some(
    (lg) =>
      lg
      && (lg.address || '').toLowerCase() === from
      && (lg.topics || []).length >= 2
      && (lg.topics[0] || '').toLowerCase() === BATCH_EXECUTED_TOPIC
      && (lg.topics[1] || '').toLowerCase() === want,
  );
  return hit ? 'executed' : 'unknown';
};

/**
 * The transaction IS on the network but we stopped waiting for its receipt.
 *
 * This is NOT a failure — the outcome is unknown, and it can still mine after
 * we give up. Callers must never treat it as "nothing happened": retrying, or
 * falling back to a second transfer, is how the same payment gets made twice.
 * It carries the hash so the caller can reconcile instead of re-sending.
 */
export class BscReceiptTimeoutError extends Error {
  readonly txHash: string;
  /** True once the tx has been handed to the network — outcome unknown. */
  readonly broadcast = true;
  constructor(txHash: string) {
    super(`bsc tx timeout: ${txHash}`);
    this.name = 'BscReceiptTimeoutError';
    this.txHash = txHash;
  }
}

/** A revert is DEFINITIVE: it mined and changed nothing. Safe to retry. */
export class BscRevertedError extends Error {
  readonly txHash: string;
  constructor(txHash: string) {
    super(`bsc tx reverted: ${txHash}`);
    this.name = 'BscRevertedError';
    this.txHash = txHash;
  }
}

/** True when a failure leaves the outcome UNKNOWN (money may still move). */
export const isOutcomeUnknown = (e: unknown): boolean =>
  e instanceof BscReceiptTimeoutError
  || Boolean((e as any)?.broadcast)
  // Defensive: an older bundle or a re-thrown copy may only carry the text.
  || /bsc tx timeout/i.test(String((e as any)?.message || ''));

/**
 * Poll for a receipt; throws on revert or timeout.
 *
 * Cadence is tight first, then backs off. BSC mines sub-second, so the old
 * flat 2s quantum spent most of its wall clock waiting on a transaction
 * that had ALREADY landed — the chain was never the slow part. Early polls
 * are cheap (the relay allows 120 reads/min/user and a send spends ~5), and
 * the back-off keeps a genuinely stuck tx from burning that budget.
 *
 * The give-up budget stays ~120s, now expressed as time rather than a
 * count, so changing the cadence can't silently change the deadline.
 *
 * Each individual read is capped too (Codex audit 2026-08-02 [P1]). The
 * budget is only checked BETWEEN polls, so without a per-read cap one hung
 * relay request extends the total without limit — and the screen's 180s
 * watchdog would then declare failure while the transaction is still live,
 * which is the retry path that double-sends. The relay can legitimately
 * take a while (it rotates endpoints server-side), so the cap is generous;
 * it exists to bound the tail, not to tighten the common case.
 */
const RECEIPT_READ_CAP_MS = 10_000;

export const bscWaitForReceipt = async (
  txHash: string, budgetMs = 120_000,
): Promise<BscReceipt> => {
  // 300,500,800,1200 then 2000 steady.
  const delayFor = (i: number): number =>
    [300, 500, 800, 1200][i] ?? 2000;
  const deadline = Date.now() + budgetMs;
  for (let i = 0; ; i++) {
    // Abandon a read that outlives the cap. This does NOT cancel the request
    // (there is nothing to cancel a GraphQL read with here) — it stops us
    // waiting on it, which is all the deadline needs.
    const rec = (await Promise.race([
      rpcCall('eth_getTransactionReceipt', [txHash]),
      new Promise((resolve) =>
        setTimeout(() => resolve(null), Math.min(RECEIPT_READ_CAP_MS, Math.max(deadline - Date.now(), 1)))),
    ])) as BscReceipt | null;
    if (rec) {
      if (rec.status !== '0x1') throw new BscRevertedError(txHash);
      return rec;
    }
    const delay = delayFor(i);
    if (Date.now() + delay >= deadline) break;
    await new Promise((r) => setTimeout(r, delay));
  }
  throw new BscReceiptTimeoutError(txHash);
};

export const bscGetCode = async (address: string): Promise<string> =>
  rpcCall('eth_getCode', [address, 'latest']);

// ── EIP-7702 authorization signing ──────────────────────────────────────
// The one-time tuple designating ConfioBatchDelegate at the user's own EOA:
// sign keccak(0x05 ‖ rlp([chainId, delegate, accountNonce])). The sponsor
// carries it in a type-4 tx; the account keeps its key and address.

export interface SetCodeAuthorization {
  chainId: number;
  address: string; // the delegate contract
  nonce: string; // the EOA's ACCOUNT nonce at signing (decimal string)
  yParity: number;
  r: string; // 0x…
  s: string; // 0x…
}

/**
 * Delegates this app will designate at the user's EOA — pinned in the BUILD,
 * never taken from the server.
 *
 * Signing an EIP-7702 authorization is the most dangerous thing this wallet
 * does: it installs code that executes AS the user's address. The tuple has
 * NO expiry (chainId, address, nonce only), so a signature handed to a
 * compromised server can be banked and broadcast whenever that account nonce
 * comes up. Every flow here took the address from a server response, so one
 * bad response reached the whole wallet, not one transaction.
 * (Codex audit 2026-08-02, P1.)
 *
 * ROTATION — order matters, or you brick sponsorship for shipped builds:
 *   1. ship a release that lists BOTH the old and new delegate,
 *   2. only then point the server at the new one,
 *   3. drop the old entry in a later release.
 * Do NOT keep a superseded delegate here for convenience: an attacker who
 * controls a response could otherwise force a downgrade to an older, weaker
 * delegate (e.g. one without the intentId replay binding).
 */
export const TRUSTED_BATCH_DELEGATES: readonly string[] = [
  // ConfioBatchDelegate (intentId-binding build), BSC mainnet
  '0xc06bd197b34a587026615c6aed21301f5e99bc00',
];

export const isTrustedDelegate = (address: string): boolean =>
  TRUSTED_BATCH_DELEGATES.includes((address || '').toLowerCase());

export function signSetCodeAuthorization(
  delegateAddress: string,
  accountNonce: bigint,
  privKeyHex: string,
  chainId: bigint = BSC_NETWORK.chainId,
): SetCodeAuthorization {
  // Enforced HERE, at the one function that can produce an authorization, so
  // a new sponsored flow cannot forget the check.
  if (!isTrustedDelegate(delegateAddress)) {
    throw new Error(`untrusted_delegate:${delegateAddress}`);
  }
  const payload = rlpEncode([
    bigintToMinimalBytes(chainId),
    hexToBytes0x(delegateAddress), // raw 20 bytes, NOT minimal-int
    bigintToMinimalBytes(accountNonce),
  ]);
  const digest = keccak_256(concatBytes(Uint8Array.from([0x05]), payload));
  const sigBytes = secp256k1.sign(digest, hexToBytes(privKeyHex), {
    prehash: false,
    lowS: true,
    format: 'recovered',
  });
  const sig = secp256k1.Signature.fromBytes(sigBytes, 'recovered');
  return {
    chainId: Number(chainId),
    address: delegateAddress,
    nonce: accountNonce.toString(),
    yParity: sig.recovery ?? 0,
    r: '0x' + sig.r.toString(16),
    s: '0x' + sig.s.toString(16),
  };
}

// ── EIP-712 batch-intent signing (ConfioBatchDelegate.execute) ──────────
// Canonical strings shared with ConfioBatchDelegate.sol and
// cusd_plus/sponsor_7702.py. The three-way parity anchor lives in the forge
// test test_sharedEip712Vector / Django test_shared_eip712_vector /
// validate-evm-signer.mts. Never change one alone.

export interface BatchCall {
  to: string;
  valueWei: bigint;
  data: string; // 0x…
}

const typehash = (s: string): string => bytesToHex(keccak_256(utf8ToBytes(s)));

const DOMAIN_TYPEHASH = typehash(
  'EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)',
);
const CALL_TYPEHASH = typehash('Call(address to,uint256 value,bytes data)');
const EXECUTE_TYPEHASH = typehash(
  'Execute(Call[] calls,uint256 nonce,uint256 deadline,bytes32 intentId)Call(address to,uint256 value,bytes data)',
);
const NAME_HASH = bytesToHex(keccak_256(utf8ToBytes('ConfioBatchDelegate')));
const VERSION_HASH = bytesToHex(keccak_256(utf8ToBytes('1')));

const keccakHex = (hexNoPrefix: string): string =>
  bytesToHex(keccak_256(hexNoPrefix ? hexToBytes(hexNoPrefix) : new Uint8Array(0)));

/** EIP-712 digest the EOA signs for execute(calls, nonce, deadline, intentId) —
 * domain binds chainId + the USER'S OWN ADDRESS (verifyingContract). intentId
 * (bytes32, 0x-prefixed) binds the signature to a specific server-defined
 * intent (migration audit 2026-07-31): domain flows receive it from prepare;
 * the savings rail derives it (see deriveIntentId). */
export function hashBatchIntent(
  calls: BatchCall[],
  nonce: bigint,
  deadline: bigint,
  intentId: string,
  userAddress: string,
  chainId: bigint = BSC_NETWORK.chainId,
): Uint8Array {
  const callHashes = calls
    .map((c) =>
      keccakHex(
        CALL_TYPEHASH +
          encodeAddress(c.to) +
          encodeUint(c.valueWei) +
          keccakHex(c.data.replace(/^0x/, '')),
      ),
    )
    .join('');
  const domainSeparator = keccakHex(
    DOMAIN_TYPEHASH + NAME_HASH + VERSION_HASH + encodeUint(chainId) + encodeAddress(userAddress),
  );
  const structHash = keccakHex(
    EXECUTE_TYPEHASH +
      keccakHex(callHashes) +
      encodeUint(nonce) +
      encodeUint(deadline) +
      intentId.replace(/^0x/, '').padStart(64, '0'),
  );
  return keccak_256(hexToBytes('1901' + domainSeparator + structHash));
}

/** The savings rail (generic sponsorBscBatch) has no prepare step, so the
 * client derives intentId the same way the server does: kind from the
 * selectors (redeem if any redeemToUsdt call, else subscribe), keccak(kind:).
 * Domain flows (send/pay/presale/invite/payroll) ignore this and pass the
 * intentId the server returned. */
const SEL_REDEEM_TO_USDT = 'f4794519'; // redeemToUsdt(uint256,uint256,address)
export function deriveIntentId(calls: BatchCall[]): string {
  const selectors = new Set(calls.map((c) => c.data.replace(/^0x/, '').slice(0, 8)));
  const stockBuy = selector(
    'buyWithSavings((uint256,uint256,bytes32,address,uint256,uint256,uint256,uint8,bytes32),bytes,uint256,uint256,uint256,uint256)',
  ).slice(2);
  const stockSell = selector(
    'sellToSavings((uint256,uint256,bytes32,address,uint256,uint256,uint256,uint8,bytes32),bytes,uint256,uint256,uint256)',
  ).slice(2);
  const kind = selectors.has(stockBuy)
    ? 'stock_buy'
    : selectors.has(stockSell)
      ? 'stock_sell'
      : selectors.has(SEL_REDEEM_TO_USDT)
        ? 'redeem'
        : 'subscribe';
  return '0x' + bytesToHex(keccak_256(utf8ToBytes(`${kind}:`)));
}

/** 65-byte r‖s‖v signature (v = 27/28, what OZ ECDSA.recover expects). */
export function signIntentDigest(digest: Uint8Array, privKeyHex: string): string {
  const sigBytes = secp256k1.sign(digest, hexToBytes(privKeyHex), {
    prehash: false,
    lowS: true,
    format: 'recovered',
  });
  const sig = secp256k1.Signature.fromBytes(sigBytes, 'recovered');
  const v = 27 + (sig.recovery ?? 0);
  return (
    '0x' +
    sig.r.toString(16).padStart(64, '0') +
    sig.s.toString(16).padStart(64, '0') +
    v.toString(16).padStart(2, '0')
  );
}

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
