import { mergeLive, parseBbo, parseCandle } from '../useMarketStream';

// Shapes as Hyperliquid's feed sent them (probed 2026-10-27).
const feedCandle = { t: 1793143740000, T: 1793143799999, s: 'BTC', i: '1m', o: '80911.0', c: '80910.0',
  h: '80911.0', l: '80910.0', v: '0.7847', n: 28 };
const feedBbo = { coin: 'xyz:GOLD', time: 1793143772144,
  bbo: [{ px: '4063.1', sz: '1.8487', n: 4 }, { px: '4063.2', sz: '35.5863', n: 9 }] };

const c = (time: number, close = 1) => ({ time, open: 1, high: 2, low: 0.5, close, volume: 1 });

describe('useMarketStream parsing', () => {
  it('reads a feed candle', () => {
    expect(parseCandle(feedCandle, 'BTC', '1m')).toEqual({
      time: 1793143740000, open: 80911, high: 80911, low: 80910, close: 80910, volume: 0.7847 });
  });

  it('ignores another coin, another interval, or a broken price', () => {
    expect(parseCandle(feedCandle, 'ETH', '1m')).toBeNull();
    expect(parseCandle(feedCandle, 'BTC', '5m')).toBeNull();
    expect(parseCandle({ ...feedCandle, h: 'x' }, 'BTC', '1m')).toBeNull();
    expect(parseCandle({ ...feedCandle, t: '1' }, 'BTC', '1m')).toBeNull();
  });

  it('reads bid and ask, and refuses a missing side or a crossed book', () => {
    expect(parseBbo(feedBbo, 'xyz:GOLD', 5)).toEqual({ bid: 4063.1, ask: 4063.2, at: 5 });
    expect(parseBbo(feedBbo, 'BTC', 5)).toBeNull();
    expect(parseBbo({ ...feedBbo, bbo: [null, feedBbo.bbo[1]] }, 'xyz:GOLD', 5)).toBeNull();
    expect(parseBbo({ ...feedBbo, bbo: [feedBbo.bbo[1], feedBbo.bbo[0]] }, 'xyz:GOLD', 5)).toBeNull();
  });
});

describe('mergeLive', () => {
  it('lays streamed candles over the history and starts the next one', () => {
    const history = [c(1), c(2)];
    expect(mergeLive(history, [c(2, 9)]).map((x) => [x.time, x.close])).toEqual([[1, 1], [2, 9]]);
    expect(mergeLive(history, [c(3, 9)]).map((x) => x.time)).toEqual([1, 2, 3]);
    expect(mergeLive(history, [])).toBe(history);
    expect(mergeLive([], [c(3)])).toEqual([]);
  });

  it('keeps a closed candle\'s streamed final values after the next one starts', () => {
    // The server's copy of candle 2 is from before it closed (close 1, volume 1).
    const merged = mergeLive([c(1), c(2)], [{ ...c(2, 109), volume: 100 }, c(3, 110)]);
    expect(merged.map((x) => [x.time, x.close, x.volume])).toEqual([[1, 1, 1], [2, 109, 100], [3, 110, 1]]);
  });

  it('never adds candles older than the history', () => {
    expect(mergeLive([c(5), c(6)], [c(1, 9)]).map((x) => x.time)).toEqual([5, 6]);
  });
});
