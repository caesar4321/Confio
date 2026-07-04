// Ondo Stocks (GM) market data — single wiring point for the Acciones screens.
//
// TODO(gm): replace the static stubs with a backend proxy of the Ondo GM API
// (base https://api.gm.ondo.finance/v1, x-api-key from onboarding):
// - /assets/all/metadata → real asset list + logos (replaces the design-phase
//   public CDN logoUrl below)
// - enhanced prices → price + 24h change; OHLC → charts
// - market status + asset statuses → session/tradability (incl. 1-5 min
//   session-boundary pauses and per-asset halts)
// Proxy server-side per their Endpoint Caching guidance and enforce the
// partner geofence (US/CA/BR + sanctions) per Ondo terms.
//
// Trading-hours model (verified against Ondo docs 2026-07-04):
// - Continuous ~24/5: Sun 8:05pm ET → Fri 7:59pm ET (pre/core/post/overnight
//   via Blue Ocean ATS), with brief pauses at session boundaries.
// - Off-Hours session (weekends/holidays) for SELECT assets only — at launch
//   SPYon, QQQon, CRCLon, NVDAon, TSLAon, GOOGLon — live on Ethereum and
//   BNB CHAIN (Solana "planned later"). Overnight/Off-Hours = wider spreads
//   and smaller max order sizes, NOT a resting order book: users always sign
//   a transaction that executes now or fails — there is no "order waits for
//   open" state anywhere in the UX.
//
// Product notes:
// - Tokens are total-return trackers: dividends auto-reinvest into the price.
//   No dividend-payout UI anywhere, by design.
// - Buying power = the user's cUSD+ balance (sweep-account model).

import { useMemo } from 'react';

export type GmSession = 'core' | 'extended' | 'off-hours' | 'closed';
export type Tradability = 'open' | 'reduced' | 'closed';

export interface GmStock {
  ticker: string;
  name: string;
  priceUsd: number;
  dayChangePct: number;
  color: string; // fallback initial-circle hue when the logo fails to load
  logoUrl: string;
  offHours: boolean; // tradable on weekends/holidays (per-asset, per Ondo)
}

// Deterministic fake sparkline so detail charts render before the API lands.
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

// Design-phase logo source; production switches to Ondo metadata logos.
const logo = (t: string) => `https://financialmodelingprep.com/image-stock/${t}.png`;

const STOCKS: GmStock[] = [
  { ticker: 'TSLA', name: 'Tesla', priceUsd: 312.4, dayChangePct: 1.84, color: '#E31937', logoUrl: logo('TSLA'), offHours: true },
  { ticker: 'NVDA', name: 'NVIDIA', priceUsd: 168.9, dayChangePct: 2.31, color: '#76B900', logoUrl: logo('NVDA'), offHours: true },
  { ticker: 'AAPL', name: 'Apple', priceUsd: 214.6, dayChangePct: -0.42, color: '#555960', logoUrl: logo('AAPL'), offHours: false },
  { ticker: 'MSFT', name: 'Microsoft', priceUsd: 472.1, dayChangePct: 0.67, color: '#00A4EF', logoUrl: logo('MSFT'), offHours: false },
  { ticker: 'AMZN', name: 'Amazon', priceUsd: 223.5, dayChangePct: 1.12, color: '#FF9900', logoUrl: logo('AMZN'), offHours: false },
  { ticker: 'GOOGL', name: 'Alphabet', priceUsd: 186.2, dayChangePct: -0.28, color: '#4285F4', logoUrl: logo('GOOGL'), offHours: true },
  { ticker: 'META', name: 'Meta', priceUsd: 705.8, dayChangePct: 0.94, color: '#0064E0', logoUrl: logo('META'), offHours: false },
  { ticker: 'KO', name: 'Coca-Cola', priceUsd: 69.8, dayChangePct: 0.15, color: '#B31942', logoUrl: logo('KO'), offHours: false },
  { ticker: 'MCD', name: "McDonald's", priceUsd: 301.2, dayChangePct: -0.51, color: '#FFC72C', logoUrl: logo('MCD'), offHours: false },
  { ticker: 'SPY', name: 'S&P 500 (ETF)', priceUsd: 618.3, dayChangePct: 0.44, color: '#B45309', logoUrl: logo('SPY'), offHours: true },
  { ticker: 'QQQ', name: 'Nasdaq 100 (ETF)', priceUsd: 552.7, dayChangePct: 0.71, color: '#1D4ED8', logoUrl: logo('QQQ'), offHours: true },
  { ticker: 'IAU', name: 'Oro (ETF)', priceUsd: 63.1, dayChangePct: 0.22, color: '#A16207', logoUrl: logo('IAU'), offHours: false },
];

export const useGmMarket = () =>
  useMemo(() => {
    // TODO(gm): market-status API. Function-shaped so TS keeps the union type
    // (a literal const would narrow and break session comparisons downstream).
    const getSession = (): GmSession => 'core';
    const session = getSession();
    const tradabilityFor = (s: GmStock): Tradability => {
      if (session === 'core') return 'open';
      if (session === 'extended') return 'reduced';
      if (session === 'off-hours') return s.offHours ? 'reduced' : 'closed';
      return s.offHours ? 'reduced' : 'closed';
    };
    return {
      session,
      stocks: STOCKS,
      byTicker: (t: string) => STOCKS.find((s) => s.ticker === t),
      tradabilityFor,
    };
  }, []);
