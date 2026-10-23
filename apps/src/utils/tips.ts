// Tips (inbox/tips.py on the server, which enforces all of this).
export const TIP_MIN = '0.50';
export const TIP_MAX = '200';
export const TIP_CHIPS = [1, 2, 5, 10] as const;

/** "5" → "5.00"; null when not a valid tip amount (0.50–200, at most 2 decimals). */
export const parseTipAmount = (text: string): string | null => {
  const clean = (text || '').trim();
  if (!/^\d{1,3}(\.\d{0,2})?$/.test(clean)) return null;
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
