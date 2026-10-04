// Pure rules for the Tu mes insight cards (docs/designs/tu-mes-insights.md).
// No React here, so every rule is unit-tested on its own.
import type { MonthSummary, ProtectionValue, SavingsEarned } from '../apollo/monthSummary';
import { formatDecimal } from './numberLocale';
import { capitalize, monthName } from './monthSummary';

export const PACE_MIN_DAY = 5;          // §6: the pace line starts on day 5
export const PROJECTION_MIN_DAY = 7;    // §6: the projection starts on day 7
export const MIN_SAVINGS_USD = 0.01;    // B' hides below one cent (R20)
export const SPARK_MIN_DAYS = 3;        // design 5A: fewer days → number only
export const RECURRING_VISIBLE = 3;     // design 11A: then "+N más"

const LESS = 0.9;
const MORE = 1.1;

export type PaceTone = 'less' | 'same' | 'more';

/** Same-period comparison: this month's Salió to date vs last month's up to
 *  the same day (monthSummary.previous while the month is running). */
export function paceTone(currentSpending: number, comparableSpending: number): PaceTone {
  if (comparableSpending <= 0) return currentSpending > 0 ? 'more' : 'same';
  const ratio = currentSpending / comparableSpending;
  if (ratio <= LESS) return 'less';
  if (ratio >= MORE) return 'more';
  return 'same';
}

/** Copy per tone: warm for personal accounts, plain facts for businesses
 *  (design review 12B). `month` is lowercase ("septiembre"). */
export function paceCopy(tone: PaceTone, month: string, business: boolean): string {
  if (business) {
    if (tone === 'less') return `Hasta hoy salió menos que a esta altura de ${month}`;
    if (tone === 'more') return `Hasta hoy salió más que a esta altura de ${month}`;
    return `Hasta hoy salió parecido a ${month}`;
  }
  if (tone === 'less') return `Vas bien: gastas menos que en ${month}`;
  if (tone === 'more') return `Vas gastando más que en ${month}`;
  return `Vas parecido a ${month}`;
}

/** Linear pace only (R24): Salió so far ÷ days elapsed × days in month. */
export function projection(spendingToDate: number, dayOfMonth: number, daysInMonth: number): number {
  if (dayOfMonth <= 0) return 0;
  return (spendingToDate / dayOfMonth) * daysInMonth;
}

export function daysIn(year: number, month: number): number {
  return new Date(year, month, 0).getDate();
}

export type PaceLine = {
  tone: PaceTone;
  verdict: string;
  /** null before day 7 */
  projectionUsd: number | null;
  previousMonthLabel: string;   // "Septiembre"
  previousMonthUsd: number;
};

/** The pace line inside Card A, or null when it doesn't apply (not the
 *  current month, before day 5, or last month had no Salió at all). */
export function paceLine(
  summary: MonthSummary,
  previousMonthSpendingUsd: string | null | undefined,
  today: Date,
  business: boolean,
): PaceLine | null {
  const isCurrent = summary.year === today.getFullYear() && summary.month === today.getMonth() + 1;
  const day = today.getDate();
  const fullPrevious = Number(previousMonthSpendingUsd);
  if (!isCurrent || day < PACE_MIN_DAY || !Number.isFinite(fullPrevious) || fullPrevious <= 0) return null;
  const spending = Number(summary.current.spendingUsd);
  const comparable = Number(summary.previous.spendingUsd);
  const tone = paceTone(spending, comparable);
  const prev = summary.month === 1 ? 12 : summary.month - 1;
  return {
    tone,
    verdict: paceCopy(tone, monthName(prev), business),
    projectionUsd: day >= PROJECTION_MIN_DAY ? projection(spending, day, daysIn(summary.year, summary.month)) : null,
    previousMonthLabel: capitalize(monthName(prev)),
    previousMonthUsd: fullPrevious,
  };
}

/** Which card fills the dollar slot (R21): protection when the server could
 *  prove it, otherwise savings earned (≥ one cent), otherwise nothing. */
export type DollarSlot =
  | { kind: 'protection'; value: ProtectionValue }
  | { kind: 'savings'; value: SavingsEarned }
  | null;

export function dollarSlot(protection: ProtectionValue | null | undefined,
  savings: SavingsEarned | null | undefined): DollarSlot {
  if (protection) return { kind: 'protection', value: protection };
  if (savings && Number(savings.earnedUsd) >= MIN_SAVINGS_USD) return { kind: 'savings', value: savings };
  return null;
}

/** Design 7A: a pill is grey when its full date is before today. */
export function isPastDay(year: number, month: number, day: number, today: Date): boolean {
  const date = new Date(year, month - 1, day);
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  return date.getTime() < start.getTime();
}

const MONTH_SHORT = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];

/** "5 oct" */
export function shortDate(month: number, day: number): string {
  return `${day} ${MONTH_SHORT[(month - 1 + 12) % 12]}`;
}

const LOCAL_SYMBOL: Record<string, string> = { BOB: 'Bs', VES: 'Bs', ARS: '$' };

/** "Bs 3.990" (whole) or "Bs 36,50" (rates): the user's separators. */
export function formatLocal(amount: string | number, currency: string, decimals = 0): string {
  const symbol = LOCAL_SYMBOL[currency] ?? currency;
  return `${symbol} ${formatDecimal(amount, { decimals })}`;
}

/** "hoy, 10:42" or "3 oct, 10:42" in the device's local time. */
export function quoteTime(iso: string, now: Date = new Date()): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return '';
  const hh = String(at.getHours()).padStart(2, '0');
  const mm = String(at.getMinutes()).padStart(2, '0');
  const sameDay = at.toDateString() === now.toDateString();
  return `${sameDay ? 'hoy' : shortDate(at.getMonth() + 1, at.getDate())}, ${hh}:${mm}`;
}
