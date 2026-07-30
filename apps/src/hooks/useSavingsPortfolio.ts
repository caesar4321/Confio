// Single wiring point for the Ahorros e Inversiones portfolio.
//
// LIVE since 2026-07-10: cusdPlusSummary reads the real vault position
// (shares × pPlus server-side, cached with a last-known fallback) and
// gmHoldings returns the account's tokenized-stock positions (server-side
// Multicall3 scan of the GM universe — the chain is the registry — priced
// from the cached GM market payload).
// Movements stay an empty state until the cusdPlusMovements ledger lands.
//
// Notes:
// - savings.netApyPct is SERVER-derived LIVE from Ondo's on-chain oracle:
//   the USDY daily rate compounded at the vault's kept share (85%) —
//   rates float with US Treasuries and are never hardcoded in copy.
// - stocks.enabled is a remote flag (decision 2dcfada5: dark until the
//   demand signal), geofenced per Ondo partner terms.

import { useMemo } from 'react';
import { gql, useQuery } from '@apollo/client';

// Flags gate surfaces (savingsEnabled gates ENTRY only — Ahorrar CTA,
// Convert; exits are never gated. The deposit mutation enforces
// eligibility independently, so flags are UX, not security). Numbers are
// the real position: vault balance + stock holdings.
const GET_AHORRO_PORTFOLIO = gql`
  query AhorroPortfolio {
    cusdPlusSummary {
      savingsEnabled
      stocksEnabled
      cusdDepositsPaused
      balanceUsd
      netApyPct
      earnedTodayUsd
      earnedMonthUsd
      usdtBalanceUsd
      usdtBalanceWei
    }
    gmHoldings {
      symbol
      ticker
      name
      units
      valueUsd
      dayChangePct
    }
  }
`;

export interface StockPosition {
  /** GM token symbol (TSLAon) — the trading/on-chain id */
  symbol: string;
  ticker: string;
  name: string;
  units: number;
  valueUsd: number;
  dayChangePct: number;
}

export type SavingsMovementType =
  | 'deposit' // Ahorraste (cUSD → cUSD+ or ramp-in)
  | 'withdraw' // Retiraste (→ cUSD or bank)
  | 'buy' // Compraste una acción (from cUSD+)
  | 'sell' // Vendiste una acción (back to cUSD+)
  | 'yield'; // weekly/monthly yield summary row (never per-day spam)

export interface SavingsMovement {
  id: string;
  type: SavingsMovementType;
  title: string; // e.g. 'Ahorraste', 'Compraste TSLA'
  amountUsd: number; // signed: deposits/sell/yield positive into savings
  createdAt: string; // ISO
}

export interface SavingsPortfolio {
  savings: {
    enabled: boolean; // issuer geo-eligibility; gates entry surfaces only
    cusdDepositsPaused: boolean; // cUSD phase-out: stop promoting new cUSD ramp deposits
    balanceUsd: number; // USD value only — share counts are never exposed
    netApyPct: number;
    earnedTodayUsd: number;
    earnedMonthUsd: number;
    // NOTE: no entryCostPct here on purpose — conversion cost is server-quoted
    // in-flow (ConvertSavings) and never printed in marketing copy. The stale
    // Jupiter-era 0.15% figure lived here once; don't bring it back.
  };
  stocks: {
    enabled: boolean;
    totalUsd: number;
    earnedTodayUsd: number;
    positions: StockPosition[];
  };
  movements: SavingsMovement[];
  /** Raw wallet USDT-BSC: landed-but-not-minted money (eligible users,
   *  transient) or the whole "Confío Dollar" balance (geo-ineligible users).
   *  TOP-LEVEL on purpose — never part of savings.balanceUsd, which caps the
   *  vault redeem rails. */
  usdtBalanceUsd: number;
  /** Same balance in exact wei (server string; client re-reads live before
   *  exact-amount sends). */
  usdtBalanceWei: string;
  totalUsd: number;
  earnedTodayUsd: number;
  earnedMonthUsd: number;
  /** Force a network refetch (pull-to-refresh). Server-side balance caches
   *  are ~30s, so this is "as fresh as the server will serve". */
  refetch: () => Promise<unknown>;
}

export const useSavingsPortfolio = (): SavingsPortfolio => {
  const { data, refetch } = useQuery(GET_AHORRO_PORTFOLIO, {
    fetchPolicy: 'cache-and-network',
    pollInterval: 60_000, // matches the server-side GM cache TTL
  });
  const summary = data?.cusdPlusSummary;
  // Fail-open before the server answers (most users are eligible LATAM —
  // avoids flash-hiding the hub); authoritative once it does. The server
  // gates the MINT (phone + IP country): ineligible deposits simply land as
  // raw USDT ("Confío Dollar"), never as cUSD+.
  const savingsEnabled: boolean = summary?.savingsEnabled ?? true;
  // Stocks (Ondo GM): server flag = geo-eligible AND CUSD_PLUS_STOCKS_ENABLED.
  // Fail-closed before the answer — an investment surface appearing beats
  // one being yanked away from a blocked user.
  const stocksEnabled: boolean = summary?.stocksEnabled ?? false;
  // cUSD phase-out steering. Defaults to the shipped prod state (paused) so
  // the pre-answer frame renders the intended savings-first sheet instead of
  // flashing the legacy cUSD option and collapsing one round-trip later.
  const cusdDepositsPaused: boolean = summary?.cusdDepositsPaused ?? true;

  return useMemo(() => {
    const savings = {
      enabled: savingsEnabled,
      cusdDepositsPaused,
      balanceUsd: summary?.balanceUsd ?? 0,
      // Server-derived; 0 until the oracle-rate derivation (or config) is
      // set — an honest 0% beats a hardcoded 3% (locked design rule).
      netApyPct: summary?.netApyPct ?? 0,
      earnedTodayUsd: summary?.earnedTodayUsd ?? 0,
      earnedMonthUsd: summary?.earnedMonthUsd ?? 0,
    };
    // gmHoldings is null on GM upstream failure (never a fake price) —
    // Apollo keeps the last good payload cached across brief hiccups.
    const positions: StockPosition[] = (data?.gmHoldings ?? []).map((h: any) => ({
      symbol: h.symbol,
      ticker: h.ticker,
      name: h.name,
      units: h.units,
      valueUsd: h.valueUsd,
      dayChangePct: h.dayChangePct,
    }));
    const stocks = {
      enabled: stocksEnabled,
      totalUsd: positions.reduce((sum, p) => sum + p.valueUsd, 0),
      // Day P&L implied by each position's 24h change:
      // value_now − value_now / (1 + pct/100), summed.
      earnedTodayUsd: positions.reduce(
        (sum, p) => sum + (p.valueUsd * p.dayChangePct) / (100 + p.dayChangePct || 1),
        0,
      ),
      positions,
    };
    // Movements stay a launch-day empty state until the cusdPlusMovements
    // ledger lands server-side (resolver is still a stub returning []).
    const movements: SavingsMovement[] = [];
    return {
      savings,
      stocks,
      movements,
      usdtBalanceUsd: summary?.usdtBalanceUsd ?? 0,
      usdtBalanceWei: summary?.usdtBalanceWei ?? '0',
      totalUsd: savings.balanceUsd + stocks.totalUsd,
      earnedTodayUsd: savings.earnedTodayUsd + stocks.earnedTodayUsd,
      earnedMonthUsd: savings.earnedMonthUsd,
      refetch,
    };
  }, [data, savingsEnabled, stocksEnabled, cusdDepositsPaused, summary, refetch]);
};
