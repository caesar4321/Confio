// One number format for the whole app, decided by the user's country
// (phone country, like the wallet currency), for every number shown and
// every amount typed:
//   VE, AR, CO, BO, CL, EC, PY, UY, BR, ES …  1.234,56
//   MX, PE, DO, SV, GT, HN, NI, PA, US …      1,234.56
//
// Deterministic on purpose: no Intl. Hermes/Android take locale data from
// the device, so the same country can format differently per phone, and
// locales like es-ES do not group 4-digit numbers (1000 -> "1000"), which
// broke separator detection by formatting a sample number.
//
// Pure helpers read the current separators from a module-level setting that
// the app updates when the user's country is known (NumberLocaleSync), so
// formatters outside React (utils, services) follow it too.

export type Separators = { group: string; decimal: string };

const DOT_DECIMAL: Separators = { group: ',', decimal: '.' };
const COMMA_DECIMAL: Separators = { group: '.', decimal: ',' };

// Countries that write 1.234,56. Everything else uses 1,234.56.
const COMMA_DECIMAL_COUNTRIES = new Set([
  'AR', 'BO', 'BR', 'CL', 'CO', 'CR', 'CU', 'EC', 'PY', 'UY', 'VE',
  'ES', 'PT', 'DE', 'IT', 'NL', 'FR', 'BE', 'AT', 'ID', 'TR', 'RU',
]);

export function separatorsForCountry(countryIso?: string | null): Separators {
  return countryIso && COMMA_DECIMAL_COUNTRIES.has(countryIso.toUpperCase()) ? COMMA_DECIMAL : DOT_DECIMAL;
}

let current: Separators = DOT_DECIMAL;
let currentCountry: string | null = null;
const listeners = new Set<() => void>();

/** Sets the app-wide separators WITHOUT notifying (safe during render).
 *  Returns true when they changed. */
export function applyNumberLocaleCountry(countryIso?: string | null): boolean {
  const next = separatorsForCountry(countryIso);
  currentCountry = countryIso ? countryIso.toUpperCase() : null;
  if (next.decimal === current.decimal && next.group === current.group) return false;
  current = next;
  return true;
}

/** Tell subscribed components to re-render with the current separators. */
export function notifyNumberLocale() {
  listeners.forEach((l) => l());
}

/** Set + notify (tests, non-React callers). */
export function setNumberLocaleCountry(countryIso?: string | null) {
  if (applyNumberLocaleCountry(countryIso)) notifyNumberLocale();
}

export function getSeparators(): Separators {
  return current;
}

export function getNumberLocaleCountry(): string | null {
  return currentCountry;
}

export function subscribeNumberLocale(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export type FormatOptions = {
  /** Fixed number of decimals (default 2). */
  decimals?: number;
  /** Show at least this many decimals, up to `decimals` (trailing zeros trimmed). */
  minDecimals?: number;
  /** Thousands grouping (default true). */
  grouping?: boolean;
  /** Override the app-wide separators (e.g. a trade counterpart's country). */
  separators?: Separators;
};

/** Round half away from zero at `decimals`, without binary-float surprises
 *  like 1.005 -> "1.00". Returns the plain "1234.5"-style string. */
function toFixedSafe(value: number, decimals: number): string {
  if (!Number.isFinite(value)) return '0';
  const sign = value < 0 ? -1 : 1;
  const abs = Math.abs(value);
  // Shift via exponent notation to avoid 1.005 * 100 = 100.49999…
  const shifted = Number(`${abs}e${decimals}`);
  const rounded = Number.isFinite(shifted) ? Math.round(shifted) : abs;
  const back = Number.isFinite(shifted) ? Number(`${rounded}e-${decimals}`) : abs;
  return (sign * back).toFixed(decimals);
}

/** Format a number with the user's (or the given) separators. */
export function formatDecimal(value: number | string, options: FormatOptions = {}): string {
  const num = typeof value === 'number' ? value : Number(value);
  const { decimal, group } = options.separators ?? current;
  const decimals = Math.max(0, options.decimals ?? 2);
  const fixed = toFixedSafe(Number.isFinite(num) ? num : 0, decimals);
  const negative = fixed.startsWith('-');
  let [intPart, fracPart = ''] = (negative ? fixed.slice(1) : fixed).split('.');
  if (options.minDecimals !== undefined && fracPart) {
    const keep = Math.min(options.minDecimals, decimals);
    fracPart = fracPart.replace(/0+$/, '');
    if (fracPart.length < keep) fracPart = fracPart.padEnd(keep, '0');
  }
  if (options.grouping !== false) {
    intPart = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, group);
  }
  const body = fracPart ? `${intPart}${decimal}${fracPart}` : intPart;
  // "-0" is not a number anyone wants to read.
  return negative && /[1-9]/.test(body) ? `-${body}` : body;
}

/** "US$1.234,56" / "US$1,234.56". Sign goes before the prefix. */
export function formatUsdAmount(value: number | string, options: FormatOptions = {}): string {
  const text = formatDecimal(value, options);
  return text.startsWith('-') ? `-US$${text.slice(1)}` : `US$${text}`;
}

/**
 * What the user typed in an amount field -> a number (NaN if not a number).
 *
 * Tolerant on purpose: the keypad shows the DEVICE locale's decimal key,
 * which may differ from the user's country, and people paste amounts:
 *  - one '.' or ',' followed by 1-2 (or more than 3) digits = decimal mark
 *    ("12,5", "12.5", "0,123456" for tokens);
 *  - a mark followed by exactly 3 digits = the country's grouping if it is
 *    the country's group mark ("1.234" in VE = 1234), else decimal;
 *  - both marks present: the LAST one is the decimal mark ("1.234,56");
 *  - the same mark repeated = grouping ("1.234.567").
 */
export function parseAmountInput(text: string | null | undefined, separators: Separators = current): number {
  const canonical = normalizeAmountInput(text, separators);
  return canonical === null ? NaN : Number(canonical);
}

/** Same rules as parseAmountInput, but returns the canonical "1234.56"
 *  string (or null): exact, for code that must not go through floats. */
export function normalizeAmountInput(text: string | null | undefined, separators: Separators = current): string | null {
  if (text == null) return null;
  const cleaned = String(text).replace(/[\s\u00a0'’]/g, '').replace(/^US\$|^\$/, '');
  if (!cleaned) return null;
  if (!/^-?[0-9.,]+$/.test(cleaned) || !/[0-9]/.test(cleaned)) return null;
  const negative = cleaned.startsWith('-');
  const body = negative ? cleaned.slice(1) : cleaned;
  const dots = (body.match(/\./g) || []).length;
  const commas = (body.match(/,/g) || []).length;
  let normalized: string;
  if (dots && commas) {
    const decimalMark = body.lastIndexOf('.') > body.lastIndexOf(',') ? '.' : ',';
    const groupMark = decimalMark === '.' ? ',' : '.';
    if ((decimalMark === '.' ? dots : commas) > 1) return null;
    // Real grouping only: "1.234,56" yes, "1,2.3" no (groups are 3 digits).
    const intPart = body.slice(0, body.lastIndexOf(decimalMark));
    const groups = intPart.split(groupMark);
    if (!(groups[0].length >= 1 && groups[0].length <= 3 && groups.slice(1).every((g) => g.length === 3))) return null;
    normalized = body.split(groupMark).join('').replace(decimalMark, '.');
  } else if (dots + commas === 0) {
    normalized = body;
  } else {
    const mark = dots ? '.' : ',';
    const count = dots || commas;
    if (count > 1) {
      // "1.234.567": grouping only when every group has 3 digits.
      const groups = body.split(mark);
      if (!groups.slice(1).every((g) => g.length === 3)) return null;
      normalized = groups.join('');
    } else {
      const [intPart, fracPart] = body.split(mark);
      const isGroup = fracPart.length === 3 && intPart.length > 0 && mark === separators.group;
      normalized = isGroup ? `${intPart}${fracPart}` : `${intPart || '0'}.${fracPart}`;
    }
  }
  if (!/^\d*\.?\d*$/.test(normalized) || normalized === '.' || normalized === '') return null;
  return negative ? `-${normalized}` : normalized;
}

/**
 * Clean what the user is typing into an amount field: digits and ONE
 * decimal mark (either key), shown with the user's decimal mark, decimals
 * capped. No grouping while typing (it would fight the cursor).
 */
/** True when `next` differs from `prev` by one typed/deleted/replaced
 *  character. Anything else (paste, paste over a selection, autofill) is a
 *  whole new value. */
function isSingleKeystroke(prev: string, next: string): boolean {
  const diff = next.length - prev.length;
  if (Math.abs(diff) > 1) return false;
  let start = 0;
  while (start < prev.length && start < next.length && prev[start] === next[start]) start += 1;
  let endPrev = prev.length - 1;
  let endNext = next.length - 1;
  while (endPrev >= start && endNext >= start && prev[endPrev] === next[endNext]) { endPrev -= 1; endNext -= 1; }
  // At most one character changed between the common prefix and suffix.
  return endPrev - start + 1 <= 1 && endNext - start + 1 <= 1;
}

export function sanitizeAmountInput(
  text: string,
  maxDecimals = 2,
  separators: Separators = current,
  /** The field's value before this change: tells a paste from typing. */
  previous?: string,
): string {
  // A whole number arriving at once (paste: "1.234,56", "1,234.56",
  // "1.234.567", or VE "1.234" = 1234) must keep its value, not have its
  // first mark read as the decimal (that turned 1.234,56 into 1,23456 and a
  // pasted VE "1.234" into 1,234). Key-by-key typing keeps the simple rule:
  // either decimal key = the decimal mark.
  const raw = String(text).trim();
  const dots = (raw.match(/\./g) || []).length;
  const commas = (raw.match(/,/g) || []).length;
  const pasted = previous !== undefined && !isSingleKeystroke(String(previous), raw);
  if ((dots && commas) || dots > 1 || commas > 1 || (pasted && dots + commas === 1)) {
    const canonical = normalizeAmountInput(raw, separators);
    if (canonical !== null && !canonical.startsWith('-')) {
      return toAmountInput(Number(canonical), maxDecimals, separators);
    }
  }
  let out = '';
  let seenMark = false;
  let decimalsTyped = 0;
  for (const ch of String(text)) {
    if (ch >= '0' && ch <= '9') {
      if (seenMark) {
        if (decimalsTyped >= maxDecimals) continue;
        decimalsTyped += 1;
      }
      out += ch;
    } else if ((ch === '.' || ch === ',') && !seenMark && maxDecimals > 0) {
      seenMark = true;
      out += separators.decimal;
    }
  }
  if (out.startsWith(separators.decimal)) out = `0${out}`;
  return out;
}

/** A plain number as an editable amount string with the user's decimal mark
 *  (e.g. pre-filling "Max" into an input). TRUNCATES to `maxDecimals`, never
 *  rounds up: a Max prefill must not exceed the balance it came from. */
export function toAmountInput(value: number, maxDecimals = 2, separators: Separators = current): string {
  if (!Number.isFinite(value)) return '';
  const factor = 10 ** maxDecimals;
  // Exponent shift avoids 1.13 * 100 = 112.99999 truncating to 1.12.
  const shifted = Number(`${Math.abs(value)}e${maxDecimals}`);
  const truncated = Math.trunc(Number.isFinite(shifted) ? shifted : Math.abs(value) * factor) / factor;
  const fixed = (Math.sign(value) * truncated).toFixed(maxDecimals).replace(/\.?0+$/, '');
  return fixed.replace('.', separators.decimal);
}

/** A percentage number (no "%"), up to `maxDecimals`, trailing zeros
 *  trimmed: 0.9 -> "0,9" (VE) / "0.9" (MX); 1 -> "1". */
export function formatPercent(value: number, maxDecimals = 2, separators?: Separators): string {
  return formatDecimal(value, { decimals: maxDecimals, minDecimals: 0, separators });
}

/**
 * A server/canonical amount string ("12.50", "-3.1", "+20", 7) shown with the
 * user's separators, keeping its sign and exactly the decimals it has (up to
 * 6). Anything that is not a plain number is returned unchanged.
 */
export function formatAmountString(raw: string | number | null | undefined): string {
  if (raw === null || raw === undefined) return '';
  const text = String(raw).trim();
  const match = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(text);
  if (!match) return text;
  const [, sign, , frac = ''] = match;
  const decimals = Math.min(frac.length, 6);
  const body = formatDecimal(Number(text.replace(/^[+-]/, '')), { decimals, minDecimals: decimals });
  return `${sign}${body}`;
}
