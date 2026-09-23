import {prioritizeStocks} from '../stockPresentation';

describe('stock discovery order', () => {
  it('pins the four featured assets and preserves market-cap order for the rest', () => {
    const tickers = ['NVDA', 'AAPL', 'GOOGL', 'QQQ', 'SPY', 'SLV', 'GLD', 'SMALL'];
    const stocks = tickers.map(ticker => ({ticker}));
    expect(prioritizeStocks(stocks).map(stock => stock.ticker)).toEqual([
      'SPY', 'QQQ', 'GLD', 'SLV', 'NVDA', 'AAPL', 'GOOGL', 'SMALL',
    ]);
    expect(stocks.map(stock => stock.ticker)).toEqual(tickers);
  });

  it('does not reintroduce unavailable assets or filtered-out search results', () => {
    const stocks = [{ticker: 'GOOGL'}, {ticker: 'GLD'}, {ticker: 'GOOG'}];
    expect(prioritizeStocks(stocks)).toEqual([stocks[1], stocks[0], stocks[2]]);
    expect(prioritizeStocks([])).toEqual([]);
  });
});
