// Display names for the tokens that appear on receipts, success screens and
// transaction details.
//
// This existed as five identical private copies across the payment/receipt
// screens, none of which knew about the BSC tokens — so a cUSD+ receipt showed
// the raw wire value "CUSD_PLUS" as its denomination. One table, one place to
// add the next token.

const TOKEN_LABELS: Record<string, string> = {
  CUSD: 'cUSD',
  CUSD_PLUS: 'cUSD+',
  CONFIO: 'CONFIO',
  USDC: 'USDC',
  USDT: 'USDT',
};

/**
 * Wire value ("CUSD_PLUS") → what a user should read ("cUSD+").
 *
 * Unknown tokens pass through unchanged: a new server-side token shows its
 * raw symbol rather than vanishing from a receipt. Already-formatted input
 * ("cUSD+") also passes through, so this is safe to apply twice.
 */
export const formatTokenLabel = (currency?: string | null): string => {
  const raw = String(currency ?? '').trim();
  if (!raw) return '';
  const key = raw.toUpperCase().replace(/[\s-]/g, '_');
  return TOKEN_LABELS[key] ?? raw;
};

/** Dollar-denominated tokens take a "$"; CONFIO is a token COUNT and never does. */
export const isDollarToken = (currency?: string | null): boolean =>
  formatTokenLabel(currency) !== 'CONFIO';

/**
 * The full amount string for a receipt: "$12.34 cUSD+" or "10 CONFIO".
 */
export const formatTokenAmount = (
  amount: string | number,
  currency?: string | null,
): string => {
  const label = formatTokenLabel(currency);
  const value = String(amount ?? '').trim();
  return isDollarToken(currency) ? `$${value} ${label}`.trim() : `${value} ${label}`.trim();
};
