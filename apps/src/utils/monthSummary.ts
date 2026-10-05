import { formatUsdAmount } from './numberLocale';
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
 * AR/CO/MX. `whole` drops cents (summary screens: one precision, whole
 * dollars; amounts under US$1 keep cents so they never read as US$0, while
 * an exact zero is US$0).
 */
export function formatUsd(amount: string | number, { whole = false }: { whole?: boolean } = {}): string {
  const value = typeof amount === 'number' ? amount : Number(amount);
  if (!Number.isFinite(value)) return 'US$—';
  // Exactly zero is "US$0" (a quiet month), never "US$0.00".
  const digits = whole && (Math.abs(value) >= 1 || value === 0) ? 0 : 2;
  // The user's country separators (utils/numberLocale): US$1.234 in VE.
  return formatUsdAmount(value, { decimals: digits });
}

/** "+US$4.20" / "−US$3.10": cents and a true minus sign (no alarm color implied). */
export function signedUsd(amount: number): string {
  const text = formatUsdAmount(Math.abs(amount), { decimals: 2 });
  return amount < 0 ? `−${text}` : `+${text}`;
}

export const MASK = '••••';

// Same keys and order as the server (users/models_cashflow.py).
export const CATEGORY_META: Record<CategoryKey, { label: string; icon: string }> = {
  food: { label: 'Comida', icon: 'coffee' },
  transport: { label: 'Transporte', icon: 'truck' },
  home: { label: 'Casa', icon: 'home' },
  bills: { label: 'Servicios', icon: 'zap' },
  family: { label: 'Familia', icon: 'users' },
  // Not shopping-bag / heart: the money-list vocabulary already uses those
  // for a merchant payment and a donation (components/icons/vocabulary.ts).
  shopping: { label: 'Compras', icon: 'shopping-cart' },
  health: { label: 'Salud', icon: 'activity' },
  education: { label: 'Educación', icon: 'book-open' },
  leisure: { label: 'Salidas', icon: 'film' },
  debt: { label: 'Deudas', icon: 'credit-card' },
  work: { label: 'Trabajo', icon: 'briefcase' },
  other: { label: 'Otro', icon: 'more-horizontal' },
};

export const CATEGORY_ORDER: CategoryKey[] = [
  'food', 'transport', 'home', 'bills', 'family', 'shopping',
  'health', 'education', 'leisure', 'debt', 'work', 'other',
];

/** The success-screen prompt shows these first; "Más" reveals the rest. */
export const QUICK_CATEGORY_COUNT = 6;

export function categoryLabel(category: string | null | undefined): string {
  if (!category || category === 'uncategorized') return 'Sin categoría';
  return CATEGORY_META[category as CategoryKey]?.label ?? 'Sin categoría';
}
