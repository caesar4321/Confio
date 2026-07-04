// Adaptive precision for savings-accrual amounts ("hoy +$X", daily
// estimates, yield rows). Small savers earn sub-cent days and must still
// SEE growth — the daily tick IS the product promise, and hiding it from
// exactly the first-deposit users we need to convince kills the hook.
//
// Rules: ≥ 1¢ renders money-standard 2 dp; below it extends to 3 dp
// ($0.004); below display resolution (< $0.0005) returns null and the
// caller hides the line. Returns the absolute value — sign and color are
// the caller's job. Stock day-changes stay 2 dp (market convention);
// this is for savings yield only.
export const formatUsdDeltaAbs = (v: number): string | null => {
  const abs = Math.abs(v);
  if (abs < 0.0005) return null;
  return `$${abs.toFixed(abs >= 0.005 ? 2 : 3)}`;
};
