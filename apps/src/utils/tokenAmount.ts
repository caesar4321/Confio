// One canonical representation for a dollar amount, shared by every step of
// a withdrawal: integer MICRO-UNITS (1e6), parsed straight from the user's
// input string.
//
// Why this exists (audit 2026-08-03 [P1] #6/#7): the off-ramp order was
// created from `value.toFixed(6)` while the on-chain funding used
// `Math.round(value * 1e6)`. Those are different functions. Input
// `20.0000015` becomes 20.000001 through one and 20.000002 through the
// other, so the transfer paid the provider a different number than the order
// it was funding. Guardarian was worse: it sent the provider a raw float and
// only rounded at funding time.
//
// Everything HERE is string/BigInt based, and the on-chain transfer amount
// is integer-exact end to end.
//
// It is not true that no amount anywhere touches a float: the Guardarian
// rail still hands the provider a JSON number (microsToNumber -> float() in
// config/views.py), because that is what the provider's API takes. That
// round trip is exact at 6dp for realistic wallet sizes and the server
// re-quantizes with ROUND_DOWN, but the invariant is "the value that moves
// on-chain is exact", not "no float is ever involved" (round 3 [P2] #12).

/** USDT-BSC is 18dp; our canonical grain is 6dp. */
const MICRO_TO_WEI = 10n ** 12n;
const MICRO_DIGITS = 6;

/**
 * Parse a user-entered decimal amount into integer micro-units.
 *
 * Accepts both decimal separators (LATAM keyboards produce ","). Excess
 * precision is TRUNCATED, never rounded up — funding more than the user
 * asked for is the one direction that can overdraw them. Returns null for
 * anything that isn't a positive number.
 */
export const parseUsdMicros = (input: string | number | null | undefined): bigint | null => {
  if (input === null || input === undefined) return null;
  const raw = String(input).trim().replace(',', '.');
  if (!/^\d*\.?\d*$/.test(raw) || raw === '' || raw === '.') return null;

  const [whole, frac = ''] = raw.split('.');
  const fracPadded = (frac + '0'.repeat(MICRO_DIGITS)).slice(0, MICRO_DIGITS);
  const micros = BigInt(whole || '0') * 10n ** BigInt(MICRO_DIGITS) + BigInt(fracPadded || '0');
  return micros > 0n ? micros : null;
};

/** Micro-units to USDT-BSC base units (18dp). Exact, no rounding. */
export const microsToWei = (micros: bigint): bigint => micros * MICRO_TO_WEI;

/** 18dp base units back to micro-units, truncating the dust below our grain. */
export const weiToMicros = (wei: bigint): bigint => wei / MICRO_TO_WEI;

/**
 * The canonical decimal string for an amount — what goes to the server, the
 * provider, and the biometric confirmation prompt. Trailing zeros trimmed so
 * it reads like money, but the VALUE is exactly what will be transferred.
 */
export const formatMicros = (micros: bigint): string => {
  const negative = micros < 0n;
  const abs = negative ? -micros : micros;
  const unit = 10n ** BigInt(MICRO_DIGITS);
  const whole = abs / unit;
  const frac = (abs % unit).toString().padStart(MICRO_DIGITS, '0').replace(/0+$/, '');
  return `${negative ? '-' : ''}${whole}${frac ? `.${frac}` : ''}`;
};

/** Micro-units as a Number, for display helpers that still take numbers.
 *  Never feed the result back into a transfer — use the BigInt for that. */
export const microsToNumber = (micros: bigint): number => Number(micros) / 1e6;
