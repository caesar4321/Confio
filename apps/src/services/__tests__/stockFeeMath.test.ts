import {
  buyRequirement,
  buySpendForGross,
  feePercent,
  perimeterFee,
  sellFee,
  StockFeePolicy,
} from '../stockFeeMath';

const WAD = 10n ** 18n;
const V2: StockFeePolicy = { feeBps: 90n, mode: 'perimeter' };
const LEGACY: StockFeePolicy = { feeBps: 30n, mode: 'router' };

describe('stockFeeMath', () => {
  it('mirrors cUSD.feeFor rounding up', () => {
    expect(perimeterFee(100n * WAD, 90n)).toBe(9n * 10n ** 17n);
    expect(perimeterFee(1n, 90n)).toBe(1n);
    expect(perimeterFee(0n, 90n)).toBe(0n);
  });

  it('v2 buy: savings gross covers spend after the 0.9% exit fee, minimal', () => {
    const spend = 99_100_000_000_000_000_000n; // $99.10
    const { requiredGrossWei, feeWei, minUsdtOutWei } = buyRequirement(spend, V2);
    expect(requiredGrossWei - perimeterFee(requiredGrossWei, 90n)).toBeGreaterThanOrEqual(spend);
    const smaller = requiredGrossWei - 1n;
    expect(smaller - perimeterFee(smaller, 90n)).toBeLessThan(spend);
    expect(feeWei).toBe(requiredGrossWei - spend);
    expect(minUsdtOutWei).toBe(spend); // net floor, as the relay requires
  });

  it('v2 buy: $100 of savings buys $99.10 of stock', () => {
    expect(buySpendForGross(100n * WAD, V2)).toBe(99_100_000_000_000_000_000n);
  });

  it('legacy buy keeps the v1 shapes exactly', () => {
    const spend = 600n * WAD;
    const { requiredGrossWei, minUsdtOutWei } = buyRequirement(spend, LEGACY);
    expect(requiredGrossWei).toBe(spend + (spend * 30n + 9969n) / 9970n);
    expect(minUsdtOutWei).toBe(requiredGrossWei);
    expect(buySpendForGross(100n * WAD, LEGACY)).toBe(997n * 10n ** 17n);
  });

  it('sell fee: ceil for v2 (cUSD entry), floor for legacy (router)', () => {
    expect(sellFee(600n * WAD, V2)).toBe(54n * 10n ** 17n);
    expect(sellFee(1n, V2)).toBe(1n);
    expect(sellFee(1n, LEGACY)).toBe(0n);
  });

  it('formats the percent for display', () => {
    expect(feePercent(V2)).toBe(0.9);
    expect(feePercent(LEGACY)).toBe(0.3);
  });
});
