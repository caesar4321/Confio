// Data for the Tu mes insight cards (docs/designs/tu-mes-insights.md 8A and
// the delta corrections):
//
// - Five isolated queries (monthInsights, savingsEarned, protectionValue,
//   stockMonth, cryptoMonth): each fails alone, and an older server never
//   breaks monthSummary.
// - The two investment cards ("Tus acciones", "Oro y Bitcoin") follow the
//   same rules, each in its own slot: merge, settling poll, one ask at a time.
// - One reveal: once Card A has rendered (`ready`), the cards are shown
//   together, in slot order, when every query has settled (no short window:
//   a cold stocks scan of ~1.6s must not lose its card). Only a request
//   that hangs (a degraded node) is cut off, at REVEAL_HANG_GUARD_MS; anything later is dropped for this
//   view, so nothing below ever moves after the reveal.
// - Refocus refetches silently: values inside cards already shown update,
//   but no card or row is added, removed or swapped until the next view
//   (month switch or screen re-entry).
// - Answers are dropped when they belong to an earlier month or account.
import { useCallback, useEffect, useRef, useState } from 'react';
import { useApolloClient } from '@apollo/client';
import {
  GET_CRYPTO_MONTH, GET_MONTH_INSIGHTS, GET_PROTECTION_VALUE, GET_SAVINGS_EARNED, GET_STOCK_MONTH,
  type CryptoMonth, type MonthInsights, type ProtectionValue, type RecurringPayment, type SavingsEarned,
  type StockMonth,
} from '../apollo/monthSummary';
import { MIN_SAVINGS_USD } from '../utils/monthInsights';

/** Not a design window: the reveal waits for every query. This only cuts off
 *  a request that never answers, so the lower screen can't stay empty. */
export const REVEAL_HANG_GUARD_MS = 5000;

export type InsightData = {
  insights: MonthInsights | null;
  savings: SavingsEarned | null;
  protection: ProtectionValue | null;
  /** "Tus acciones": null hides the card (unknown, or stocks not offered). */
  stocks?: StockMonth | null;
  /** "Oro y Bitcoin": null hides the card (unknown, or crypto not offered). */
  crypto?: CryptoMonth | null;
};

/** The investment cards: each its own query, merge and settling poll. */
export type InvestmentSlot = 'stocks' | 'crypto';
const SLOTS: InvestmentSlot[] = ['stocks', 'crypto'];
type Investment = { state: StockMonth['state']; canBuy?: boolean };

const QUERIES = {
  stocks: { query: GET_STOCK_MONTH, field: 'stockMonth' },
  crypto: { query: GET_CRYPTO_MONTH, field: 'cryptoMonth' },
} as const;

export type MonthInsightsState =
  | { revealed: false }
  | ({ revealed: true } & InsightData);

const EMPTY: InsightData = { insights: null, savings: null, protection: null, stocks: null, crypto: null };

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
    stocks: mergeInvestment(shown.stocks, next.stocks),
    crypto: mergeInvestment(shown.crypto, next.crypto),
  };
}

/** One investment card's refetch → shown value. Never a downgrade (gain →
 *  value_only; the hook alone overrides this for a value-only answer final
 *  after a trade). One-way exceptions, all in the same card: a settling card
 *  resolves in place; value only becomes the month's result once the history
 *  explains it (a passing value-only right after a trade must not stick);
 *  and the invitation gives way to the card once the user has bought through
 *  it. 'none' stays as shown: its only content is whether the invitation is
 *  drawn (canBuy, which follows the request's IP), and a flip would add or
 *  remove a card. */
function mergeInvestment<T extends Investment>(shown: T | null | undefined, next: T | null | undefined): T | null {
  if (!shown) return null;
  return next && !(shown.state === 'none' && next.state === 'none')
    && (next.state === shown.state
    || (shown.state === 'none' && next.state !== 'none')
    || (shown.state === 'value_only' && next.state === 'gain')
    // After settling the server answers 'none' only when the trade
    // failed (a pending one is still 'settling'): never a stuck note.
    || shown.state === 'settling')
    ? next : shown;
}

/** Drawn on screen: a card, or an invitation (stocks 'none' with canBuy). */
const drawn = (v: Investment | null | undefined) => Boolean(v && !(v.state === 'none' && !v.canBuy));

type SlotRefs = {
  /** The latest answer's state, even when the shown card kept its own
   *  (gain/value_only never swap to 'settling'): the screen polls on it. */
  last: StockMonth['state'] | null;
  /** The view (generation) whose ask is in flight: a month switch frees the
   *  slot at once, and an old ask's cleanup never frees a new one. */
  inFlight: number | null;
  /** Asks are numbered when sent: an answer older than one already applied
   *  (a focus refresh waits for its slowest query; a poll doesn't) must not
   *  land over it and restart the settling poll. */
  asked: number;
  applied: number;
};
const newSlot = (): SlotRefs => ({ last: null, inFlight: null, asked: 0, applied: 0 });

export function useMonthInsights(params: {
  accountKey: string | null | undefined;
  year: number;
  month: number;
  timezone: string | undefined;
  isCurrent: boolean;
  /** Card A has rendered (monthSummary answered): the insight queries start. */
  ready: boolean;
}): MonthInsightsState & {
  refresh: () => void; refreshStocks: () => void; refreshCrypto: () => void;
  stocksSettling: boolean; cryptoSettling: boolean;
} {
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
  const slots = useRef<Record<InvestmentSlot, SlotRefs>>({ stocks: newSlot(), crypto: newSlot() });
  useEffect(() => () => { generation.current += 1; }, []);

  /** Records an applied answer's state (what the screen polls on). True
   *  when it resolves a trade this view saw settling: the server's answer
   *  after a trade is final (it says 'settling' itself while a trade is on
   *  the wire or a node lags it, from the scan's own blocks), so that answer
   *  replaces the card shown — even a pre-trade 'gain', which would
   *  otherwise keep the value before the trade. */
  const noteSlot = useCallback((slot: InvestmentSlot, next: StockMonth['state'] | null): boolean => {
    const refs = slots.current[slot];
    const resolvesTrade = refs.last === 'settling' && next !== null && next !== 'settling';
    refs.last = next;
    return resolvesTrade;
  }, []);

  /** mergeValues, except an answer that resolves a trade replaces its shown card. */
  const mergeAnswers = useCallback((current: InsightData, next: InsightData, resolves: Partial<Record<InvestmentSlot, boolean>>) => {
    const merged = mergeValues(current, next);
    for (const slot of SLOTS) {
      if (resolves[slot] && current[slot] && next[slot]) (merged as any)[slot] = next[slot];
    }
    return merged;
  }, []);

  const fetchSlot = useCallback((slot: InvestmentSlot) => {
    const { query, field } = QUERIES[slot];
    return client.query<Record<string, any>>({ query, variables: { year, month, timezone }, fetchPolicy: 'no-cache' })
      .then((r) => (r.data?.[field] ?? null) as any).catch(() => null);
  }, [client, year, month, timezone]);

  const fetchAll = useCallback((ask: Record<InvestmentSlot, boolean> = { stocks: true, crypto: true }) => {
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
    return {
      insights, savings, protection,
      stocks: (ask.stocks ? fetchSlot('stocks') : Promise.resolve(null)) as Promise<StockMonth | null>,
      crypto: (ask.crypto ? fetchSlot('crypto') : Promise.resolve(null)) as Promise<CryptoMonth | null>,
    };
  }, [client, year, month, timezone, isCurrent, fetchSlot]);

  // A new month or account is a new view: hide, then reveal again.
  if (view.current !== viewKey) {
    view.current = viewKey;
    generation.current += 1;
    shown.current = null;
    for (const slot of SLOTS) slots.current[slot].last = null;
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
      for (const slot of SLOTS) noteSlot(slot, got[slot]?.state ?? null);
      setState({ revealed: true, ...shown.current });
    };
    const { insights, savings, protection, stocks, crypto } = fetchAll();
    insights.then((v) => { if (!closed) got.insights = v; });
    savings.then((v) => { if (!closed) got.savings = v; });
    protection.then((v) => { if (!closed) got.protection = v; });
    stocks.then((v) => { if (!closed) got.stocks = v; });
    crypto.then((v) => { if (!closed) got.crypto = v; });
    const timer = setTimeout(reveal, REVEAL_HANG_GUARD_MS);
    Promise.all([insights, savings, protection, stocks, crypto]).then(() => {
      clearTimeout(timer);
      reveal();
    });
    return () => {
      closed = true;
      clearTimeout(timer);
    };
  }, [ready, accountKey, viewKey, fetchAll, noteSlot]);

  const refresh = useCallback(() => {
    const gen = generation.current;
    if (!shown.current) return;
    // An investment ask already in flight (a settling poll, cold scan)
    // answers on its own: never stack a second one on it. Ours holds the
    // slot too. Nothing drawn (no answer, or 'none' with nothing to offer):
    // don't make the server scan and price the portfolio for nothing — and
    // an answer could only add a card mid-view. Unless a trade is settling here.
    const ask = {} as Record<InvestmentSlot, boolean>;
    const seq = {} as Record<InvestmentSlot, number>;
    for (const slot of SLOTS) {
      const refs = slots.current[slot];
      ask[slot] = (drawn(shown.current[slot]) || refs.last === 'settling') && refs.inFlight !== gen;
      seq[slot] = ask[slot] ? ++refs.asked : 0;
    }
    const answers = fetchAll(ask);
    for (const slot of SLOTS) {
      if (!ask[slot]) continue;
      const refs = slots.current[slot];
      refs.inFlight = gen;
      answers[slot].finally(() => { if (refs.inFlight === gen) refs.inFlight = null; });
    }
    const { insights, savings, protection, stocks, crypto } = answers;
    Promise.all([insights, savings, protection, stocks, crypto]).then(([i, s, p, k, c]) => {
      if (generation.current !== gen || !shown.current) return;
      const got: Record<InvestmentSlot, Investment | null> = { stocks: k, crypto: c };
      const next: InsightData = { insights: i, savings: s, protection: p };
      const resolves: Partial<Record<InvestmentSlot, boolean>> = {};
      for (const slot of SLOTS) {
        const refs = slots.current[slot];
        const fresh = ask[slot] && seq[slot] > refs.applied;
        if (fresh) {
          refs.applied = seq[slot];
          if (got[slot]) resolves[slot] = noteSlot(slot, got[slot]!.state);
        }
        (next as any)[slot] = fresh ? got[slot] : shown.current[slot];
      }
      const merged = mergeAnswers(shown.current, next, resolves);
      shown.current = merged;
      setState({ revealed: true, ...merged });
    });
  }, [fetchAll, noteSlot, mergeAnswers]);

  /** One investment card only (a settling trade): the other cards are not
   *  re-asked. One ask at a time: a slow answer (cold scan) is not stacked
   *  with the next poll's, and an older answer can't land after a newer one. */
  const refreshSlot = useCallback((slot: InvestmentSlot) => {
    const gen = generation.current;
    const refs = slots.current[slot];
    if (!shown.current || refs.inFlight === gen) return;
    refs.inFlight = gen;
    const seq = ++refs.asked;
    fetchSlot(slot).finally(() => { if (refs.inFlight === gen) refs.inFlight = null; }).then((k: Investment | null) => {
      if (generation.current !== gen || !shown.current || seq <= refs.applied) return;
      refs.applied = seq;
      const resolvesTrade = k ? noteSlot(slot, k.state) : false;
      const merged = mergeAnswers(shown.current, { ...shown.current, [slot]: k }, { [slot]: resolvesTrade });
      shown.current = merged;
      setState({ revealed: true, ...merged });
    });
  }, [fetchSlot, noteSlot, mergeAnswers]);
  const refreshStocks = useCallback(() => refreshSlot('stocks'), [refreshSlot]);
  const refreshCrypto = useCallback(() => refreshSlot('crypto'), [refreshSlot]);

  // Only a shown card can resolve in place (a dropped one never appears).
  const settlingIn = (slot: InvestmentSlot) => Boolean(shown.current?.[slot]) && slots.current[slot].last === 'settling';
  return {
    ...state, refresh, refreshStocks, refreshCrypto,
    stocksSettling: settlingIn('stocks'), cryptoSettling: settlingIn('crypto'),
  };
}
