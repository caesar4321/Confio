// Tips (inbox/tips.py on the server, which enforces all of this).
import { normalizeAmountInput } from './numberLocale';

// The same $1 floor as any dollar send (server: inbox/tips.MIN_USD).
export const TIP_MIN = '1';
export const TIP_MAX = '200';
export const TIP_CHIPS = [1, 2, 5, 10] as const;

/** What was typed, in the user's country format ("5", "2,50" in VE, "2.50"
 * in MX) → the canonical "2.50"; null when not a valid tip amount
 * (1–200, at most 2 decimals). */
export const parseTipAmount = (text: string): string | null => {
  const clean = normalizeAmountInput(text);
  if (clean === null || !/^\d{1,3}(\.\d{0,2})?$/.test(clean)) return null;
  const value = Number(clean);
  if (!Number.isFinite(value) || value < Number(TIP_MIN) || value > Number(TIP_MAX)) return null;
  return value.toFixed(2);
};

/** A Propina, from a list row, a refetch or a push payload. Tips are keyed
 * "tip-…" and pushes say is_tip; either is enough. */
export const isTipTransaction = (tx: any): boolean => {
  if (!tx) return false;
  const flag = tx.is_tip ?? tx.isTip;
  if (flag === true || (typeof flag === 'string' && flag.trim().toLowerCase() === 'true')) return true;
  return String(tx.idempotencyKey || tx.idempotency_key || '').startsWith('tip-');
};
