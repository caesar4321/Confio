// Stock-trade fee math, shared by quotes, execution and the screens.
//
// Confío charges one 0.9% fee whenever dollars leave or re-enter Confío
// Dollar (cUSD/cUSD+): a withdrawal, a deposit, a stock buy or a stock sale.
// Router v2 ("perimeter" mode) takes it on the cUSD+ exit (buy) and entry
// (sell) and charges nothing of its own. "router" mode is the v1 math (30
// bps accrued by the router), used only until router v2 is live; the server
// says which via `stockFeePolicy`.

export type StockFeeMode = 'perimeter' | 'router';

export interface StockFeePolicy {
  feeBps: bigint;
  mode: StockFeeMode;
}

const BPS = 10_000n;

const ceilDiv = (a: bigint, b: bigint): bigint => (a + b - 1n) / b;

/** Mirror of CusdVault.feeFor: ceil(gross * feeBps / 10_000). */
export const perimeterFee = (grossWei: bigint, feeBps: bigint): bigint =>
  grossWei <= 0n || feeBps <= 0n ? 0n : ceilDiv(grossWei * feeBps, BPS);

/** The stock notional a gross savings amount buys. */
export const buySpendForGross = (grossWei: bigint, policy: StockFeePolicy): bigint =>
  policy.mode === 'perimeter'
    ? grossWei - perimeterFee(grossWei, policy.feeBps)
    : grossWei - (grossWei * policy.feeBps) / BPS;

/**
 * What a buy of `spendWei` (the attested notional) needs from savings.
 * `minUsdtOut` is the router floor: the gross redemption in router mode, the
 * net after cUSD's exit fee in perimeter mode (the server checks both).
 */
export const buyRequirement = (
  spendWei: bigint,
  policy: StockFeePolicy,
): { requiredGrossWei: bigint; feeWei: bigint; minUsdtOutWei: bigint } => {
  const bps = policy.feeBps;
  if (policy.mode === 'perimeter') {
    let gross = ceilDiv(spendWei * BPS, BPS - bps);
    while (gross - perimeterFee(gross, bps) < spendWei) gross += 1n;
    return { requiredGrossWei: gross, feeWei: gross - spendWei, minUsdtOutWei: spendWei };
  }
  const fee = ceilDiv(spendWei * bps, BPS - bps);
  return { requiredGrossWei: spendWei + fee, feeWei: fee, minUsdtOutWei: spendWei + fee };
};

/** Fee taken from a sale's USDT proceeds before they re-enter savings. */
export const sellFee = (proceedsWei: bigint, policy: StockFeePolicy): bigint =>
  policy.mode === 'perimeter'
    ? perimeterFee(proceedsWei, policy.feeBps)
    : (proceedsWei * policy.feeBps) / BPS;

/** Percent for display, e.g. 90n -> 0.9. */
export const feePercent = (policy: StockFeePolicy): number => Number(policy.feeBps) / 100;
