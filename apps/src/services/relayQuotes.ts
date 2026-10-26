// Relay orders behind Futuros plans, proven by the app (Futuros).
//
// Relay decides where a deposit or a withdrawal pays out from the ORDER the
// quote creates. The server passes Relay's raw signed quote with each plan;
// the app proves the order itself — its id is the EIP-712 hash of its
// terms, signed by Relay's solver — checks that the member is sender,
// recipient and refund address, and signs only the deposit or withdrawal
// that carries exactly this order. Mirrors cusd_plus/perps_relay.

import { keccak_256 } from '@noble/hashes/sha3';
import { bytesToHex, concatBytes, hexToBytes, utf8ToBytes } from '@noble/hashes/utils';
import { secp256k1 } from '@noble/curves/secp256k1.js';

/** Relay's solver that signs Futuros orders (mirrors settings.RELAY_PERPS_SOLVERS). */
const RELAY_SOLVERS = new Set(['0xf70da97812cb96acdf810712aa562db8dfa3dbef']);

export const BSC_CHAIN_ID = 56;
export const HL_CHAIN_ID = 1337;
const BSC_USDT = '0x55d398326f99059ff775485246999027b3197955';
const HL_USDC = '0x00000000000000000000000000000000';
const HL_USDC_TOKEN = 'USDC:0x6d1e7cde53ba9467b783cb7c530ce054';
const PROTOCOL_CHAIN: Record<number, string> = { [BSC_CHAIN_ID]: 'bnb', [HL_CHAIN_ID]: 'hyperliquid' };
const CURRENCY: Record<number, { address: string; decimals: number }> = {
  [BSC_CHAIN_ID]: { address: BSC_USDT, decimals: 18 },
  [HL_CHAIN_ID]: { address: HL_USDC, decimals: 8 },
};
export const RELAY_BSC_DEPOSITORY = '0x4cd00e387622c35bddb9b4c962c136462338bc31';
export const RELAY_HL_DEPOSITORY = '0x66cf0aace1b4e562593bec10ec7868fba9932224';
const SEL_DEPOSIT = 'e8017952';
const HEX32 = /^0x[0-9a-f]{64}$/;

export class RelayQuoteError extends Error {
  code = 'unsafe_plan';
}

const fail = (why: string): never => {
  throw new RelayQuoteError(why);
};

const addr = (v: unknown) => String(v ?? '').toLowerCase();
const big = (v: unknown): bigint => {
  const s = String(v ?? '');
  if (!/^\d+$/.test(s)) fail('relay: bad amount');
  return BigInt(s);
};

// ── order authentication ──────────────────────────────────────────────
// orderId = Relay's EIP-712 hashStruct of the order (relay-settlement sdk
// getOrderId); orderSignature = the solver's eth_sign of that id. Rebuilt
// here from the terms the app checks, so those terms ARE the order Relay
// executes. Mirrors cusd_plus/perps_relay.authenticate_order.

const ORDER_TYPES: Record<string, [string, string][]> = {
  Order: [['version', 'string'], ['solverChainId', 'string'], ['solver', 'address'], ['salt', 'uint256'],
    ['inputs', 'Input[]'], ['output', 'Output'], ['fees', 'Fee[]']],
  Input: [['payment', 'InputPayment'], ['refunds', 'InputRefund[]']],
  InputPayment: [['chainId', 'string'], ['currency', 'bytes'], ['amount', 'uint256'], ['weight', 'uint256']],
  InputRefund: [['chainId', 'string'], ['recipient', 'bytes'], ['currency', 'bytes'], ['minimumAmount', 'uint256'],
    ['deadline', 'uint32'], ['extraData', 'bytes']],
  Output: [['chainId', 'string'], ['payments', 'OutputPayment[]'], ['deadline', 'uint32'], ['calls', 'bytes[]'],
    ['extraData', 'bytes']],
  OutputPayment: [['recipient', 'bytes'], ['currency', 'bytes'], ['minimumAmount', 'uint256'],
    ['expectedAmount', 'uint256']],
  Fee: [['recipientChainId', 'string'], ['recipient', 'bytes'], ['currencyChainId', 'string'], ['currency', 'bytes'],
    ['amount', 'uint256']],
};

const typeString = (name: string): string => {
  const deps = new Set<string>();
  const walk = (t: string) => {
    const base = t.replace(/\[\]$/, '');
    if (ORDER_TYPES[base] && !deps.has(base)) {
      deps.add(base);
      ORDER_TYPES[base].forEach(([, ft]) => walk(ft));
    }
  };
  walk(name);
  deps.delete(name);
  return [name, ...[...deps].sort()]
    .map((n) => `${n}(${ORDER_TYPES[n].map(([fn, ft]) => `${ft} ${fn}`).join(',')})`).join('');
};

const hexBytes = (v: unknown): Uint8Array => {
  const s = String(v ?? '');
  if (!/^0x([0-9a-fA-F]{2})*$/.test(s)) fail('relay: order field');
  return hexToBytes(s.slice(2));
};

const encodeField = (ft: string, v: any): Uint8Array => {
  if (ft.endsWith('[]')) {
    if (!Array.isArray(v)) fail('relay: order array');
    return keccak_256(concatBytes(...v.map((x: any) => encodeField(ft.slice(0, -2), x))));
  }
  if (ORDER_TYPES[ft]) return structHash(ft, v);
  if (ft === 'string') {
    if (typeof v !== 'string') fail('relay: order string');
    return keccak_256(utf8ToBytes(v));
  }
  if (ft === 'bytes') return keccak_256(hexBytes(v));
  if (ft === 'address') {
    const b = hexBytes(v);
    if (b.length !== 20) fail('relay: order address');
    return concatBytes(new Uint8Array(12), b);
  }
  if (ft.startsWith('uint')) {
    const n = BigInt(typeof v === 'number' ? v : String(v));
    if (n < 0n || n >= 1n << BigInt(ft.slice(4))) fail('relay: order integer');
    return hexToBytes(n.toString(16).padStart(64, '0'));
  }
  return fail('relay: order type');
};

const structHash = (name: string, data: any): Uint8Array => {
  if (!data || typeof data !== 'object') fail('relay: order struct');
  return keccak_256(concatBytes(keccak_256(utf8ToBytes(typeString(name))),
    ...ORDER_TYPES[name].map(([fn, ft]) => encodeField(ft, data[fn]))));
};

export const relayOrderId = (order: any) => '0x' + bytesToHex(structHash('Order', order));

/** The order id is the hash of these terms, signed by Relay's solver. */
const authenticateOrder = (v2: any): string => {
  const order = v2?.orderData;
  if (order?.version !== 'v1') fail('relay: order version');
  const id = addr(v2?.orderId);
  if (relayOrderId(order) !== id) fail('relay: order id does not match its terms');
  const solver = addr(order.solver);
  if (!RELAY_SOLVERS.has(solver)) fail('relay: unknown solver');
  const sig = hexBytes(v2?.orderSignature);
  if (sig.length !== 65) fail('relay: order signature');
  const digest = keccak_256(concatBytes(utf8ToBytes('\x19Ethereum Signed Message:\n32'), hexToBytes(id.slice(2))));
  let signer = '';
  try {
    const v = sig[64] >= 27 ? sig[64] - 27 : sig[64];
    const pub = secp256k1.Signature.fromBytes(concatBytes(Uint8Array.of(v), sig.slice(0, 64)), 'recovered')
      .recoverPublicKey(digest).toBytes(false);
    signer = '0x' + bytesToHex(keccak_256(pub.slice(1)).slice(-20));
  } catch {
    fail('relay: order signature');
  }
  if (signer !== solver) fail('relay: order not signed by its solver');
  return id;
};

/** The order terms common to both directions: who sends, who receives, in
 *  what, how much, and who gets a refund — all the member. */
const bindOrder = (raw: any, origin: number, destination: number, amount: bigint, wallet: string) => {
  const me = wallet.toLowerCase();
  authenticateOrder(raw?.protocol?.v2);
  const d = raw?.details;
  if (addr(d?.sender) !== me || addr(d?.recipient) !== me) fail('relay: not the member');
  for (const [field, chain] of [['currencyIn', origin], ['currencyOut', destination], ['refundCurrency', origin]] as const) {
    const c = d?.[field]?.currency;
    if (c?.chainId !== chain || addr(c?.address) !== CURRENCY[chain].address || c?.decimals !== CURRENCY[chain].decimals) {
      fail('relay: asset or network');
    }
  }
  if (big(d.currencyIn.amount) !== amount) fail('relay: input amount');
  const v2 = raw?.protocol?.v2;
  const orderId = addr(v2?.orderId);
  if (!HEX32.test(orderId)) fail('relay: order id');
  const order = v2?.orderData;
  const inputs = order?.inputs;
  const out = order?.output;
  if (!Array.isArray(inputs) || inputs.length !== 1 || out?.payments?.length !== 1
      || (out.calls && out.calls.length) || (order.fees && order.fees.length)) {
    fail('relay: order shape');
  }
  const pay = inputs[0].payment;
  if (pay?.chainId !== PROTOCOL_CHAIN[origin] || addr(pay?.currency) !== CURRENCY[origin].address
      || big(pay?.amount) !== amount) {
    fail('relay: order input');
  }
  const paid = out.payments[0];
  if (out.chainId !== PROTOCOL_CHAIN[destination] || addr(paid?.currency) !== CURRENCY[destination].address
      || addr(paid?.recipient) !== me) {
    fail('relay: order output');
  }
  // The member's tolerances, as the server's (perps_relay.validate_quote): an
  // authentic order may still carry terms no member agreed to.
  const expected = big(paid.expectedAmount);
  const minimum = big(paid.minimumAmount);
  const decimals = BigInt(CURRENCY[destination].decimals);
  const floor = (15n * 10n ** decimals) / 100n; // 15 cents
  const allowed = [expected * 250n / 10_000n, floor].reduce((a, b) => (a > b ? a : b));
  const deterioration = allowed < expected * 1000n / 10_000n ? allowed : expected * 1000n / 10_000n;
  const rebased = amount * 10n ** decimals / 10n ** BigInt(CURRENCY[origin].decimals);
  if (minimum <= 0n || minimum > expected || expected - minimum > deterioration
      || minimum * 10_000n < rebased * (10_000n - 2000n)) {
    fail('relay: output below the member\'s tolerance');
  }
  // The order's own signed deadline: an expired order is never paid into.
  const deadline = Number(out.deadline);
  if (!Number.isSafeInteger(deadline) || deadline * 1000 <= Date.now() + 120_000) fail('relay: order expired');
  const refunds = inputs[0].refunds;
  if (!Array.isArray(refunds) || !refunds.length || refunds.some((r: any) => addr(r?.recipient) !== me)) {
    fail('relay: refunds');
  }
  const details = v2?.paymentDetails;
  const depository = addr(details?.depository);
  if (details?.chainId !== PROTOCOL_CHAIN[origin] || big(details?.amount) !== amount
      || depository !== (origin === BSC_CHAIN_ID ? RELAY_BSC_DEPOSITORY : RELAY_HL_DEPOSITORY)) {
    fail('relay: payment details');
  }
  return {
    orderId, depository, requestId: addr(raw?.requestId), deadline,
    // What the order guarantees to deliver (and expects to): the review is held to it.
    expectedOut: big(paid.expectedAmount), minimumOut: big(paid.minimumAmount),
  };
};

const word = (hex: string) => hex.replace(/^0x/, '').padStart(64, '0');

/** BSC → HyperCore: the one deposit call this quote allows. */
export const bindDepositQuote = (raw: any, wallet: string, amount: bigint) => {
  const order = bindOrder(raw, BSC_CHAIN_ID, HL_CHAIN_ID, amount, wallet);
  const data = '0x' + SEL_DEPOSIT + word(wallet.toLowerCase()) + word(BSC_USDT) + word(amount.toString(16))
    + order.orderId.slice(2);
  return { ...order, depositData: data };
};

/** HyperCore → BSC: the nonce mapping and withdrawal this quote allows. */
export const bindReturnQuote = (raw: any, wallet: string, units: bigint) => {
  const me = wallet.toLowerCase();
  const order = bindOrder(raw, HL_CHAIN_ID, BSC_CHAIN_ID, units, wallet);
  const steps = Object.fromEntries((raw?.steps || []).map((s: any) => [s?.id, s]));
  const sign = steps.authorize?.items?.[0]?.data?.sign;
  const value = sign?.value;
  const params = steps.deposit?.items?.[0]?.data?.action?.parameters;
  const nonce = value?.nonce;
  if (sign?.domain?.name !== 'RelayNonceMapping' || sign?.domain?.version !== '2' || sign?.primaryType !== 'NonceMapping'
      || value?.chainId !== 'hyperliquid' || addr(value?.wallet) !== me || addr(value?.depositor) !== me
      || addr(value?.id) !== order.orderId || !Number.isSafeInteger(nonce) || nonce <= 0
      // A Hyperliquid nonce is a millisecond timestamp: only one from around now
      // (a far-future one could never be retired, and would block new funding).
      || Math.abs(nonce - Date.now()) > 30 * 60 * 1000) {
    fail('relay: authorization');
  }
  const amount = String(params?.amount ?? '');
  const [whole, frac = ''] = amount.split('.');
  if (!/^\d+(\.\d+)?$/.test(amount) || BigInt(whole) * 10n ** 8n + BigInt((frac + '00000000').slice(0, 8)) !== units
      || addr(params?.destination) !== order.depository || params?.sourceDex !== '' || params?.destinationDex !== ''
      || params?.token !== HL_USDC_TOKEN || params?.fromSubAccount !== '' || params?.nonce !== nonce) {
    fail('relay: withdrawal');
  }
  return { ...order, nonce: nonce as number, amount, destination: order.depository };
};
