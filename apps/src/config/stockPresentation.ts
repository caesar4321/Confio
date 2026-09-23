// Presentation only: trading symbols and server market-cap ranking stay intact.
export const FEATURED_STOCK_TICKERS = ['SPY', 'QQQ', 'GLD', 'SLV'] as const;

export const STOCK_PRESENTATION: Record<string, {name: string; description: string}> = {
  SPY: {
    name: 'S&P 500',
    description: 'SPY sigue al índice S&P 500, que reúne a unas 500 grandes empresas de Estados Unidos. Aquí accedes a su versión digital de Ondo.',
  },
  GLD: {
    name: 'Oro',
    description: 'GLD busca reflejar el precio del oro, descontando sus gastos. Aquí accedes a su versión digital de Ondo; no recibes oro físico.',
  },
  SLV: {
    name: 'Plata',
    description: 'SLV busca reflejar el precio de la plata, descontando sus gastos. Aquí accedes a su versión digital de Ondo; no recibes plata física.',
  },
  QQQ: {
    name: 'NASDAQ 100',
    description: 'QQQ sigue al índice Nasdaq-100, que reúne a 100 de las mayores empresas no financieras que cotizan en Nasdaq. Aquí accedes a su versión digital de Ondo.',
  },
  GOOGL: {
    name: 'Google (Clase A)',
    description: 'GOOGL y GOOG corresponden a Alphabet, la empresa matriz de Google. La acción Clase A (GOOGL) tiene un voto por acción; la Clase C (GOOG) no tiene voto. Cotizan por separado y sus precios pueden diferir. Estos derechos corresponden a las acciones originales y no se transfieren automáticamente al token de Ondo.',
  },
  GOOG: {
    name: 'Google (Clase C)',
    description: 'GOOG y GOOGL corresponden a Alphabet, la empresa matriz de Google. La acción Clase C (GOOG) no tiene voto; la Clase A (GOOGL) tiene un voto por acción. Cotizan por separado y sus precios pueden diferir. Estos derechos corresponden a las acciones originales y no se transfieren automáticamente al token de Ondo.',
  },
};

/**
 * One line per starter-shelf card: what you get, in plain words. Factual, not
 * promotional — no "safe", no "refugio" (gold falls too) — and no risk
 * sermon either; the disclosure lives in its layered places (footer, info).
 */
export const STOCK_TAGLINES: Record<string, string> = {
  SPY: '500 grandes empresas en una compra',
  QQQ: 'Sigue al índice Nasdaq-100',
  GLD: 'Sigue el precio del oro',
  SLV: 'Sigue el precio de la plata',
};

/** Input is already ranked by market capitalization by gmMarket. */
export const prioritizeStocks = <T extends {ticker: string}>(stocks: T[]): T[] => {
  const featured = new Set<string>(FEATURED_STOCK_TICKERS);
  return [
    ...FEATURED_STOCK_TICKERS.flatMap(ticker => stocks.filter(stock => stock.ticker === ticker)),
    ...stocks.filter(stock => !featured.has(stock.ticker)),
  ];
};
