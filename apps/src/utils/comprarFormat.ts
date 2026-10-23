import { formatDecimal, formatPercent, formatUsdAmount } from './numberLocale';

// Every Comprar number follows the app-wide format of the USER's country
// (utils/numberLocale: VE/AR/CO/BO… 1.234,56 · MX/PE/US… 1,234.56), never a
// fixed locale and never the device's.

const SYMBOLS: Record<string, string> = { BOB: 'Bs', VES: 'Bs.', ARS: '$', COP: '$', PEN: 'S/', MXN: '$', USD: 'US$' };

/** "210 Bs" / "S/ 35" — Bolivia writes the symbol after the amount. */
export const formatLocalPrice = (amount: string | number, currency: string): string => {
  const n = Number(amount);
  const text = Number.isFinite(n) ? formatDecimal(n, { decimals: n % 1 ? 2 : 0 }) : String(amount);
  const symbol = SYMBOLS[currency] || currency;
  return currency === 'BOB' || currency === 'VES' ? `${text} ${symbol}` : `${symbol} ${text}`;
};

/** "8%" / "7,5%" from basis points (server-provided; never hardcoded). */
export const formatFeeBps = (bps?: number | null): string | null => {
  if (bps === null || bps === undefined || !Number.isFinite(bps)) return null;
  return `${formatPercent(bps / 100, 2)}%`;
};

/** "≈ 208,80 Bs" — the display-only local reference, or null without one. */
export const formatReference = (ref?: { amount?: string | null; currency?: string | null } | null): string | null =>
  ref?.amount && ref.currency ? `≈ ${formatLocalPrice(ref.amount, ref.currency)}` : null;

/** "US$1.234,56" / "US$1,234.56", like every other dollar amount in the app. */
export const formatUsd = (amount: string | number): string => {
  const n = Number(amount);
  return Number.isFinite(n) ? formatUsdAmount(n) : `US$${amount}`;
};

/** A store's average rating: "4,5" / "4.5". */
export const formatRating = (avg: string | number): string => formatDecimal(Number(avg), { decimals: 1 });
