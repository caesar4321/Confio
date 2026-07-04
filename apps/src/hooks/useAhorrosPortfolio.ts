// Single wiring point for the Ahorros e Inversiones portfolio.
//
// Neither the cUSD+ backend nor the Ondo Stocks backend exists yet. Every
// number the hub (and the HomeScreen entry row) renders flows through this
// hook so screens ship now and wire later without layout changes.
//
// When the backend lands, replace the memoized stub with the GraphQL seam
// already mounted server-side (cusd_plus/schema.py): cusdPlusSummary,
// cusdPlusMovements(limit, offset), cusdPlusQuote(amountUsd, direction).
// Notes:
// - savings.netApyPct MUST be server-derived (USDY oracle gross × 0.85) —
//   rates float with US Treasuries and are never hardcoded in copy.
// - stocks.enabled becomes a remote flag (decision 2dcfada5: dark until the
//   demand signal), geofenced US/CA/BR + sanctions per Ondo partner terms.

import { useMemo } from 'react';
import { gql, useQuery } from '@apollo/client';

// Issuer geo-eligibility (Ondo) — LIVE server flags, unlike the number stubs
// below. savingsEnabled gates ENTRY surfaces only (Ahorrar CTA, Convert);
// exits (Retirar) are never gated. Computed server-side from the user's
// phone country (cusd_plus/eligibility.py); the deposit mutation enforces
// it independently, so this flag is UX, not security.
const GET_AHORRO_ELIGIBILITY = gql`
  query AhorroEligibility {
    cusdPlusSummary {
      savingsEnabled
      stocksEnabled
    }
  }
`;

export interface StockPosition {
  ticker: string;
  name: string;
  valueUsd: number;
  dayChangePct: number;
}

export type AhorroMovementType =
  | 'deposit' // Ahorraste (cUSD → cUSD+ or ramp-in)
  | 'withdraw' // Retiraste (→ cUSD or bank)
  | 'buy' // Compraste una acción (from cUSD+)
  | 'sell' // Vendiste una acción (back to cUSD+)
  | 'yield'; // weekly/monthly yield summary row (never per-day spam)

export interface AhorroMovement {
  id: string;
  type: AhorroMovementType;
  title: string; // e.g. 'Ahorraste', 'Compraste TSLA'
  amountUsd: number; // signed: deposits/sell/yield positive into savings
  createdAt: string; // ISO
}

export interface AhorrosPortfolio {
  savings: {
    enabled: boolean; // issuer geo-eligibility; gates entry surfaces only
    balanceUsd: number; // USD value only — share counts are never exposed
    netApyPct: number;
    earnedTodayUsd: number;
    earnedMonthUsd: number;
    // NOTE: no entryCostPct here on purpose — conversion cost is server-quoted
    // in-flow (ConvertAhorro) and never printed in marketing copy. The stale
    // Jupiter-era 0.15% figure lived here once; don't bring it back.
  };
  stocks: {
    enabled: boolean;
    totalUsd: number;
    earnedTodayUsd: number;
    positions: StockPosition[];
  };
  movements: AhorroMovement[];
  totalUsd: number;
  earnedTodayUsd: number;
  earnedMonthUsd: number;
}

// DEV ONLY: true renders realistic sample data so every rich state is
// reviewable (hero split line, hoy/mes ticker, positions, movements).
// false renders the real launch-day empty states. Delete this whole demo
// branch when the backend lands.
const DEMO = true;

export const useAhorrosPortfolio = (): AhorrosPortfolio => {
  const { data: flagsData } = useQuery(GET_AHORRO_ELIGIBILITY, {
    fetchPolicy: 'cache-and-network',
  });
  // Fail-open before the server answers (most users are eligible LATAM —
  // avoids flash-hiding the hub); authoritative once it does. The server
  // rejects ineligible deposits regardless of what the UI shows.
  const savingsEnabled: boolean = flagsData?.cusdPlusSummary?.savingsEnabled ?? true;
  // Stocks: dark-launch + geo flag. DEMO builds stay visible until the
  // server answers so design review keeps working.
  const stocksEnabled: boolean = flagsData?.cusdPlusSummary?.stocksEnabled ?? DEMO;

  return useMemo(() => {
    const savings = DEMO
      ? {
          enabled: savingsEnabled,
          balanceUsd: 1250.4,
          netApyPct: 3.0,
          earnedTodayUsd: 0.1,
          earnedMonthUsd: 2.05,
        }
      : {
          enabled: savingsEnabled,
          balanceUsd: 0,
          netApyPct: 3.0,
          earnedTodayUsd: 0,
          earnedMonthUsd: 0,
        };
    const positions: StockPosition[] = DEMO
      ? [
          { ticker: 'TSLA', name: 'Tesla', valueUsd: 180.5, dayChangePct: 2.14 },
          { ticker: 'NVDA', name: 'NVIDIA', valueUsd: 95.2, dayChangePct: -1.32 },
        ]
      : [];
    const stocks = {
      enabled: stocksEnabled,
      totalUsd: positions.reduce((sum, p) => sum + p.valueUsd, 0),
      earnedTodayUsd: DEMO ? 2.53 : 0,
      positions,
    };
    const movements: AhorroMovement[] = DEMO
      ? [
          {
            id: 'm1',
            type: 'yield',
            title: 'Rendimiento de la semana',
            amountUsd: 0.68,
            createdAt: '2026-06-29T12:00:00Z',
          },
          {
            id: 'm2',
            type: 'buy',
            title: 'Compraste TSLA',
            amountUsd: -150,
            createdAt: '2026-06-27T15:30:00Z',
          },
          {
            id: 'm3',
            type: 'deposit',
            title: 'Ahorraste',
            amountUsd: 500,
            createdAt: '2026-06-25T09:10:00Z',
          },
          {
            id: 'm4',
            type: 'withdraw',
            title: 'Retiraste a cUSD',
            amountUsd: -80,
            createdAt: '2026-06-20T18:45:00Z',
          },
          {
            id: 'm5',
            type: 'deposit',
            title: 'Ahorraste',
            amountUsd: 900,
            createdAt: '2026-06-15T11:00:00Z',
          },
        ]
      : [];
    return {
      savings,
      stocks,
      movements,
      totalUsd: savings.balanceUsd + stocks.totalUsd,
      earnedTodayUsd: savings.earnedTodayUsd + stocks.earnedTodayUsd,
      earnedMonthUsd: savings.earnedMonthUsd,
    };
  }, [savingsEnabled, stocksEnabled]);
};
