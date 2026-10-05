// Data for the Tu mes insight cards (docs/designs/tu-mes-insights.md 8A and
// the delta corrections):
//
// - Four isolated queries (monthInsights, savingsEarned, protectionValue,
//   stockMonth): each fails alone, and an older server never breaks
//   monthSummary.
// - One reveal: the window opens when Card A has rendered (`ready`) and
//   closes when every query has settled or after 800ms. What arrived by then
//   is shown, together and in slot order; anything later is dropped for this
//   view, so nothing below ever moves after the reveal.
// - Refocus refetches silently: values inside cards already shown update,
//   but no card or row is added, removed or swapped until the next view
//   (month switch or screen re-entry).
// - Answers are dropped when they belong to an earlier month or account.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useApolloClient } from '@apollo/client';
import {
  GET_MONTH_INSIGHTS, GET_PROTECTION_VALUE, GET_SAVINGS_EARNED, GET_STOCK_MONTH,
  type MonthInsights, type ProtectionValue, type RecurringPayment, type SavingsEarned, type StockMonth,
} from '../apollo/monthSummary';
import { MIN_SAVINGS_USD } from '../utils/monthInsights';

export const REVEAL_WINDOW_MS = 800;
/** Arriving from a trade's success screen: the trade just invalidated the
 *  holdings scan, and the stocks card is what the user came to see. The
 *  reveal still happens the moment every query has answered. */
export const REVEAL_WINDOW_AFTER_TRADE_MS = 2500;
/** Value-only answers re-asked after a trade settled (one per poll, ~4s
 *  apart: past the server's 30s scan cache) before value only is taken as
 *  the real answer — an incomplete history is not a race, never polled for
 *  the whole settling window. */
export const VALUE_ONLY_RECHECKS = 12;

export type InsightData = {
  insights: MonthInsights | null;
  savings: SavingsEarned | null;
  protection: ProtectionValue | null;
  /** "Tus acciones": null hides the card (unknown, or stocks not offered). */
  stocks?: StockMonth | null;
};

export type MonthInsightsState =
  | { revealed: false }
  | ({ revealed: true } & InsightData);

const EMPTY: InsightData = { insights: null, savings: null, protection: null, stocks: null };

/** What the reveal actually shows: a savings answer under a cent and a
 *  savings answer behind protection are not cards, so they are not "shown"
 *  (a refocus must never turn them into one). */
export function visibleAtReveal(data: InsightData): InsightData {
  const gained = data.protection && data.protection.state !== 'stable';
  const savingsVisible = !gained && data.savings && Number(data.savings.earnedUsd) >= MIN_SAVINGS_USD;
  return { ...data, savings: savingsVisible ? data.savings : null };
}

const positive = (v: string | null | undefined) => Number(v) > 0;

/** Refetch result → shown values, without changing the structure revealed. */
export function mergeValues(shown: InsightData, next: InsightData): InsightData {
  const keys = new Set((shown.insights?.recurring ?? []).map((r) => r.counterpartyKey));
  const byKey = new Map<string, RecurringPayment>((next.insights?.recurring ?? []).map((r) => [r.counterpartyKey, r]));
  return {
    insights: shown.insights
      ? {
        // The pace line exists only with last month's Salió > 0: keep that fact frozen.
        previousMonthSpendingUsd: next.insights && positive(next.insights.previousMonthSpendingUsd) === positive(shown.insights.previousMonthSpendingUsd)
          ? next.insights.previousMonthSpendingUsd : shown.insights.previousMonthSpendingUsd,
        recurring: shown.insights.recurring.map((r) => (keys.has(r.counterpartyKey) && byKey.get(r.counterpartyKey)) || r),
      }
      : null,
    // A card shown stays shown (keeps its last value if the refetch has none).
    savings: shown.savings
      ? (next.savings && Number(next.savings.earnedUsd) >= MIN_SAVINGS_USD ? next.savings : shown.savings)
      : null,
    // Same state only: a gained↔stable flip would swap the slot's card.
    protection: shown.protection
      ? (next.protection && next.protection.state === shown.protection.state ? next.protection : shown.protection)
      : null,
    // Never a downgrade (gain → value_only). One-way exceptions, all in the
    // same card: a settling card resolves in place; value only becomes the
    // month's result once the history explains it (a passing value-only
    // right after a trade must not stick); and the invitation gives way to
    // the card once the user has bought through it.
    stocks: shown.stocks
      ? (next.stocks && (next.stocks.state === shown.stocks.state
        || (shown.stocks.state === 'none' && next.stocks.state !== 'none')
        || (shown.stocks.state === 'value_only' && next.stocks.state === 'gain')
        // After settling the server answers 'none' only when the trade
        // failed (a pending one is still 'settling'): never a stuck note.
        || shown.stocks.state === 'settling')
        ? next.stocks : shown.stocks)
      : null,
  };
}

export function useMonthInsights(params: {
  accountKey: string | null | undefined;
  year: number;
  month: number;
  timezone: string | undefined;
  isCurrent: boolean;
  /** Card A has rendered (monthSummary answered): the 800ms window starts. */
  ready: boolean;
  /** Reveal window override (REVEAL_WINDOW_AFTER_TRADE_MS from a trade). */
  revealWindowMs?: number;
}): MonthInsightsState & { refresh: () => void; refreshStocks: () => void; stocksSettling: boolean } {
  const { accountKey, year, month, timezone, isCurrent, ready, revealWindowMs = REVEAL_WINDOW_MS } = params;
  // Read at reveal time: a param merged later must not restart a reveal.
  const windowMs = useRef(revealWindowMs);
  windowMs.current = revealWindowMs;
  const client = useApolloClient();
  const viewKey = `${accountKey ?? ''}:${year}-${month}`;
  const [state, setState] = useState<MonthInsightsState>({ revealed: false });
  const view = useRef(viewKey);
  // Bumped on every new view and on unmount: an answer carries the
  // generation it was asked in, so a refresh from an earlier visit to the
  // SAME month can never overwrite a newer one.
  const generation = useRef(0);
  const shown = useRef<InsightData | null>(null);
  // The latest stocks answer's state, even when the shown card kept its own
  // (gain/value_only never swap to 'settling'): the screen polls on it.
  const lastStocks = useRef<StockMonth['state'] | null>(null);
  // This view saw a trade settle: a value-only answer right after it may be
  // a passing race (scan vs finality), so it keeps being re-asked (up to
  // VALUE_ONLY_RECHECKS answers: an incomplete history is a real answer).
  const sawSettling = useRef(false);
  const valueOnlyChecks = useRef(0);
  const stocksInFlight = useRef(false);
  // Stocks asks are numbered when sent: an answer older than one already
  // applied (a focus refresh waits for its slowest query; a poll doesn't)
  // must not land over it and restart the settling poll.
  const stocksAsked = useRef(0);
  const stocksApplied = useRef(0);
  useEffect(() => () => { generation.current += 1; }, []);

  /** Records an applied stocks answer's state (what the screen polls on). */
  const noteStocks = useCallback((next: StockMonth['state'] | null) => {
    lastStocks.current = next;
    if (next === 'settling') {
      sawSettling.current = true;
      valueOnlyChecks.current = 0;
    } else if (next === 'value_only' && sawSettling.current) {
      valueOnlyChecks.current += 1;
      if (valueOnlyChecks.current > VALUE_ONLY_RECHECKS) sawSettling.current = false;
    } else if (next === 'gain' || next === 'none') {
      sawSettling.current = false;               // the trade resolved
    }
  }, []);

  const fetchStocks = useCallback(() => client.query<{ stockMonth: StockMonth | null }>(
    { query: GET_STOCK_MONTH, variables: { year, month, timezone }, fetchPolicy: 'no-cache' })
    .then((r) => r.data?.stockMonth ?? null).catch(() => null), [client, year, month, timezone]);

  const fetchAll = useCallback((withStocks = true) => {
    const opt = { fetchPolicy: 'no-cache' as const };
    const safe = <T,>(p: Promise<{ data?: T }>) => p.then((r) => r.data ?? null).catch(() => null);
    const insights = safe(client.query<{ monthInsights: MonthInsights | null }>(
      { query: GET_MONTH_INSIGHTS, variables: { year, month, timezone }, ...opt })).then((d) => d?.monthInsights ?? null);
    const savings = safe(client.query<{ savingsEarned: SavingsEarned | null }>(
      { query: GET_SAVINGS_EARNED, variables: { year, month }, ...opt })).then((d) => d?.savingsEarned ?? null);
    // Protection is a "today" number: current month only (§4).
    const protection = isCurrent
      ? safe(client.query<{ protectionValue: ProtectionValue | null }>({ query: GET_PROTECTION_VALUE, variables: { timezone }, ...opt }))
        .then((d) => d?.protectionValue ?? null)
      : Promise.resolve(null);
    return { insights, savings, protection, stocks: withStocks ? fetchStocks() : Promise.resolve(null) };
  }, [client, year, month, timezone, isCurrent, fetchStocks]);

  // A new month or account is a new view: hide, then reveal again.
  if (view.current !== viewKey) {
    view.current = viewKey;
    generation.current += 1;
    shown.current = null;
    lastStocks.current = null;
    sawSettling.current = false;
    valueOnlyChecks.current = 0;
    if (state.revealed) setState({ revealed: false });
  }

  useEffect(() => {
    if (!ready) return undefined;
    const gen = generation.current;
    if (!accountKey) {                 // nothing to fetch: reveal empty, never a skeleton forever
      shown.current = { ...EMPTY };
      setState({ revealed: true, ...EMPTY });
      return undefined;
    }
    let closed = false;
    const got: InsightData = { ...EMPTY };
    const reveal = () => {
      if (closed || generation.current !== gen) return;
      closed = true;
      shown.current = visibleAtReveal({ ...got });
      noteStocks(got.stocks?.state ?? null);
      setState({ revealed: true, ...shown.current });
    };
    const { insights, savings, protection, stocks } = fetchAll();
    insights.then((v) => { if (!closed) got.insights = v; });
    savings.then((v) => { if (!closed) got.savings = v; });
    protection.then((v) => { if (!closed) got.protection = v; });
    stocks.then((v) => { if (!closed) got.stocks = v; });
    const timer = setTimeout(reveal, windowMs.current);
    Promise.all([insights, savings, protection, stocks]).then(() => {
      clearTimeout(timer);
      reveal();
    });
    return () => {
      closed = true;
      clearTimeout(timer);
    };
  }, [ready, accountKey, viewKey, fetchAll, noteStocks]);

  const refresh = useCallback(() => {
    const gen = generation.current;
    if (!shown.current) return;
    // A stocks ask already in flight (a settling poll, cold scan) answers on
    // its own: never stack a second one on it. Ours holds the slot too.
    const askStocks = !stocksInFlight.current;
    const seq = askStocks ? ++stocksAsked.current : 0;
    const { insights, savings, protection, stocks } = fetchAll(askStocks);
    if (askStocks) {
      stocksInFlight.current = true;
      stocks.finally(() => { stocksInFlight.current = false; });
    }
    Promise.all([insights, savings, protection, stocks]).then(([i, s, p, k]) => {
      if (generation.current !== gen || !shown.current) return;
      const fresh = askStocks && seq > stocksApplied.current;
      if (fresh) {
        stocksApplied.current = seq;
        if (k) noteStocks(k.state);
      }
      const merged = mergeValues(shown.current,
        { insights: i, savings: s, protection: p, stocks: fresh ? k : shown.current.stocks });
      shown.current = merged;
      setState({ revealed: true, ...merged });
    });
  }, [fetchAll, noteStocks]);

  /** Stocks only (a settling trade): the other cards are not re-asked. One
   *  ask at a time: a slow answer (cold scan) is not stacked with the next
   *  poll's, and an older answer can't land after a newer one. */
  const refreshStocks = useCallback(() => {
    const gen = generation.current;
    if (!shown.current || stocksInFlight.current) return;
    stocksInFlight.current = true;
    const seq = ++stocksAsked.current;
    fetchStocks().finally(() => { stocksInFlight.current = false; }).then((k) => {
      if (generation.current !== gen || !shown.current || seq <= stocksApplied.current) return;
      stocksApplied.current = seq;
      if (k) noteStocks(k.state);
      const merged = mergeValues(shown.current, { ...shown.current, stocks: k });
      shown.current = merged;
      setState({ revealed: true, ...merged });
    });
  }, [fetchStocks, noteStocks]);

  // Only a shown card can resolve in place (a dropped one never appears).
  const stocksSettling = Boolean(shown.current?.stocks) && (lastStocks.current === 'settling'
    || (sawSettling.current && lastStocks.current === 'value_only'));
  return { ...state, refresh, refreshStocks, stocksSettling };
}
