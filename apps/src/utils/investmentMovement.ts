// Ledger rows for investment trades carry a description prefix the server
// sets (cusd_plus/unified.py): "Ondo Stocks: " for U.S. stocks, "Cripto: "
// for Bitcoin and other coins, "Oro: " for gold, "Futuros: " for a Futuros
// margin out or proceeds home. Everything that treats a
// stock trade as an internal settlement (no stranger, no counterparty
// lookup, its own title and glyph) keys on all three.

export const INVESTMENT_PREFIXES = ['Ondo Stocks: ', 'Cripto: ', 'Oro: ', 'Futuros: '] as const;

export const investmentPrefix = (description?: string | null): string | null => {
  if (typeof description !== 'string') return null;
  return INVESTMENT_PREFIXES.find((prefix) => description.startsWith(prefix)) ?? null;
};

export const isInvestmentMovement = (description?: string | null): boolean =>
  investmentPrefix(description) !== null;

/** The row title: the description after its prefix, or undefined. */
export const investmentTitle = (description?: string | null): string | undefined => {
  const prefix = investmentPrefix(description);
  return prefix ? (description as string).slice(prefix.length) : undefined;
};
