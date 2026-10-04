// Shared helpers for "Tu mes" (month summary): labels, money formatting,
// timezone. Copy is Spanish (user-facing); identifiers are English.
import type { CategoryKey } from '../apollo/monthSummary';

export const MONTHS_ES = [
  'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
  'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
];

export function monthName(month: number): string {
  return MONTHS_ES[(month - 1 + 12) % 12] ?? '';
}

export function capitalize(text: string): string {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

export function previousMonth(year: number, month: number): { year: number; month: number } {
  return month === 1 ? { year: year - 1, month: 12 } : { year, month: month - 1 };
}

export function nextMonth(year: number, month: number): { year: number; month: number } {
  return month === 12 ? { year: year + 1, month: 1 } : { year, month: month + 1 };
}

/** Device IANA timezone (the server falls back to the phone country). */
export function deviceTimezone(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || undefined;
  } catch {
    return undefined;
  }
}

/** Calendar month in the device's local time. */
export function currentYearMonth(now: Date = new Date()): { year: number; month: number } {
  return { year: now.getFullYear(), month: now.getMonth() + 1 };
}

/**
 * "US$1,234.56". Always "US$" (design 5A): a bare "$" reads as pesos in
 * AR/CO/MX. `whole` drops cents for big headline numbers.
 */
export function formatUsd(amount: string | number, { whole = false }: { whole?: boolean } = {}): string {
  const value = typeof amount === 'number' ? amount : Number(amount);
  if (!Number.isFinite(value)) return 'US$—';
  const abs = Math.abs(value);
  const digits = whole && abs >= 100 ? 0 : 2;
  const text = abs.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${value < 0 ? '-' : ''}US$${text}`;
}

export const MASK = '••••';

export const CATEGORY_META: Record<CategoryKey, { label: string; icon: string }> = {
  food: { label: 'Comida', icon: 'coffee' },
  transport: { label: 'Transporte', icon: 'truck' },
  home: { label: 'Casa', icon: 'home' },
  family: { label: 'Familia', icon: 'users' },
  work: { label: 'Trabajo', icon: 'briefcase' },
  other: { label: 'Otro', icon: 'more-horizontal' },
};

export const CATEGORY_ORDER: CategoryKey[] = ['food', 'transport', 'home', 'family', 'work', 'other'];

export function categoryLabel(category: string | null | undefined): string {
  if (!category || category === 'uncategorized') return 'Sin categoría';
  return CATEGORY_META[category as CategoryKey]?.label ?? 'Sin categoría';
}
