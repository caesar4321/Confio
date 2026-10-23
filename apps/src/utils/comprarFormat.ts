const SYMBOLS: Record<string, string> = { BOB: 'Bs', VES: 'Bs.', ARS: '$', COP: '$', PEN: 'S/', MXN: '$', USD: 'US$' };

/** "210 Bs" / "S/ 35" — Bolivia writes the symbol after the amount. */
export const formatLocalPrice = (amount: string | number, currency: string): string => {
  const n = Number(amount);
  const text = Number.isFinite(n)
    ? n.toLocaleString('es-BO', { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 })
    : String(amount);
  const symbol = SYMBOLS[currency] || currency;
  return currency === 'BOB' || currency === 'VES' ? `${text} ${symbol}` : `${symbol} ${text}`;
};

/** "8%" / "7,5%" from basis points (server-provided; never hardcoded). */
export const formatFeeBps = (bps?: number | null): string | null => {
  if (bps === null || bps === undefined || !Number.isFinite(bps)) return null;
  const pct = bps / 100;
  return `${pct.toLocaleString('es-BO', { maximumFractionDigits: 2 })}%`;
};

export const formatUsd = (amount: string | number): string => {
  const n = Number(amount);
  return `US$ ${Number.isFinite(n) ? n.toFixed(2) : amount}`;
};
