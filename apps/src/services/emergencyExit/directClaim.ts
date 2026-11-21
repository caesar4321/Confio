// Cuenta inteligente: the beneficiary's direct on-chain path (spec 6.7).
//
// A beneficiary must be able to finish a claim with Confío's server
// unreachable. This module sends the three calls that path needs as PLAIN,
// SELF-PAID transactions from the beneficiary's own personal wallet (EOA) to
// the account contract:
//
//   initiateClaim()                       ConfioSmartAccount.sol:530
//   executeClaim()                        ConfioSmartAccount.sol:543
//   withdraw(address,uint256,address)     ConfioSmartAccount.sol:383 (inherited
//                                         only; `to` = the new owner's wallet)
//
// None of the three has a sponsor gate (the contract says so at 530 and
// carries none on the other two), so a type-2 transaction from the EOA works.
// If the EOA is 7702-delegated (ConfioBatchDelegate) nothing changes: the
// sender's code never runs when it SENDS a transaction, and the delegate's
// receive()/fallback() keep BNB transfers to the address working.
//
// Deliberately NOT gatedTx.sendGatedCall: that wraps every leg in
// execute([assertSilent(), leg]) and only lands after Confío's heartbeat has
// gone silent. A claim must work in an ordinary outage, and while Confío is
// alive too, so there is no heartbeat read anywhere in this file.
//
// Transport: the bundled public BSC RPCs (bscRpcs.ts) with failover, through
// a local client that keeps a revert's data (the shared helpers drop it).
// It never installs a global transport, so normal app flows are untouched.
// Pure TypeScript (no react-native imports): the RPC is injectable for tests.

import { keccak_256 } from '@noble/hashes/sha3';
import { bytesToHex, concatBytes, hexToBytes } from '@noble/hashes/utils';
import { secp256k1 } from '@noble/curves/secp256k1.js';
import {
  BSC_NETWORK,
  bigintToMinimalBytes,
  encodeAddress,
  encodeUint,
  rlpEncode,
  selector,
  type DerivedEvmWallet,
  type SignedTx,
} from '../evmWallet';
import { CHAIN_ENDPOINTS } from './bscRpcs';
import {
  BUNDLED_CONFIO_ADDRESS,
  BUNDLED_CUSD_ADDRESS,
  BUNDLED_VAULT_ADDRESS,
  decodeStockBalanceMulticall,
  encodeStockBalanceMulticall,
  exitTokenUniverse,
} from './bscExit';

// ---------------------------------------------------------------- calls

export const DIRECT_SIGNATURES = {
  initiateClaim: 'initiateClaim()',
  executeClaim: 'executeClaim()',
  withdraw: 'withdraw(address,uint256,address)',
} as const;

export type DirectCall =
  | { kind: 'initiateClaim' }
  | { kind: 'executeClaim' }
  | { kind: 'withdraw'; token: string; amount: bigint; to: string };

const ADDRESS = /^0x[0-9a-fA-F]{40}$/;
export const isAccountAddress = (a: unknown): a is string =>
  typeof a === 'string' && ADDRESS.test(a) && BigInt(a) !== 0n;

/** Exact calldata for one direct call. Throws on a malformed withdraw. */
export function directCalldata(call: DirectCall): string {
  if (call.kind === 'withdraw') {
    if (!isAccountAddress(call.token) || !isAccountAddress(call.to) || call.amount <= 0n) {
      throw new Error('bad_withdraw');
    }
    return selector(DIRECT_SIGNATURES.withdraw)
      + encodeAddress(call.token) + encodeUint(call.amount) + encodeAddress(call.to);
  }
  return selector(DIRECT_SIGNATURES[call.kind]);
}

// The contract's custom errors that these three calls (and the token
// transfer under withdraw) can raise, by 4-byte selector.
const ERROR_NAMES = [
  'NotBeneficiary', 'BadState', 'ClaimAlreadyPending', 'Cooldown', 'TooEarly',
  'NotOwner', 'NotInherited', 'BadDestination', 'IsInherited', 'BadToken', 'BadAmount',
] as const;
export type DirectRevertName = (typeof ERROR_NAMES)[number];

export const DIRECT_REVERTS: Record<string, DirectRevertName> = Object.fromEntries(
  ERROR_NAMES.map((name) => [selector(`${name}()`), name]),
) as Record<string, DirectRevertName>;

export function decodeRevert(data: string | null | undefined): DirectRevertName | null {
  if (typeof data !== 'string' || data.length < 10) {
    return null;
  }
  return DIRECT_REVERTS[data.slice(0, 10).toLowerCase()] ?? null;
}

// ------------------------------------------------------------------ RPC

export type RpcFn = (method: string, params: unknown[]) => Promise<any>;

/** The node ran the call and it reverted. Definitive: no failover. */
export class DirectRevertError extends Error {
  readonly data: string | null;
  constructor(message: string, data: string | null) {
    super(message);
    this.name = 'DirectRevertError';
    this.data = data;
  }
}

const RPC_TIMEOUT_MS = 10_000;

const revertData = (error: any): string | null => {
  const d = error?.data;
  if (typeof d === 'string' && d.startsWith('0x')) {
    return d;
  }
  if (typeof d?.data === 'string' && d.data.startsWith('0x')) {
    return d.data;
  }
  return null;
};

const rpcOnce = async (url: string, method: string, params: unknown[]): Promise<any> => {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error('bsc rpc timeout')), RPC_TIMEOUT_MS);
  });
  try {
    const res: any = await Promise.race([
      fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
      }),
      timeout,
    ]);
    if (!res.ok) {
      throw new Error(`bsc rpc http ${res.status}`);
    }
    const json = await res.json();
    if (json.error) {
      const message = String(json.error.message || 'rpc error');
      if (json.error.code === 3 || /revert/i.test(message)) {
        throw new DirectRevertError(message, revertData(json.error));
      }
      throw new Error(`bsc rpc: ${message}`);
    }
    return json.result;
  } finally {
    if (timer) {
      clearTimeout(timer);
    }
  }
};

/** Public BSC RPCs in order, failing over on transport errors only. */
export const publicDirectRpc: RpcFn = async (method, params) => {
  let lastErr: unknown;
  for (const url of CHAIN_ENDPOINTS.BSC_RPCS) {
    try {
      return await rpcOnce(url, method, params);
    } catch (e) {
      if (e instanceof DirectRevertError) {
        throw e;
      }
      lastErr = e;
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error('all BSC RPCs failed');
};

// ------------------------------------------------------- type-2 signing

export interface Eip1559TxParams {
  nonce: bigint;
  maxPriorityFeePerGas: bigint;
  maxFeePerGas: bigint;
  gasLimit: bigint;
  to: string;
  valueWei: bigint;
  data: string;
  chainId?: bigint;
}

const hex0x = (h: string): Uint8Array => hexToBytes(h.startsWith('0x') ? h.slice(2) : h);

/** EIP-1559 (type-2) signing, empty access list. Parity-tested against eth_account. */
export function signEip1559Transaction(tx: Eip1559TxParams, privKeyHex: string): SignedTx {
  const chainId = tx.chainId ?? BSC_NETWORK.chainId;
  const fields: Array<Parameters<typeof rlpEncode>[0]> = [
    bigintToMinimalBytes(chainId),
    bigintToMinimalBytes(tx.nonce),
    bigintToMinimalBytes(tx.maxPriorityFeePerGas),
    bigintToMinimalBytes(tx.maxFeePerGas),
    bigintToMinimalBytes(tx.gasLimit),
    hex0x(tx.to),
    bigintToMinimalBytes(tx.valueWei),
    tx.data && tx.data !== '0x' ? hex0x(tx.data) : new Uint8Array(0),
    [], // accessList
  ];
  const digest = keccak_256(concatBytes(Uint8Array.from([0x02]), rlpEncode(fields)));
  const sigBytes = secp256k1.sign(digest, hexToBytes(privKeyHex), {
    prehash: false,
    lowS: true,
    format: 'recovered',
  });
  const sig = secp256k1.Signature.fromBytes(sigBytes, 'recovered');
  const signed = concatBytes(
    Uint8Array.from([0x02]),
    rlpEncode([
      ...fields,
      bigintToMinimalBytes(BigInt(sig.recovery ?? 0)),
      bigintToMinimalBytes(sig.r),
      bigintToMinimalBytes(sig.s),
    ]),
  );
  return { rawTx: '0x' + bytesToHex(signed), txHash: '0x' + bytesToHex(keccak_256(signed)) };
}

// ------------------------------------------------------- account state

export interface DirectAccountState {
  owner: string;
  beneficiary: string;
  inherited: boolean;
  /** 0 Unsubscribed, 1 Active, 2 CancelPending, 3 Expired, 4 Inherited. */
  status: number;
  /** Unix seconds; 0 = none. */
  claimStartedAt: number;
  claimExecutableAt: number;
  claimCooldownUntil: number;
}

const word = (ret: string): bigint => BigInt(ret && ret !== '0x' ? ret : 0);
const wordAddress = (ret: string): string => '0x' + (ret || '').replace(/^0x/, '').padStart(64, '0').slice(-40).toLowerCase();

/** The account's claim state, read from the chain (no Confío server). */
export async function readDirectAccountState(account: string, rpc: RpcFn = publicDirectRpc): Promise<DirectAccountState> {
  if (!isAccountAddress(account)) {
    throw new Error('bad_account');
  }
  const call = (sig: string) => rpc('eth_call', [{ to: account, data: selector(sig) }, 'latest']) as Promise<string>;
  const [code, owner, beneficiary, inherited, status, started, executable, cooldown] = await Promise.all([
    rpc('eth_getCode', [account, 'latest']) as Promise<string>,
    call('owner()'),
    call('beneficiary()'),
    call('inherited()'),
    call('status()'),
    call('claimStartedAt()'),
    call('claimExecutableAt()'),
    call('claimCooldownUntil()'),
  ]);
  if (!code || code === '0x' || !owner || owner === '0x') {
    throw new Error('not_a_smart_account');
  }
  return {
    owner: wordAddress(owner),
    beneficiary: wordAddress(beneficiary),
    inherited: word(inherited) !== 0n,
    status: Number(word(status)),
    claimStartedAt: Number(word(started)),
    claimExecutableAt: Number(word(executable)),
    claimCooldownUntil: Number(word(cooldown)),
  };
}

export type DirectStep =
  | { kind: 'initiate' }
  | { kind: 'wait'; executableAt: number }
  | { kind: 'execute' }
  | { kind: 'withdraw' }
  | { kind: 'cooldown'; until: number }
  | { kind: 'not_beneficiary' }
  | { kind: 'inactive' };

/** What the beneficiary can do next, from the chain's own state. Mirrors the
 *  contract's checks so a doomed transaction is never offered. */
export function nextDirectStep(state: DirectAccountState, me: string, nowSec: number): DirectStep {
  const self = me.toLowerCase();
  if (state.inherited) {
    return state.owner === self ? { kind: 'withdraw' } : { kind: 'not_beneficiary' };
  }
  if (state.beneficiary !== self) {
    return { kind: 'not_beneficiary' };
  }
  // _active(): a plan, not inherited, not expired (status 1 or 2).
  if (state.status !== 1 && state.status !== 2) {
    return { kind: 'inactive' };
  }
  if (state.claimStartedAt === 0) {
    return nowSec < state.claimCooldownUntil ? { kind: 'cooldown', until: state.claimCooldownUntil } : { kind: 'initiate' };
  }
  return nowSec >= state.claimExecutableAt ? { kind: 'execute' } : { kind: 'wait', executableAt: state.claimExecutableAt };
}

// --------------------------------------------------- holdings (withdraw)

const USDT_BSC = '0x55d398326f99059fF775485246999027B3197955';
const MULTICALL3 = '0xcA11bde05977b3631167028862bE2a173976CA11';
const BALANCE_CHUNK = 250;

export interface DirectHolding {
  address: string;
  /** What the person sees: a product name, never a token unit. */
  label: string;
  balance: bigint;
}

/** Every token the account could hold that this build knows of, plus the
 *  addresses this device remembered from the server, with display names. */
export function directTokenUniverse(extra: readonly string[] = []): Array<{ address: string; label: string }> {
  const out = new Map<string, { address: string; label: string }>();
  const add = (address: string, label: string) => {
    const key = (address || '').toLowerCase();
    if (isAccountAddress(key) && !out.has(key)) {
      out.set(key, { address: key, label });
    }
  };
  add(BUNDLED_VAULT_ADDRESS, 'Confío Dollar+');
  add(BUNDLED_CUSD_ADDRESS, 'Confío Dollar');
  add(USDT_BSC, 'USDT');
  add(BUNDLED_CONFIO_ADDRESS, 'CONFIO');
  exitTokenUniverse().forEach((t) => add(t.address, t.symbol));
  extra.forEach((a) => add(a, 'Otro activo'));
  return [...out.values()];
}

/** Non-zero balances held by the account, read through Multicall3. */
export async function readDirectHoldings(
  account: string,
  extra: readonly string[] = [],
  rpc: RpcFn = publicDirectRpc,
): Promise<DirectHolding[]> {
  if (!isAccountAddress(account)) {
    throw new Error('bad_account');
  }
  const universe = directTokenUniverse(extra);
  const held: DirectHolding[] = [];
  for (let i = 0; i < universe.length; i += BALANCE_CHUNK) {
    const chunk = universe.slice(i, i + BALANCE_CHUNK);
    const ret: string = await rpc('eth_call', [
      { to: MULTICALL3, data: encodeStockBalanceMulticall(account, chunk) }, 'latest',
    ]);
    const balances = decodeStockBalanceMulticall(ret, chunk.length);
    chunk.forEach((t, j) => {
      if ((balances[j] ?? 0n) > 0n) {
        held.push({ ...t, balance: balances[j] });
      }
    });
  }
  return held;
}

// ----------------------------------------------------------- gas / quote

const MIN_GAS_PRICE = 100_000_000n; // 0.1 gwei, the floor the app's other senders use
const GAS_FLOOR = 60_000n;

export interface DirectQuote {
  from: string;
  to: string;
  data: string;
  gasLimit: bigint;
  maxFeePerGas: bigint;
  /** Most this transaction can cost in BNB wei. */
  needWei: bigint;
  balanceWei: bigint;
}

export type DirectQuoteResult =
  | { ok: true; quote: DirectQuote }
  | { ok: false; reason: 'refused'; error: DirectRevertName | null };

/**
 * Simulate the call from the beneficiary's own address and price it. A call
 * the contract would refuse is caught here, before anything is signed or any
 * BNB is spent. Transport failures throw (the caller says "no connection").
 */
export async function quoteDirectCall(params: {
  from: string;
  account: string;
  call: DirectCall;
  rpc?: RpcFn;
}): Promise<DirectQuoteResult> {
  const { from, account, call } = params;
  const rpc = params.rpc ?? publicDirectRpc;
  if (!isAccountAddress(from) || !isAccountAddress(account)) {
    throw new Error('bad_address');
  }
  const data = directCalldata(call);
  let estimate: bigint;
  try {
    estimate = BigInt(await rpc('eth_estimateGas', [{ from, to: account, data }]));
  } catch (e) {
    if (e instanceof DirectRevertError) {
      return { ok: false, reason: 'refused', error: decodeRevert(e.data) };
    }
    throw e;
  }
  const [rawPrice, balance] = await Promise.all([
    rpc('eth_gasPrice', []),
    rpc('eth_getBalance', [from, 'latest']),
  ]);
  let price = BigInt(rawPrice);
  if (price < MIN_GAS_PRICE) {
    price = MIN_GAS_PRICE;
  }
  const maxFeePerGas = (price * 12n) / 10n;
  let gasLimit = (estimate * 13n) / 10n;
  if (gasLimit < GAS_FLOOR) {
    gasLimit = GAS_FLOOR;
  }
  return {
    ok: true,
    quote: {
      from, to: account, data, gasLimit, maxFeePerGas,
      needWei: gasLimit * maxFeePerGas,
      balanceWei: BigInt(balance),
    },
  };
}

// ---------------------------------------------------------------- send

export type DirectSendOutcome =
  | { status: 'executed'; txHash: string }
  /** Broadcast, verdict not seen. NOT a failure: never retry blindly. */
  | { status: 'unknown'; txHash: string }
  | { status: 'reverted'; txHash: string }
  | { status: 'refused'; error: DirectRevertName | null }
  | { status: 'needs_bnb'; needWei: bigint; balanceWei: bigint; address: string };

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * Sign on the device and broadcast one direct call. The withdraw destination
 * must be the signer's own wallet (spec 6.6 also allows the new owner's own
 * Cuenta inteligente, which needs the server to know; not offered here).
 */
export async function sendDirectCall(params: {
  wallet: DerivedEvmWallet;
  account: string;
  call: DirectCall;
  rpc?: RpcFn;
  receiptBudgetMs?: number;
  pollMs?: number;
  /** Called once the transaction is signed, before it is broadcast. */
  onSigned?: (txHash: string) => void;
}): Promise<DirectSendOutcome> {
  const { wallet, account, call } = params;
  const rpc = params.rpc ?? publicDirectRpc;
  if (call.kind === 'withdraw' && call.to.toLowerCase() !== wallet.address.toLowerCase()) {
    throw new Error('withdraw_to_must_be_own_wallet');
  }
  const quoted = await quoteDirectCall({ from: wallet.address, account, call, rpc });
  if (!quoted.ok) {
    return { status: 'refused', error: quoted.error };
  }
  const { quote } = quoted;
  if (quote.balanceWei < quote.needWei) {
    return { status: 'needs_bnb', needWei: quote.needWei, balanceWei: quote.balanceWei, address: wallet.address };
  }
  const nonce = BigInt(await rpc('eth_getTransactionCount', [wallet.address, 'pending']));
  const signed = signEip1559Transaction({
    nonce,
    maxPriorityFeePerGas: quote.maxFeePerGas,
    maxFeePerGas: quote.maxFeePerGas,
    gasLimit: quote.gasLimit,
    to: account,
    valueWei: 0n,
    data: quote.data,
    chainId: BSC_NETWORK.chainId,
  }, wallet.privKeyHex);
  params.onSigned?.(signed.txHash);

  // From here on a signed transaction exists. A transport error on the send
  // (timeout, dropped connection, a node that answered badly) does NOT mean
  // it was not broadcast: an endpoint may have relayed it before failing.
  // Only a decoded contract revert is a definitive "nothing happened"; every
  // other failure is "unknown" with the hash computed locally from the raw tx.
  try {
    await rpc('eth_sendRawTransaction', [signed.rawTx]);
  } catch (e) {
    if (e instanceof DirectRevertError) {
      return { status: 'refused', error: decodeRevert(e.data) };
    }
    const message = String((e as any)?.message || '');
    // "already known" and friends: another endpoint holds it; poll below.
    if (!/already known|known transaction|nonce too low/i.test(message)) {
      return { status: 'unknown', txHash: signed.txHash };
    }
  }

  const deadline = Date.now() + (params.receiptBudgetMs ?? 120_000);
  const pollMs = params.pollMs ?? 1500;
  for (;;) {
    let receipt: any = null;
    try {
      receipt = await rpc('eth_getTransactionReceipt', [signed.txHash]);
    } catch {
      receipt = null;
    }
    if (receipt) {
      return receipt.status === '0x1'
        ? { status: 'executed', txHash: signed.txHash }
        : { status: 'reverted', txHash: signed.txHash };
    }
    if (Date.now() + pollMs >= deadline) {
      return { status: 'unknown', txHash: signed.txHash };
    }
    await sleep(pollMs);
  }
}

/** Total BNB the withdraw of every holding needs, quoted one by one. */
export async function quoteDirectWithdrawAll(params: {
  from: string;
  account: string;
  holdings: readonly DirectHolding[];
  rpc?: RpcFn;
}): Promise<{ ok: true; needWei: bigint; balanceWei: bigint } | { ok: false; error: DirectRevertName | null }> {
  let need = 0n;
  let balance = 0n;
  for (const h of params.holdings) {
    const q = await quoteDirectCall({
      from: params.from,
      account: params.account,
      call: { kind: 'withdraw', token: h.address, amount: h.balance, to: params.from },
      rpc: params.rpc,
    });
    if (!q.ok) {
      return { ok: false, error: q.error };
    }
    need += q.quote.needWei;
    balance = q.quote.balanceWei;
  }
  return { ok: true, needWei: need, balanceWei: balance };
}

/** BNB wei as a short decimal string, rounded UP (it is a minimum to send). */
export function formatBnbCeil(wei: bigint, decimals = 5): string {
  const unit = 10n ** BigInt(18 - decimals);
  const units = (wei + unit - 1n) / unit;
  const whole = units / 10n ** BigInt(decimals);
  const frac = (units % 10n ** BigInt(decimals)).toString().padStart(decimals, '0').replace(/0+$/, '');
  return frac ? `${whole}.${frac}` : `${whole}`;
}
