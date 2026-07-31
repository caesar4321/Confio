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
export const formatUsdDeltaAbs = (v: number): string | null => {
  const abs = Math.abs(v);
  if (abs < 0.00005) return null;
  if (abs >= 0.005) return `$${abs.toFixed(2)}`;
  return `$${abs.toFixed(abs >= 0.0005 ? 3 : 4)}`;
};
