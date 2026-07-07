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
      }
    }
  }
`;

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

// Logo CDN keyed by underlying ticker; TickerLogo falls back to the initial
// circle when an image 404s, so a missing logo is cosmetic only.
const logoFor = (ticker: string) =>
  `https://financialmodelingprep.com/image-stock/${ticker}.png`;

export const useGmMarket = () => {
  const { data, loading } = useQuery(GM_MARKET, {
    fetchPolicy: 'cache-and-network',
    pollInterval: 60_000, // matches the server-side cache TTL
  });

  return useMemo(() => {
    const market = data?.gmMarket;
    const session: GmSession = (market?.session as GmSession) || 'core';
    const stocks: GmStock[] = (market?.assets || []).map((a: any) => ({
      symbol: a.symbol,
      ticker: a.ticker,
      name: a.name,
      priceUsd: a.priceUsd,
      dayChangePct: a.dayChangePct,
      color: colorFor(a.ticker),
      logoUrl: logoFor(a.ticker),
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
      loading: loading && stocks.length === 0,
      byTicker: (t: string) => stocks.find((s) => s.ticker === t),
      tradabilityFor,
    };
  }, [data, loading]);
};
