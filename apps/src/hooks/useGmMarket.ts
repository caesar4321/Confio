// Ondo Stocks (GM) market data — single wiring point for the Acciones screens.
//
// LIVE since 2026-07-07: the server proxies the Ondo GM Backend API
// (cusd_plus/gm_api.py, x-api-key server-side only, cached per Ondo's
// endpoint-caching guidance) and this hook consumes the gmMarket GraphQL
// query. 438 assets with real prices, 24h change, 24h sparkline and the
// per-asset off-hours flag; session comes from /status/market.
//
// Honesty rule (same as useConvertQuote): while loading or on upstream
// failure the hook returns an EMPTY list — never a fake price. Apollo keeps
// the last good payload cached, so brief upstream hiccups don't blank the UI.
//
// Trading-hours model (verified against Ondo docs 2026-07-04):
// - Continuous ~24/5 via pre/core/post/overnight sessions, brief pauses at
//   session boundaries.
// - Off-Hours (weekends/holidays) for SELECT assets only — live set comes
//   from tradableSessions per asset. Overnight/Off-Hours = wider spreads and
//   smaller max order sizes, NOT a resting order book: users always sign a
//   transaction that executes now or fails.
//
// Product notes:
// - Tokens are total-return trackers: dividends auto-reinvest into the price.
//   No dividend-payout UI anywhere, by design.
// - Buying power = the user's cUSD+ balance (sweep-account model).

import { useMemo } from 'react';
import { gql, useQuery } from '@apollo/client';

export type GmSession = 'core' | 'extended' | 'off-hours' | 'closed';
export type Tradability = 'open' | 'reduced' | 'closed';

export interface GmStock {
  /** GM token symbol (TSLAon) — the trading/on-chain id */
  symbol: string;
  /** Underlying ticker (TSLA) — the display id, used in navigation */
  ticker: string;
  name: string;
  priceUsd: number;
  dayChangePct: number;
  color: string; // fallback initial-circle hue when the logo fails to load
  logoUrl: string;
  offHours: boolean; // tradable on weekends/holidays (per-asset, per Ondo)
  sparkline24h: number[];
}

const GM_MARKET = gql`
  query GmMarket {
    gmMarket {
      session
      assets {
        symbol
        ticker
        name
        priceUsd
        dayChangePct
        offHours
        sparkline24h
        logoUrl
      }
    }
  }
`;

// Per-symbol candles for the range-selector chart (server proxy of Ondo's
// OHLC endpoint, 300s cache). Ondo's smallest supported request is 1D with
// 15-minute candles, so 1H/6H/12H reuse that real series and slice it on the
// client. Only the close series is consumed — the detail chart is a line,
// not a candlestick.
export type GmRange =
  | '1H'
  | '6H'
  | '12H'
  | '1D'
  | '1M'
  | '3M'
  | '6M'
  | '1Y'
  | 'MAX';
type GmApiRange = Exclude<GmRange, '1H' | '6H' | '12H'>;
export const GM_RANGES: GmRange[] = [
  '1H',
  '6H',
  '12H',
  '1D',
  '1M',
  '3M',
  '6M',
  '1Y',
  'MAX',
];
export const GM_RANGE_ACCESSIBILITY_LABELS: Record<GmRange, string> = {
  '1H': '1 hora',
  '6H': '6 horas',
  '12H': '12 horas',
  '1D': '1 día',
  '1M': '1 mes',
  '3M': '3 meses',
  '6M': '6 meses',
  '1Y': '1 año',
  MAX: 'Máximo',
};

interface GmCandle {
  timestamp: number;
  close: number;
}

const INTRADAY_LOOKBACK_MS: Partial<Record<GmRange, number>> = {
  '1H': 60 * 60 * 1000,
  '6H': 6 * 60 * 60 * 1000,
  '12H': 12 * 60 * 60 * 1000,
};

export const gmApiRangeFor = (range: GmRange): GmApiRange =>
  range in INTRADAY_LOOKBACK_MS ? '1D' : (range as GmApiRange);

/** Select closes inside the requested window, anchored to the newest candle.
 * Anchoring to market data rather than Date.now keeps the last trading window
 * visible while a market is paused or closed. */
export const gmClosesForRange = (
  candles: GmCandle[],
  range: GmRange,
): number[] => {
  const lookbackMs = INTRADAY_LOOKBACK_MS[range];
  if (!lookbackMs || candles.length === 0)
    return candles.map(candle => candle.close);

  const newestTimestamp = Math.max(...candles.map(candle => candle.timestamp));
  const cutoff = newestTimestamp - lookbackMs;
  return candles
    .filter(candle => candle.timestamp >= cutoff)
    .map(candle => candle.close);
};

export const gmOhlcState = (
  candles: GmCandle[],
  range: GmRange,
  enabled: boolean,
  loading: boolean,
  hasError: boolean,
) => {
  const closes = enabled ? gmClosesForRange(candles, range) : [];
  const empty = closes.length === 0;
  return {
    closes,
    loading: enabled && loading && empty,
    failed: enabled && hasError && empty,
  };
};

const GM_OHLC = gql`
  query GmOhlc($symbol: String!, $range: String) {
    gmOhlc(symbol: $symbol, range: $range) {
      timestamp
      close
    }
  }
`;

export const useGmOhlc = (
  symbol: string | undefined,
  range: GmRange,
  enabled = true,
) => {
  const apiRange = gmApiRangeFor(range);
  const { data, loading, error } = useQuery(GM_OHLC, {
    variables: { symbol, range: apiRange },
    skip: !enabled || !symbol,
    fetchPolicy: 'cache-and-network',
    pollInterval: 300_000,
  });
  return useMemo(
    () =>
      gmOhlcState(
        data?.gmOhlc ?? [],
        range,
        enabled,
        loading,
        !!error || data?.gmOhlc === null,
      ),
    [data, loading, error, enabled, range],
  );
};

// Deterministic fallback sparkline so charts render when the 24h series is
// missing for an asset (never used as a price display).
export const sparklineFor = (ticker: string, points = 24): number[] => {
  let seed = 0;
  for (const c of ticker) seed = (seed * 31 + c.charCodeAt(0)) % 997;
  const out: number[] = [];
  let v = 100;
  for (let i = 0; i < points; i++) {
    seed = (seed * 73 + 41) % 997;
    v += ((seed % 21) - 10) / 6;
    out.push(v);
  }
  return out;
};

// Stable per-ticker hue for the initial-circle fallback (TickerLogo).
const colorFor = (ticker: string): string => {
  let seed = 0;
  for (const c of ticker) seed = (seed * 31 + c.charCodeAt(0)) % 359;
  return `hsl(${seed}, 55%, 42%)`;
};

// Transitional fallback only (old server payloads without logoUrl): the
// server now sends logos from OUR S3 mirror so user devices never hotlink
// third parties. TickerLogo falls back to the initial circle on 404 either
// way, so a missing logo is cosmetic only.
const logoFor = (ticker: string) =>
  `https://financialmodelingprep.com/image-stock/${ticker}.png`;

export const useGmMarket = (enabled = true) => {
  const { data, loading } = useQuery(GM_MARKET, {
    skip: !enabled,
    fetchPolicy: 'cache-and-network',
    pollInterval: 60_000, // matches the server-side cache TTL
  });

  return useMemo(() => {
    // `skip` does not erase Apollo's previous account cache. Explicitly
    // discard it when the authoritative server visibility flag is false.
    const market = enabled ? data?.gmMarket : null;
    const session: GmSession = (market?.session as GmSession) || 'core';
    const stocks: GmStock[] = (market?.assets || []).map((a: any) => ({
      symbol: a.symbol,
      ticker: a.ticker,
      name: a.name,
      priceUsd: a.priceUsd,
      dayChangePct: a.dayChangePct,
      color: colorFor(a.ticker),
      logoUrl: a.logoUrl || logoFor(a.ticker),
      offHours: !!a.offHours,
      sparkline24h: a.sparkline24h || [],
    }));
    const tradabilityFor = (s: GmStock): Tradability => {
      if (session === 'core') return 'open';
      if (session === 'extended') return 'reduced';
      if (session === 'off-hours') return s.offHours ? 'reduced' : 'closed';
      return s.offHours ? 'reduced' : 'closed';
    };
    return {
      session,
      stocks,
      loading: enabled && loading && stocks.length === 0,
      byTicker: (t: string) => stocks.find((s) => s.ticker === t),
      tradabilityFor,
    };
  }, [data, loading, enabled]);
};
