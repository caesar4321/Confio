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

export const useAhorrosPortfolio = (): AhorrosPortfolio => {
  const { data: flagsData } = useQuery(GET_AHORRO_ELIGIBILITY, {
    fetchPolicy: 'cache-and-network',
  });
  // Fail-open before the server answers (most users are eligible LATAM —
  // avoids flash-hiding the hub); authoritative once it does. The server
  // rejects ineligible deposits regardless of what the UI shows.
  const savingsEnabled: boolean = flagsData?.cusdPlusSummary?.savingsEnabled ?? true;
  // Stocks (Ondo GM): server flag = geo-eligible AND CUSD_PLUS_STOCKS_ENABLED.
  // Fail-closed before the answer — an investment surface appearing beats
  // one being yanked away from a blocked user.
  const stocksEnabled: boolean = flagsData?.cusdPlusSummary?.stocksEnabled ?? false;

  return useMemo(() => {
    // Balances/movements are launch-day empty states until the cUSD+ vault
    // ledger lands server-side (cusdPlusSummary/cusdPlusMovements stubs).
    const savings = {
      enabled: savingsEnabled,
      balanceUsd: 0,
      netApyPct: 3.0,
      earnedTodayUsd: 0,
      earnedMonthUsd: 0,
    };
    const positions: StockPosition[] = [];
    const stocks = {
      enabled: stocksEnabled,
      totalUsd: positions.reduce((sum, p) => sum + p.valueUsd, 0),
      earnedTodayUsd: 0,
      positions,
    };
    const movements: AhorroMovement[] = [];
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
