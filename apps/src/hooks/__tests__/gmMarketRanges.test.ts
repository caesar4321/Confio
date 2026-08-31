import {
  gmApiRangeFor,
  gmClosesForRange,
  gmOhlcState,
  GM_RANGES,
  GM_RANGE_ACCESSIBILITY_LABELS,
} from '../useGmMarket';

const MINUTE = 60 * 1000;
const candles = Array.from({length: 97}, (_, index) => ({
  timestamp: index * 15 * MINUTE,
  close: index,
}));

describe('GM chart ranges', () => {
  it('offers intraday ranges before the existing ranges', () => {
    expect(GM_RANGES).toEqual([
      '1H',
      '6H',
      '12H',
      '1D',
      '1M',
      '3M',
      '6M',
      '1Y',
      'MAX',
    ]);
    expect(
      GM_RANGES.map(range => GM_RANGE_ACCESSIBILITY_LABELS[range]),
    ).toEqual([
      '1 hora',
      '6 horas',
      '12 horas',
      '1 día',
      '1 mes',
      '3 meses',
      '6 meses',
      '1 año',
      'Máximo',
    ]);
  });

  it.each(['1H', '6H', '12H'] as const)(
    '%s reuses the supported 1D API request',
    range => {
      expect(gmApiRangeFor(range)).toBe('1D');
    },
  );

  it('selects the last hour from 15-minute candles', () => {
    expect(gmClosesForRange(candles, '1H')).toEqual([92, 93, 94, 95, 96]);
  });

  it('selects the last 6 and 12 hours from the same real series', () => {
    expect(gmClosesForRange(candles, '6H')).toHaveLength(25);
    expect(gmClosesForRange(candles, '12H')).toHaveLength(49);
  });

  it('does not trim provider-backed longer ranges', () => {
    expect(gmApiRangeFor('1M')).toBe('1M');
    expect(gmClosesForRange(candles, '1D')).toHaveLength(candles.length);
  });

  it('anchors short windows to the newest candle rather than wall-clock time', () => {
    const pausedMarketCandles = [
      {timestamp: 1_000, close: 10},
      {timestamp: 1_000 + 30 * MINUTE, close: 11},
      {timestamp: 1_000 + 60 * MINUTE, close: 12},
    ];

    expect(gmClosesForRange(pausedMarketCandles, '1H')).toEqual([10, 11, 12]);
  });

  it('preserves honest empty and single-candle intraday states for the UI', () => {
    expect(gmClosesForRange([], '1H')).toEqual([]);
    expect(gmClosesForRange([{timestamp: 1_000, close: 10}], '1H')).toEqual([
      10,
    ]);
  });

  it('distinguishes an empty upstream failure from sparse market data', () => {
    expect(gmOhlcState([], '1H', true, false, true)).toEqual({
      closes: [],
      loading: false,
      failed: true,
    });
    expect(
      gmOhlcState([{timestamp: 1_000, close: 10}], '1H', true, false, true),
    ).toEqual({closes: [10], loading: false, failed: false});
  });
});
