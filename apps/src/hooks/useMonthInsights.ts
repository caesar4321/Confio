// Data for the Tu mes insight cards (docs/designs/tu-mes-insights.md 8A and
// the delta corrections):
//
// - Three isolated queries (monthInsights, savingsEarned, protectionValue):
//   each fails alone, and an older server never breaks monthSummary.
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
  GET_MONTH_INSIGHTS, GET_PROTECTION_VALUE, GET_SAVINGS_EARNED,
  type MonthInsights, type ProtectionValue, type RecurringPayment, type SavingsEarned,
} from '../apollo/monthSummary';
import { MIN_SAVINGS_USD } from '../utils/monthInsights';

export const REVEAL_WINDOW_MS = 800;

export type InsightData = {
  insights: MonthInsights | null;
  savings: SavingsEarned | null;
  protection: ProtectionValue | null;
};

export type MonthInsightsState =
  | { revealed: false }
  | ({ revealed: true } & InsightData);

const EMPTY: InsightData = { insights: null, savings: null, protection: null };

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
}): MonthInsightsState & { refresh: () => void } {
  const { accountKey, year, month, timezone, isCurrent, ready } = params;
  const client = useApolloClient();
  const viewKey = `${accountKey ?? ''}:${year}-${month}`;
  const [state, setState] = useState<MonthInsightsState>({ revealed: false });
  const view = useRef(viewKey);
  // Bumped on every new view and on unmount: an answer carries the
  // generation it was asked in, so a refresh from an earlier visit to the
  // SAME month can never overwrite a newer one.
  const generation = useRef(0);
  const shown = useRef<InsightData | null>(null);
  useEffect(() => () => { generation.current += 1; }, []);

  const fetchAll = useCallback(() => {
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
    return { insights, savings, protection };
  }, [client, year, month, timezone, isCurrent]);

  // A new month or account is a new view: hide, then reveal again.
  if (view.current !== viewKey) {
    view.current = viewKey;
    generation.current += 1;
    shown.current = null;
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
      setState({ revealed: true, ...shown.current });
    };
    const { insights, savings, protection } = fetchAll();
    insights.then((v) => { if (!closed) got.insights = v; });
    savings.then((v) => { if (!closed) got.savings = v; });
    protection.then((v) => { if (!closed) got.protection = v; });
    const timer = setTimeout(reveal, REVEAL_WINDOW_MS);
    Promise.all([insights, savings, protection]).then(() => {
      clearTimeout(timer);
      reveal();
    });
    return () => {
      closed = true;
      clearTimeout(timer);
    };
  }, [ready, accountKey, viewKey, fetchAll]);

  const refresh = useCallback(() => {
    const gen = generation.current;
    if (!shown.current) return;
    const { insights, savings, protection } = fetchAll();
    Promise.all([insights, savings, protection]).then(([i, s, p]) => {
      if (generation.current !== gen || !shown.current) return;
      const merged = mergeValues(shown.current, { insights: i, savings: s, protection: p });
      shown.current = merged;
      setState({ revealed: true, ...merged });
    });
  }, [fetchAll]);

  return { ...state, refresh };
}
