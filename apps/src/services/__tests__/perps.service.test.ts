// The app re-checks everything the server asks it to sign: a compromised or
// buggy server can ask, but can never make the member sign money to anyone
// else (services/perps.ts verifyIssuedCalls / verifyAction).
import { RELAY_BSC_DEPOSITORY, deriveIntentId, encodeCall, selector } from '../evmWallet';
import {
  HL_USDC_TOKEN, TradeContext, venuePrice, estimateLiquidationPx, pinnedDollars, usdToWei, verifyAction, verifyIssuedCalls,
} from '../perps';
import { wirePrice } from '../emergencyExit/hyperCoreExit';

const ME = '0x' + '44'.repeat(20);
const OTHER = '0x' + '99'.repeat(20);
const VAULT = '0x' + '11'.repeat(20);
const CUSD = '0x' + '22'.repeat(20);
const USDT = '0x55d398326f99059ff775485246999027b3197955';
const dollars = { vaultAddress: VAULT, cusdAddress: CUSD };
const word = (hex: string) => hex.replace(/^0x/, '').padStart(64, '0');

const exit = (to = ME, minOut = 991n * 10n ** 16n) => ({
  to: CUSD, value: '0',
  data: encodeCall('redeemWithFee(uint256,uint256,address)', [
    { type: 'uint', value: 10n ** 19n }, { type: 'uint', value: minOut }, { type: 'address', value: to }]),
});
const approve = (spender: string) => ({
  to: USDT, value: '0',
  data: encodeCall('approve(address,uint256)', [{ type: 'address', value: spender }, { type: 'uint', value: 10n ** 19n }]),
});
const deposit = (depositor = ME, amount = 991n * 10n ** 16n) => ({
  to: RELAY_BSC_DEPOSITORY, value: '0',
  data: '0xe8017952' + word(depositor) + word(USDT) + word(amount.toString(16)) + 'ab'.repeat(32),
});

// The Relay order the app fetched itself: the deposit must be exactly its call.
const relayFor = (amount = 991n * 10n ** 16n, depositor = ME) => ({
  depository: RELAY_BSC_DEPOSITORY,
  depositData: '0xe8017952' + word(depositor) + word(USDT) + word(amount.toString(16)) + 'ab'.repeat(32),
});
const OUT = { direction: 'out' as const, maxWei: 10n ** 19n, relayDeposit: relayFor() };

describe('verifyIssuedCalls', () => {
  it('accepts the exit + approve + Relay deposit to the member, within the reviewed amount', () => {
    expect(verifyIssuedCalls([exit(), approve(RELAY_BSC_DEPOSITORY), deposit()], ME, dollars, OUT)).toHaveLength(3);
  });
  it.each([
    ['an exit paid to someone else', [exit(OTHER), approve(RELAY_BSC_DEPOSITORY), deposit()]],
    ['an approval to a stranger', [exit(), approve(OTHER), deposit()]],
    ['an approval to a vault on the way out', [exit(), approve(VAULT), deposit()]],
    ['a deposit credited to someone else', [exit(), approve(RELAY_BSC_DEPOSITORY), deposit(OTHER)]],
    ['no Relay deposit', [exit(), approve(RELAY_BSC_DEPOSITORY)]],
    ['two Relay deposits', [exit(), approve(RELAY_BSC_DEPOSITORY), deposit(), deposit()]],
    ['a raw USDT transfer', [{ to: USDT, value: '0', data: selector('transfer(address,uint256)') + word(OTHER) + word('1') }]],
    ['native value', [{ ...exit(), value: '1' }]],
  ])('refuses %s', (_label, calls) => {
    expect(() => verifyIssuedCalls(calls as any, ME, dollars, OUT)).toThrow();
  });
  it('refuses more than the member reviewed', () => {
    const calls = [exit(), approve(RELAY_BSC_DEPOSITORY), deposit()];
    expect(() => verifyIssuedCalls(calls, ME, dollars, { ...OUT, maxWei: usdToWei('9.99') })).toThrow();
    expect(verifyIssuedCalls(calls, ME, dollars, { ...OUT, maxWei: usdToWei('10') })).toHaveLength(3);
  });
  it('caps all redemptions together, shares at the chain price', () => {
    const twice = [exit(), exit(), approve(RELAY_BSC_DEPOSITORY), deposit()];
    expect(() => verifyIssuedCalls(twice, ME, dollars, OUT)).toThrow();
    const plus = (shares: bigint) => ({ to: VAULT, value: '0', data: encodeCall('redeemToUsdt(uint256,uint256,address)', [
      { type: 'uint', value: shares }, { type: 'uint', value: 1n }, { type: 'address', value: ME }]) });
    const calls = [plus(10n ** 19n), approve(RELAY_BSC_DEPOSITORY), deposit()];
    expect(() => verifyIssuedCalls(calls, ME, dollars, OUT)).toThrow(); // no price: cannot value it
    expect(verifyIssuedCalls(calls, ME, dollars, { ...OUT, plusPriceWad: 10n ** 18n })).toHaveLength(3);
    expect(() => verifyIssuedCalls([plus(10n ** 21n), approve(RELAY_BSC_DEPOSITORY), deposit()], ME, dollars,
      { ...OUT, plusPriceWad: 10n ** 18n })).toThrow(); // the whole balance for a $10 trade
  });
  it('an open spends the reviewed dollar, never loose USDT instead', () => {
    expect(() => verifyIssuedCalls([approve(RELAY_BSC_DEPOSITORY), deposit()], ME, dollars, { ...OUT, dollar: 'cusd' })).toThrow();
    expect(verifyIssuedCalls([approve(RELAY_BSC_DEPOSITORY), deposit()], ME, dollars, { ...OUT, refundRetry: true })).toHaveLength(2);
    expect(() => verifyIssuedCalls([exit(), approve(RELAY_BSC_DEPOSITORY), deposit()], ME, dollars,
      { ...OUT, refundRetry: true })).toThrow(); // a retry never redeems fresh dollars
    const token = { to: CUSD, value: '0', data: encodeCall('redeemWithFee(uint256,uint256,address)', [
      { type: 'uint', value: 10n ** 16n }, { type: 'uint', value: 1n }, { type: 'address', value: ME }]) };
    expect(() => verifyIssuedCalls([token, approve(RELAY_BSC_DEPOSITORY), deposit()], ME, dollars,
      { ...OUT, dollar: 'cusd' })).toThrow(); // $0.01 redeemed, $10 of loose USDT deposited
  });
  it('the deposit is covered by the redemption, and is the reviewed amount less exit costs', () => {
    const OUTD = { ...OUT, dollar: 'cusd' as const };
    expect(verifyIssuedCalls([exit(), approve(RELAY_BSC_DEPOSITORY), deposit()], ME, dollars, OUTD)).toHaveLength(3);
    expect(() => verifyIssuedCalls([exit(), approve(RELAY_BSC_DEPOSITORY), deposit(ME, 10n ** 19n)], ME, dollars, OUTD))
      .toThrow(); // $10 deposit from a redemption guaranteeing $9.91: loose USDT
    expect(() => verifyIssuedCalls([exit(ME, 10n ** 18n), approve(RELAY_BSC_DEPOSITORY), deposit(ME, 10n ** 18n)], ME,
      dollars, OUTD)).toThrow(); // $10 redeemed for a $1 deposit
  });
  it('redeems only the dollar the member saw leaving', () => {
    const calls = [exit(), approve(RELAY_BSC_DEPOSITORY), deposit()];
    expect(verifyIssuedCalls(calls, ME, dollars, { ...OUT, dollar: 'cusd' })).toHaveLength(3);
    expect(() => verifyIssuedCalls(calls, ME, dollars, { ...OUT, dollar: 'cusd_plus' })).toThrow();
  });
  it('the entry only mints to the member: no Relay, no redemption', () => {
    const mint = { to: CUSD, value: '0', data: encodeCall('mintWithFee(uint256,uint256,address)', [
      { type: 'uint', value: 10n ** 19n }, { type: 'uint', value: 1n }, { type: 'address', value: ME }]) };
    const IN = { direction: 'in' as const, maxWei: null };
    expect(verifyIssuedCalls([approve(CUSD), mint], ME, dollars, IN)).toHaveLength(2);
    expect(() => verifyIssuedCalls([approve(CUSD), mint, deposit()], ME, dollars, IN)).toThrow();
    expect(() => verifyIssuedCalls([exit()], ME, dollars, IN)).toThrow();
    const landed = { direction: 'in' as const, maxWei: 10n ** 19n };
    expect(verifyIssuedCalls([approve(CUSD), mint], ME, dollars, landed)).toHaveLength(2);
    expect(() => verifyIssuedCalls([approve(CUSD), mint, approve(CUSD), mint], ME, dollars, landed)).toThrow();
  });
  it('the dollar contracts come from the app bundle, never only from the server', () => {
    expect(() => pinnedDollars({ vaultAddress: OTHER })).toThrow();
    expect(pinnedDollars({}).vaultAddress).toBe('0x3c29417eb4314155e63d4c7d4507852b87763ed1');
  });
});

describe('verifyAction', () => {
  const trade = (over: Partial<TradeContext> = {}): TradeContext => ({
    stage: 'open', assetId: 110003, dex: 'xyz', side: 'long', leverage: 5, markPx: 100, maxNotionalUsd: 102, szDecimals: 2,
    maxSize: 1, triggers: { tp: null, sl: 90 }, ...over,
  });
  const order = (r: boolean, over: Record<string, unknown> = {}) => ({
    type: 'order', orders: [{ a: 110003, b: true, p: '100', s: '1', r, t: { limit: { tif: 'Ioc' } }, c: '0x' + '0a'.repeat(16), ...over }], grouping: 'na',
  });
  it('only moves USDC between the member\'s own balances, to the market\'s own dex', () => {
    const send = { type: 'sendAsset', destination: ME, sourceDex: '', destinationDex: 'xyz', token: HL_USDC_TOKEN, amount: '1', fromSubAccount: '' };
    expect(() => verifyAction(send, 'fund_dex', ME, trade())).not.toThrow();
    expect(() => verifyAction({ ...send, destination: OTHER }, 'fund_dex', ME, trade())).toThrow();
    expect(() => verifyAction({ ...send, destinationDex: 'flx' }, 'fund_dex', ME, trade())).toThrow();
    expect(() => verifyAction({ ...send, sourceDex: 'xyz', destinationDex: '' }, 'return_dex', ME, trade({ stage: 'return' }))).not.toThrow();
    expect(() => verifyAction({ type: 'withdraw3', destination: OTHER }, 'fund_dex', ME, trade())).toThrow();
  });
  it('a limit entry rests at exactly the member\'s price, never a worse one', () => {
    const limitTrade = trade({ entry: { type: 'limit', limitPx: 95, tp: null, sl: null } });
    const gtc = (over: Record<string, unknown> = {}) => order(false, { p: '95', t: { limit: { tif: 'Gtc' } }, ...over });
    expect(() => verifyAction(gtc(), 'open_order', ME, limitTrade)).not.toThrow();
    expect(() => verifyAction(gtc({ p: '96' }), 'open_order', ME, limitTrade)).toThrow(); // a buy above its limit
    expect(() => verifyAction(gtc({ p: '94.95' }), 'open_order', ME, limitTrade)).toThrow(); // not the price chosen
    expect(() => verifyAction(order(false, { p: '95' }), 'open_order', ME, limitTrade)).toThrow(); // Ioc: not what was chosen
    expect(() => verifyAction(gtc(), 'open_order', ME, trade())).toThrow(); // a resting order the member never asked for
    // A short resting above the market fills at its limit: exposure judged there (Codex r1).
    expect(() => verifyAction(order(false, { b: false, p: '150', t: { limit: { tif: 'Gtc' } } }), 'open_order', ME,
      trade({ side: 'short', entry: { type: 'limit', limitPx: 150, tp: null, sl: null } }))).toThrow();
    expect(() => verifyAction(gtc({ p: '40' }), 'open_order', ME,
      trade({ entry: { type: 'limit', limitPx: 40, tp: null, sl: null } }))).toThrow(); // absurdly far from the market
  });
  it('protection rides the entry only as chosen: reduce-only, opposite side, the entry\'s size', () => {
    const entry = { type: 'market' as const, limitPx: null, tp: 120, sl: 90 };
    const child = (kind: 'tp' | 'sl', px: string, over: Record<string, unknown> = {}) => ({
      a: 110003, b: false, p: px, s: '1', r: true, t: { trigger: { isMarket: true, triggerPx: px, tpsl: kind } },
      c: '0x' + (kind === 'tp' ? '7a' : '7b').repeat(16), ...over,
    });
    const withKids = (kids: any[]) => ({ ...order(false), orders: [order(false).orders[0], ...kids], grouping: 'normalTpsl' });
    expect(() => verifyAction(withKids([child('tp', '120'), child('sl', '90')]), 'open_order', ME, trade({ entry }))).not.toThrow();
    expect(() => verifyAction(withKids([child('tp', '120')]), 'open_order', ME, trade({ entry }))).toThrow(); // stop missing
    expect(() => verifyAction(withKids([child('tp', '120'), child('sl', '80')]), 'open_order', ME, trade({ entry }))).toThrow();
    expect(() => verifyAction(withKids([child('tp', '120'), child('sl', '90', { r: false })]), 'open_order', ME,
      trade({ entry }))).toThrow(); // could open the other way
    expect(() => verifyAction(withKids([child('tp', '120'), child('sl', '90', { s: '0.1' })]), 'open_order', ME,
      trade({ entry }))).toThrow(); // a sliver
    expect(() => verifyAction(order(false), 'open_order', ME, trade({ entry }))).toThrow(); // chosen protection missing
    expect(() => verifyAction(withKids([child('sl', '90')]), 'open_order', ME, trade())).toThrow(); // none was chosen
  });
  it('trades only the market, side, leverage and size the member chose', () => {
    expect(() => verifyAction(order(false), 'open_order', ME, trade())).not.toThrow();
    expect(() => verifyAction(order(false, { a: 0 }), 'open_order', ME, trade())).toThrow();
    expect(() => verifyAction(order(false, { b: false }), 'open_order', ME, trade())).toThrow();
    expect(() => verifyAction(order(false, { s: '2' }), 'open_order', ME, trade())).toThrow();
    expect(() => verifyAction(order(false), 'close_order', ME, trade({ stage: 'close' }))).toThrow();
    expect(() => verifyAction(order(true, { b: false }), 'close_order', ME, trade({ stage: 'close' }))).not.toThrow();
    const sl = (px: string) => ({ ...order(true, { b: false, p: px, t: { trigger: { isMarket: true, triggerPx: px, tpsl: 'sl' } }, c: '0x' + '5c'.repeat(16) }),
      grouping: 'positionTpsl' });
    expect(() => verifyAction(sl('90'), 'tpsl', ME, trade({ stage: 'tpsl' }))).not.toThrow();
    expect(() => verifyAction(sl('50'), 'tpsl', ME, trade({ stage: 'tpsl' }))).toThrow(); // not the price entered
    expect(() => verifyAction(sl('90'), 'tpsl', ME, trade({ stage: 'tpsl', maxSize: 10 }))).toThrow(); // a sliver of 10
    const wild = { ...sl('90'), orders: [{ ...sl('90').orders[0], p: '1' }] };
    expect(() => verifyAction(wild, 'tpsl', ME, trade({ stage: 'tpsl' }))).toThrow(); // execution limit far from the trigger
    expect(() => verifyAction({ type: 'updateIsolatedMargin', asset: 110003, isBuy: true, ntli: 1 }, 'margin_add', ME,
      trade({ stage: 'margin', budgetUsd: 100 }))).toThrow(); // a token amount of a $100 top-up
    expect(() => verifyAction(sl('90'), 'tpsl', ME, trade({ stage: 'tpsl', triggers: { tp: 120, sl: 90 } }))).toThrow(); // TP missing
    expect(() => verifyAction(order(true, { b: false, s: '5' }), 'close_order', ME, trade({ stage: 'close' }))).toThrow();
    // A short judged at the mark: a $1 floor does not make 100 units small.
    expect(() => verifyAction(order(false, { b: false, p: '1', s: '100' }), 'open_order', ME, trade({ side: 'short' }))).toThrow();
    expect(() => verifyAction(order(false, { p: '150' }), 'open_order', ME, trade())).toThrow();
    expect(() => verifyAction(order(false), 'close_order', ME, trade())).toThrow(); // purpose outside the stage
    const cancel = { type: 'cancel', cancels: [{ a: 110003, o: 77 }] };
    expect(() => verifyAction(cancel, 'tpsl_cancel', ME, trade({ stage: 'tpsl' }))).not.toThrow();
    expect(() => verifyAction({ type: 'cancel', cancels: [{ a: 0, o: 77 }] }, 'tpsl_cancel', ME, trade({ stage: 'tpsl' }))).toThrow();
    expect(() => verifyAction(cancel, 'tpsl_cancel', ME, trade({ stage: 'close' }))).toThrow();
    const lev = { type: 'updateLeverage', asset: 110003, isCross: false, leverage: 5 };
    expect(() => verifyAction(lev, 'leverage', ME, trade())).not.toThrow();
    expect(() => verifyAction({ ...lev, leverage: 40 }, 'leverage', ME, trade())).toThrow();
    expect(() => verifyAction({ ...lev, isCross: true }, 'leverage', ME, trade())).toThrow();
    const add = { type: 'updateIsolatedMargin', asset: 110003, isBuy: true, ntli: 5_000_000 };
    expect(() => verifyAction(add, 'margin_add', ME, trade({ stage: 'margin' }))).not.toThrow();
    expect(() => verifyAction({ ...add, ntli: -5_000_000 }, 'margin_add', ME, trade({ stage: 'margin' }))).toThrow();
    expect(() => verifyAction({ ...add, ntli: 50_000_000 }, 'margin_add', ME, trade({ stage: 'margin', budgetUsd: 10 }))).toThrow();
    expect(() => verifyAction({ ...order(false), builder: { b: OTHER, f: 10 } }, 'open_order', ME, trade())).toThrow();
  });
});

describe('intent kind', () => {
  it('matches the server: an exit + Relay deposit is perps_open, a deposit alone a retry', () => {
    const open = [exit(), approve(RELAY_BSC_DEPOSITORY), deposit()].map((c) => ({ ...c, valueWei: 0n }));
    const { keccak_256 } = require('@noble/hashes/sha3');
    const { bytesToHex, utf8ToBytes } = require('@noble/hashes/utils');
    const id = (k: string) => '0x' + bytesToHex(keccak_256(utf8ToBytes(`${k}:req`)));
    expect(deriveIntentId(open, 'req')).toBe(id('perps_open'));
    expect(deriveIntentId(open.slice(1), 'req')).toBe(id('perps_bridge_retry'));
  });
});

describe('math', () => {
  it('liquidation sits on the losing side', () => {
    expect(estimateLiquidationPx(100, 100, 20, 'long', 20)!).toBeLessThan(100);
    expect(estimateLiquidationPx(100, 100, 20, 'short', 20)!).toBeGreaterThan(100);
  });
  it('Hyperliquid price rounding', () => {
    expect(wirePrice(2650.123, 4, true)).toBe('2650.2');
    expect(wirePrice(98000.4, 5, true)).toBe('98001');
    expect(wirePrice(0.00012345, 0, false)).toBe('0.000123');
  });
});

describe('the Relay order', () => {
  it('refuses a deposit into any order but the one the app fetched', () => {
    const other = { ...deposit(), data: deposit().data.slice(0, -64) + 'cd'.repeat(32) };
    expect(() => verifyIssuedCalls([exit(), approve(RELAY_BSC_DEPOSITORY), other], ME, dollars, OUT)).toThrow();
    expect(() => verifyIssuedCalls([exit(), approve(RELAY_BSC_DEPOSITORY), deposit()], ME, dollars,
      { ...OUT, relayDeposit: null })).toThrow();
  });
});

describe('venuePrice', () => {
  it('rounds like Hyperliquid: 5 significant figures, decimals by size, integers allowed', () => {
    expect(venuePrice(95000.37, 5, false)).toBe(95000);
    expect(venuePrice(101.123, 2, false)).toBe(101.12);
    expect(venuePrice(101.123, 2, true)).toBe(101.13);
    expect(venuePrice(0.0012345, 0, false)).toBe(0.001234);
    expect(venuePrice(123456.7, 5, true)).toBe(123457);
  });
});
