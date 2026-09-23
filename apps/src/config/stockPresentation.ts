// Presentation only: trading symbols and server market-cap ranking stay intact.
export const FEATURED_STOCK_TICKERS = ['SPY', 'QQQ', 'GLD', 'SLV'] as const;

// Short display names only. The "what is this" explanation is served by the
// server (gmAssetDescription) so copy can be fixed without an app release.
export const STOCK_PRESENTATION: Record<string, {name: string}> = {
  SPY: {name: 'S&P 500'},
  QQQ: {name: 'NASDAQ 100'},
  GLD: {name: 'Oro'},
  SLV: {name: 'Plata'},
  GOOGL: {name: 'Google (Clase A)'},
  GOOG: {name: 'Google (Clase C)'},
};

/**
 * One line per starter-shelf card: what you get, in plain words. Factual, not
 * promotional — no "safe", no "refugio" (gold falls too) — and no risk
 * sermon either; the disclosure lives in its layered places (footer, info).
 */
export const STOCK_TAGLINES: Record<string, string> = {
  SPY: '500 grandes empresas en una compra',
  QQQ: '100 grandes empresas, muchas de tecnología',
  GLD: 'Sube y baja con el oro',
  SLV: 'Sube y baja con la plata',
};

/** Input is already ranked by market capitalization by gmMarket. */
export const prioritizeStocks = <T extends {ticker: string}>(stocks: T[]): T[] => {
  const featured = new Set<string>(FEATURED_STOCK_TICKERS);
  return [
    ...FEATURED_STOCK_TICKERS.flatMap(ticker => stocks.filter(stock => stock.ticker === ticker)),
    ...stocks.filter(stock => !featured.has(stock.ticker)),
  ];
};
