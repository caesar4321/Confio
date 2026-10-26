/**
 * Formatting for the Comunidad asset profile. The server sends every amount
 * as a decimal string ("11658.03") or null when it couldn't be read: null
 * stays null here (the screen hides it), never "$0".
 *
 * Separators follow the viewer's country like every number in the app
 * (utils/numberLocale): "1.234,56" in VE/CO/AR…, "1,234.56" in MX/PE/US….
 */
import { getSeparators } from './numberLocale';

const DECIMAL = /^([+-])?(\d+)(?:\.(\d+))?$/;

const MONTHS_ES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sept', 'oct', 'nov', 'dic'];

type ParsedDecimal = { negative: boolean; whole: string; fraction: string };

const parseDecimal = (value: string | null | undefined): ParsedDecimal | null => {
  if (value === null || value === undefined) return null;
  const match = DECIMAL.exec(String(value).trim());
  if (!match) return null;
  const whole = match[2].replace(/^0+(?=\d)/, '');
  const fraction = match[3] || '';
  const isZero = /^0*$/.test(whole) && /^0*$/.test(fraction);
  return { negative: match[1] === '-' && !isZero, whole, fraction };
};

const groupThousands = (whole: string) => whole.replace(/\B(?=(\d{3})+(?!\d))/g, getSeparators().group);
const decimalMark = () => getSeparators().decimal;

/** Keeps the server's decimals but drops trailing zeros past `minDecimals`. */
const trimFraction = (fraction: string, minDecimals: number) => {
  let out = fraction.padEnd(minDecimals, '0');
  while (out.length > minDecimals && out.endsWith('0')) out = out.slice(0, -1);
  return out;
};

/** -1, 0 or 1; null when the value is unknown. */
export const signOf = (value: string | null | undefined): -1 | 0 | 1 | null => {
  const parsed = parseDecimal(value);
  if (!parsed) return null;
  if (/^0*$/.test(parsed.whole) && /^0*$/.test(parsed.fraction)) return 0;
  return parsed.negative ? -1 : 1;
};

/** True when the value is known and exactly zero. */
export const isZeroAmount = (value: string | null | undefined) => signOf(value) === 0;

export type MoneyParts = { sign: '' | '-' | '+'; whole: string; cents: string };

/**
 * "$11,658.03" split so the cents can be set lighter: { whole: "$11,658", cents: ".03" }.
 * `signed` adds "+" to positive amounts.
 */
export const moneyParts = (
  value: string | null | undefined,
  options: { signed?: boolean; minDecimals?: number; usMark?: boolean } = {},
): MoneyParts | null => {
  const parsed = parseDecimal(value);
  if (!parsed) return null;
  const fraction = trimFraction(parsed.fraction, options.minDecimals ?? 2);
  const positive = !parsed.negative && signOf(value) === 1;
  const sign: MoneyParts['sign'] = parsed.negative ? '-' : options.signed && positive ? '+' : '';
  return {
    sign,
    // "US$" where an amount stands alone in text (a bare "$" reads as pesos).
    whole: `${sign}${options.usMark ? 'US$' : '$'}${groupThousands(parsed.whole)}`,
    cents: fraction ? `${decimalMark()}${fraction}` : '',
  };
};

/** "$11,658.03"; "+$7,412.11" with `signed`; null when unknown. */
export const formatUsd = (
  value: string | null | undefined,
  options: { signed?: boolean; minDecimals?: number; usMark?: boolean } = {},
): string | null => {
  const parts = moneyParts(value, options);
  return parts ? `${parts.whole}${parts.cents}` : null;
};

/** "12.34%" without sign (the arrow carries the direction); null when unknown. */
export const formatPctAbs = (value: string | null | undefined): string | null => {
  const parsed = parseDecimal(value);
  if (!parsed) return null;
  return `${groupThousands(parsed.whole)}${decimalMark()}${trimFraction(parsed.fraction, 2)}%`;
};

/** "+1.20%" / "-0.85%"; null when unknown. */
export const formatPctSigned = (value: string | null | undefined): string | null => {
  const abs = formatPctAbs(value);
  if (abs === null) return null;
  const sign = signOf(value);
  return `${sign === 1 ? '+' : sign === -1 ? '-' : ''}${abs}`;
};

/** A token or share amount: "1,000" for "1000.00", "0.5" for "0.500000". */
export const formatAmount = (value: string | null | undefined): string | null => {
  const parsed = parseDecimal(value);
  if (!parsed) return null;
  const fraction = trimFraction(parsed.fraction, 0);
  return `${parsed.negative ? '-' : ''}${groupThousands(parsed.whole)}${fraction ? `${decimalMark()}${fraction}` : ''}`;
};

/**
 * A share count as a profile shows it: at most 4 decimals, cut (never
 * rounded up, so a holding is never overstated), trailing zeros dropped;
 * a holding too small for that reads "< 0,0001", never zero.
 * "1.1275438811438157" → "1,1275" (VE) / "1.1275" (MX).
 */
export const formatShares = (value: string | null | undefined): string | null => {
  const parsed = parseDecimal(value);
  if (!parsed) return null;
  const fraction = parsed.fraction.slice(0, 4).replace(/0+$/, '');
  const whole = groupThousands(parsed.whole);
  if (/^0*$/.test(parsed.whole) && !fraction) {
    return /[1-9]/.test(parsed.fraction) ? `< 0${decimalMark()}0001` : '0';
  }
  return `${parsed.negative ? '-' : ''}${whole}${fraction ? `${decimalMark()}${fraction}` : ''}`;
};

/**
 * Average holding time: "12 min", "7h", "3 d". Null when unknown. The server
 * rounds it to the hour (an exact figure would date a trade), so 0 means
 * "under an hour".
 */
export const formatHoldTime = (seconds: number | null | undefined): string | null => {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return null;
  if (seconds === 0) return 'menos de 1 h';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 1) return '< 1 min';
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    const rest = minutes % 60;
    return rest ? `${hours}h ${rest}m` : `${hours}h`;
  }
  return `${Math.floor(hours / 24)} d`;
};

/** "2026-10" → "oct 2026". */
export const formatMemberSince = (value: string | null | undefined): string | null => {
  const match = /^(\d{4})-(\d{2})/.exec(value || '');
  if (!match) return null;
  const month = Number(match[2]);
  if (month < 1 || month > 12) return null;
  return `${MONTHS_ES[month - 1]} ${match[1]}`;
};

/** "2026-03-02" → "2 mar"; the year is added when it isn't the current one. */
export const formatShortDate = (value: string | null | undefined, now: Date = new Date()): string | null => {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || '');
  if (!match) return null;
  const month = Number(match[2]);
  if (month < 1 || month > 12) return null;
  const label = `${Number(match[3])} ${MONTHS_ES[month - 1]}`;
  return Number(match[1]) === now.getFullYear() ? label : `${label} ${match[1]}`;
};

/** "1 trade" / "12 trades". */
export const tradeCountLabel = (count: number) => `${count} ${count === 1 ? 'trade' : 'trades'}`;
