// Single wiring point for the Ahorros e Inversiones portfolio.
//
// LIVE since 2026-07-10: cusdPlusSummary reads the real vault position
// (shares × pPlus server-side, cached with a last-known fallback) and
// gmHoldings returns the account's tokenized-stock positions (server-side
// Multicall3 scan of the GM universe — the chain is the registry — priced
// from the cached GM market payload).
// Movements are NOT here: cUSD+/USDT activity lives in the unified
// transaction ledger like every other rail, and renders through
// AccountDetailScreen's Historial. There is no second ledger.
//
// Notes:
// - savings.netApyPct is SERVER-derived LIVE from Ondo's on-chain oracle:
//   the USDY daily rate compounded at the vault's kept share (85%) —
//   rates float with US Treasuries and are never hardcoded in copy.
// - stocks.enabled is a remote flag (decision 2dcfada5: dark until the
//   demand signal), geofenced per Ondo partner terms.

import { useMemo } from 'react';
import { gql, useQuery } from '@apollo/client';
import { useAuth, useAuthReady } from '../contexts/AuthContext';
import { isOndoPhoneCountryEligible } from '../config/ondoEligibility';

// Flags gate surfaces (savingsEnabled gates ENTRY only — Ahorrar CTA,
// Convert; exits are never gated. The deposit mutation enforces
// eligibility independently, so flags are UX, not security). Numbers are
// the real position: vault balance + stock holdings.
const GET_AHORRO_PORTFOLIO = gql`
  query AhorroPortfolio {
    cusdPlusSummary {
      savingsEnabled
      stocksEnabled
      stocksTradingEnabled
      stocksBuyEnabled
      cusdDepositsPaused
      balanceUsd
      netApyPct
      earnedTodayUsd
      earnedMonthUsd
      usdtBalanceUsd
      usdtBalanceWei
      cusdBalanceUsd
      cusdBalanceWei
      conversionFeeBps
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
    tradingEnabled: boolean;
    buyEnabled: boolean;
    totalUsd: number;
    earnedTodayUsd: number;
    positions: StockPosition[];
  };
  /** Raw wallet USDT-BSC: landed-but-not-minted money (eligible users,
   *  transient) or the whole "Confío Dollar" balance (geo-ineligible users).
   *  TOP-LEVEL on purpose — never part of savings.balanceUsd, which caps the
   *  vault redeem rails. */
  usdtBalanceUsd: number;
  /** Same balance in exact wei (server string; client re-reads live before
   *  exact-amount sends). */
  usdtBalanceWei: string;
  /** Universal non-yield cUSD payment balance. */
  cusdBalanceUsd: number;
  cusdBalanceWei: string;
  /** Live, bounded USDT perimeter fee used for non-binding disclosure. */
  conversionFeeBps: number;
  totalUsd: number;
  earnedTodayUsd: number;
  earnedMonthUsd: number;
  /** Force a network refetch (pull-to-refresh). Server-side balance caches
   *  are ~30s, so this is "as fresh as the server will serve". */
  refetch: () => Promise<unknown>;
  /** True until the FIRST result lands. Every balance above defaults to 0,
   *  so callers that must tell "loaded and empty" from "not loaded yet" —
   *  a send button choosing between "Saldo insuficiente" and "Cargando…" —
   *  have to read this rather than test for 0. */
  loading: boolean;
}

export const useSavingsPortfolio = (): SavingsPortfolio => {
  // Every field here is JWT-account-scoped (the query takes no account
  // argument), so firing before the token is synced to the active account
  // answers for the WRONG account — or for none, which returns a null
  // summary the balance rows would print as a confident $0.00. Same gate
  // GET_MY_BALANCES uses.
  const isAuthReady = useAuthReady();
  const { userProfile } = useAuth();
  const { data, refetch, loading } = useQuery(GET_AHORRO_PORTFOLIO, {
    fetchPolicy: 'cache-and-network',
    pollInterval: 60_000, // matches the server-side GM cache TTL
    skip: !isAuthReady,
  });
  const summary = data?.cusdPlusSummary;
  // Fail-open before the server answers (most users are eligible LATAM —
  // avoids flash-hiding the hub); authoritative once it does. The server
  // gates the yield wrapper (phone + IP country): ineligible deposits become
  // universal cUSD ("Confío Dollar"), never cUSD+.
  const savingsEnabled: boolean = summary?.savingsEnabled ?? true;
  // Stocks (Ondo GM): server flag = geo-eligible AND CUSD_PLUS_STOCKS_ENABLED.
  // Fail-closed before the answer — an investment surface appearing beats
  // one being yanked away from a blocked user.
  const stocksEnabled: boolean = Boolean(
    summary?.stocksEnabled
    && isOndoPhoneCountryEligible(userProfile?.phoneCountry),
  );
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
    const positions: StockPosition[] = (stocksEnabled ? data?.gmHoldings ?? [] : []).map((h: any) => ({
      symbol: h.symbol,
      ticker: h.ticker,
      name: h.name,
      units: h.units,
      valueUsd: h.valueUsd,
      dayChangePct: h.dayChangePct,
    }));
    const stocks = {
      enabled: stocksEnabled,
      tradingEnabled: stocksEnabled && Boolean(summary?.stocksTradingEnabled),
      buyEnabled: stocksEnabled && Boolean(summary?.stocksBuyEnabled),
      totalUsd: positions.reduce((sum, p) => sum + p.valueUsd, 0),
      // Day P&L implied by each position's 24h change:
      // value_now − value_now / (1 + pct/100), summed.
      earnedTodayUsd: positions.reduce(
        (sum, p) => sum + (p.valueUsd * p.dayChangePct) / (100 + p.dayChangePct || 1),
        0,
      ),
      positions,
    };
    // Server display ledger, newest first. Unknown future types render as
    // neutral rows rather than crashing an old client.
    return {
      savings,
      stocks,
      usdtBalanceUsd: summary?.usdtBalanceUsd ?? 0,
      usdtBalanceWei: summary?.usdtBalanceWei ?? '0',
      cusdBalanceUsd: summary?.cusdBalanceUsd ?? 0,
      cusdBalanceWei: summary?.cusdBalanceWei ?? '0',
      conversionFeeBps: summary?.conversionFeeBps ?? 90,
      totalUsd: savings.balanceUsd + (summary?.cusdBalanceUsd ?? 0) + stocks.totalUsd,
      earnedTodayUsd: savings.earnedTodayUsd + stocks.earnedTodayUsd,
      earnedMonthUsd: savings.earnedMonthUsd,
      refetch,
      // cache-and-network keeps `loading` true on background refreshes, so
      // anchor on "no data yet" — a cached balance is a usable balance.
      // While the auth gate holds the query, Apollo reports loading=false;
      // that is still "not loaded yet", not "loaded and empty".
      loading: !isAuthReady || (loading && !data),
    };
  }, [data, savingsEnabled, stocksEnabled, cusdDepositsPaused, summary, refetch, loading, isAuthReady]);
};
