import { formatDecimal } from './numberLocale';

// Adaptive precision for savings-accrual amounts ("hoy +$X", daily
// estimates, yield rows). Small savers earn sub-cent days and must still
// SEE growth — the daily tick IS the product promise, and hiding it from
// exactly the first-deposit users we need to convince kills the hook.
//
// Rules: ≥ 1¢ renders money-standard 2 dp; below it extends to 3 dp
// ($0.004), then 4 dp ($0.0002) — a $1 deposit earns ~$0.00008/day and
// must still render (+$0.0001), founder decision 2026-07-31. Only below
// 4-dp resolution (< $0.00005, would print the all-zeros "+$0.0000")
// returns null and the caller hides the line. Returns the absolute
// value — sign and color are the caller's job. Stock day-changes stay
// 2 dp (market convention); this is for savings yield only.
/** Decimals for a small money-in amount under the same rule (referral
 * commissions are often sub-cent: 0.45% of a few dollars). */
export const adaptiveDecimals = (v: number): number => {
  const abs = Math.abs(v);
  if (abs >= 0.005 || abs === 0) return 2;
  return abs >= 0.0005 ? 3 : 4;
};

/** A small money-in amount (no currency) under that rule. Below 4-dp
 *  resolution it says "<0.0001" instead of a misleading all-zeros figure. */
export const formatSmallAmount = (v: number): string => {
  const abs = Math.abs(v);
  if (abs > 0 && abs < 0.00005) return `<${formatDecimal(0.0001, { decimals: 4 })}`;
  return formatDecimal(abs, { decimals: adaptiveDecimals(abs) });
};

export const formatUsdDeltaAbs = (v: number): string | null => {
  const abs = Math.abs(v);
  if (abs < 0.00005) return null;
  if (abs >= 0.005) return `$${formatDecimal(abs, { decimals: 2 })}`;
  return `$${formatDecimal(abs, { decimals: abs >= 0.0005 ? 3 : 4 })}`;
};
