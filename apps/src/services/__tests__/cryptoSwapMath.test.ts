import {
  buyFloors,
  DOLLAR,
  DOLLAR_PLUS,
  exceedsMaxOrder,
  exitUsdt,
  marketCostPct,
  SAVINGS_MIN_MINT_WEI,
  sellFloors,
  slipFloor,
  toBaseUnits,
  fromBaseUnits,
} from '../cryptoSwapMath';

// Vectors computed with the relay's own integer formulas
// (cusd_plus/crypto_policy.decode_crypto_call + vault math), in Python.
const PPS = 1_034_567_891_234_567_890n;
const ORACLE = 1_123_456_789_012_345_678n;
const PRICES = { pPlusWad: PPS, oraclePriceWad: ORACLE };
const FEE = 90n;
const SLIP = 100n;

/** The relay's acceptance test for a buy, transcribed from crypto_policy. */
const relayAcceptsBuy = (minUsdt: bigint, net: bigint, minToken: bigint, expectedOut: bigint) =>
  !(minUsdt > net || minUsdt < slipFloor(net, SLIP)) && expectedOut > 0n && minToken >= slipFloor(expectedOut, SLIP);

describe('buy floors (relay parity)', () => {
  it('cUSD exit: gross − ceil(gross·fee/1e4)', () => {
    const gross = 12_345_678_901_234_567_890n;
    const { netWei, feeWei, grossWei } = exitUsdt(DOLLAR, gross, FEE);
    expect(grossWei).toBe(gross);
    expect(netWei).toBe(12_234_567_791_123_456_778n);
    expect(feeWei).toBe(gross - netWei);
  });

  it('cUSD+ exit: double-floored redeem, then the same fee', () => {
    const { grossWei, netWei } = exitUsdt(DOLLAR_PLUS, 11_000_000_000_000_000_007n, FEE, PRICES);
    expect(grossWei).toBe(11_380_246_803_580_246_796n);
    expect(netWei).toBe(11_277_824_582_348_024_574n);
  });

  it('minUsdtOut is the exact net and minTokenOut the slippage floor of the quote', () => {
    const net = 12_234_567_791_123_456_778n;
    const quoted = 123_456_789_012_345n;
    const floors = buyFloors({ netUsdtWei: net, quotedTokenOut: quoted, slipBps: SLIP });
    expect(floors.minUsdtOut).toBe(net);
    expect(floors.minTokenOut).toBe((quoted * 9_900n) / 10_000n);
    expect(relayAcceptsBuy(floors.minUsdtOut, net, floors.minTokenOut, quoted)).toBe(true);
    // One wei above the net is refused by the relay (and reverts on-chain).
    expect(relayAcceptsBuy(net + 1n, net, floors.minTokenOut, quoted)).toBe(false);
    expect(relayAcceptsBuy(net, net, floors.minTokenOut - 1n, quoted)).toBe(false);
  });

  it('caps a buy at maxOrderUsd only when set', () => {
    expect(exceedsMaxOrder(100n * 10n ** 18n, 100)).toBe(false);
    expect(exceedsMaxOrder(100n * 10n ** 18n + 1n, 100)).toBe(true);
    expect(exceedsMaxOrder(10n ** 30n, null)).toBe(false);
  });
});

describe('sell floors (relay parity)', () => {
  it('cUSD: USDT floor, entry net of the fee, then the slippage floor', () => {
    const f = sellFloors({ dollar: DOLLAR, quotedUsdtOut: 98_765_432_109_876_543_210n, feeBps: FEE, slipBps: SLIP });
    expect(f.minUsdtOut).toBe(97_777_777_788_777_777_777n);
    expect(f.entryNetWei).toBe(96_897_777_788_678_777_777n);
    expect(f.expectedDest).toBe(f.entryNetWei);
    expect(f.minDestOut).toBe(95_928_800_010_791_989_999n);
    expect(f.savingsMintTooSmall).toBe(false);
  });

  it('cUSD+: shares a subscribe of the entry net mints', () => {
    const f = sellFloors({
      dollar: DOLLAR_PLUS, quotedUsdtOut: 5_432_109_876_543_210_987n, feeBps: FEE, slipBps: SLIP, prices: PRICES,
    });
    expect(f.minUsdtOut).toBe(5_377_788_777_777_778_877n);
    expect(f.entryNetWei).toBe(5_329_388_678_777_778_867n);
    expect(f.expectedDest).toBe(5_151_318_462_453_079_325n);
    expect(f.minDestOut).toBe(5_099_805_277_828_548_531n);
  });

  it('flags a cUSD+ sale netting under US$1.000001, never a cUSD one', () => {
    const quoted = 1_010_000_000_000_000_000n; // floor 0.9999 → under the mint floor
    expect(sellFloors({ dollar: DOLLAR_PLUS, quotedUsdtOut: quoted, feeBps: FEE, slipBps: SLIP, prices: PRICES })
      .savingsMintTooSmall).toBe(true);
    expect(sellFloors({ dollar: DOLLAR, quotedUsdtOut: quoted, feeBps: FEE, slipBps: SLIP }).savingsMintTooSmall)
      .toBe(false);
    expect(sellFloors({
      dollar: DOLLAR_PLUS, quotedUsdtOut: 1_030_000_000_000_000_000n, feeBps: FEE, slipBps: SLIP, prices: PRICES,
    }).savingsMintTooSmall).toBe(false);
  });

  it('uses the same mint floor as the vault client ($1.000001)', () => {
    expect(SAVINGS_MIN_MINT_WEI).toBe(1_000_001_000_000_000_000n);
  });
});

describe('units and market cost', () => {
  it('parses decimal strings into base units without float error', () => {
    expect(toBaseUnits('0.00012345', 18)).toBe(123_450_000_000_000n);
    expect(toBaseUnits('1.5', 6)).toBe(1_500_000n);
    expect(toBaseUnits('abc', 6)).toBe(0n);
    expect(fromBaseUnits('1500000', 6)).toBe(1.5);
  });

  it('never adds the pool fee on top of an impact that already includes it', () => {
    expect(marketCostPct(5, 12)).toBe(0.12);
    expect(marketCostPct(25, 3)).toBe(0.25);
    expect(marketCostPct(5, null)).toBe(0.05);
    expect(marketCostPct(null, null)).toBeNull();
  });
});
