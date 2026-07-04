// Single wiring point for the Ahorros e Inversiones portfolio.
//
// Neither the cUSD+ backend nor the Ondo Stocks backend exists yet. Every
// number the hub (and the HomeScreen entry row) renders flows through this
// hook so screens ship now and wire later without layout changes.
//
// When the backend lands, replace the memoized stub with a GraphQL query:
// - savings.netApyPct MUST be server-derived (USDY oracle gross × 0.85) —
//   rates float with US Treasuries and are never hardcoded in copy.
// - stocks.enabled becomes a remote flag (decision 2dcfada5: dark until the
//   demand signal), geofenced US/CA/BR + sanctions per Ondo partner terms.

import { useMemo } from 'react';

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

export const useAhorrosPortfolio = (): AhorrosPortfolio =>
  useMemo(() => {
    const savings = {
      balanceUsd: 0,
      netApyPct: 3.0,
      earnedTodayUsd: 0,
      earnedMonthUsd: 0,
    };
    const stocks = {
      // Visible during the design/dev phase; move to a server flag before
      // release so launch stays gated on the demand signal.
      enabled: true,
      totalUsd: 0,
      earnedTodayUsd: 0,
      positions: [] as StockPosition[],
    };
    return {
      savings,
      stocks,
      movements: [] as AhorroMovement[],
      totalUsd: savings.balanceUsd + stocks.totalUsd,
      earnedTodayUsd: savings.earnedTodayUsd + stocks.earnedTodayUsd,
      earnedMonthUsd: savings.earnedMonthUsd,
    };
  }, []);
