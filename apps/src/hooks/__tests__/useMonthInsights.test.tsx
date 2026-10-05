import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { GET_MONTH_INSIGHTS, GET_PROTECTION_VALUE, GET_SAVINGS_EARNED, GET_STOCK_MONTH } from '../../apollo/monthSummary';

const mockQuery = jest.fn();
const mockClient = { query: (...a: any[]) => mockQuery(...a) };
jest.mock('@apollo/client', () => ({ ...jest.requireActual('@apollo/client'), useApolloClient: () => mockClient }));

import {
  mergeValues, REVEAL_WINDOW_AFTER_TRADE_MS, REVEAL_WINDOW_MS, useMonthInsights, VALUE_ONLY_RECHECK_MS,
} from '../useMonthInsights';

const insights = (keys: string[]) => ({
  previousMonthSpendingUsd: '390.00',
  recurring: keys.map((k, i) => ({ counterpartyKey: k, name: k, expectedDay: 5 + i, expectedAmountUsd: '100.00', category: null })),
});

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

let latest: any;
function Probe(props: any) {
  latest = useMonthInsights(props);
  return null;
}
const base = { accountKey: 'a1', year: 2026, month: 10, timezone: 'UTC', isCurrent: true, ready: true };

beforeEach(() => {
  jest.useFakeTimers();
  mockQuery.mockReset();
});
afterEach(() => jest.useRealTimers());

it('reveals once every query settles, together', async () => {
  mockQuery.mockImplementation(({ query }: any) => Promise.resolve({ data:
    query === GET_MONTH_INSIGHTS ? { monthInsights: insights(['karen']) }
      : query === GET_SAVINGS_EARNED ? { savingsEarned: { earnedUsd: '0.42', daily: [] } }
        : { protectionValue: null } }));
  await act(async () => { renderer.create(<Probe {...base} />); });
  expect(latest.revealed).toBe(true);
  expect(latest.insights.recurring).toHaveLength(1);
  expect(latest.savings.earnedUsd).toBe('0.42');
});

it('reveals what arrived by 800ms and drops anything later (8A)', async () => {
  const slow = deferred<any>();
  mockQuery.mockImplementation(({ query }: any) => (query === GET_PROTECTION_VALUE ? slow.promise
    : Promise.resolve({ data: query === GET_MONTH_INSIGHTS ? { monthInsights: insights([]) } : { savingsEarned: { earnedUsd: '0.42', daily: [] } } })));
  await act(async () => { renderer.create(<Probe {...base} />); });
  expect(latest.revealed).toBe(false);
  await act(async () => { jest.advanceTimersByTime(REVEAL_WINDOW_MS); });
  expect(latest.revealed).toBe(true);
  expect(latest.protection).toBeNull();
  await act(async () => { slow.resolve({ data: { protectionValue: { currency: 'BOB' } } }); });
  expect(latest.protection).toBeNull();          // late: never swaps the slot after the reveal
});

it('waits for Card A before starting, and skips protection on past months', async () => {
  mockQuery.mockResolvedValue({ data: {} });
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Probe {...base} ready={false} />); });
  expect(mockQuery).not.toHaveBeenCalled();
  await act(async () => { tree.update(<Probe {...base} ready isCurrent={false} month={9} />); });
  expect(mockQuery.mock.calls.map((c) => c[0].query)).not.toContain(GET_PROTECTION_VALUE);
});

it('refocus updates values but never adds, removes or swaps a card or row', () => {
  const shown = { insights: insights(['karen']), savings: null, protection: null };
  const next = { insights: { ...insights(['karen', 'wilber']), previousMonthSpendingUsd: '400.00' },
    savings: { earnedUsd: '1.00', daily: [] }, protection: null };
  next.insights.recurring[0].expectedAmountUsd = '105.00';
  const merged = mergeValues(shown, next);
  expect(merged.insights!.recurring.map((r) => [r.counterpartyKey, r.expectedAmountUsd])).toEqual([['karen', '105.00']]);
  expect(merged.insights!.previousMonthSpendingUsd).toBe('400.00');
  expect(merged.savings).toBeNull();                 // was not shown: not added
  expect(mergeValues({ ...shown, savings: { earnedUsd: '0.42', daily: [] } }, { ...next, savings: null }).savings)
    .toEqual({ earnedUsd: '0.42', daily: [] });      // shown: kept when the refetch has none
});

it('a sub-cent savings answer is not a card, so a refocus cannot insert it (audit #7)', () => {
  const { visibleAtReveal } = require('../useMonthInsights');
  const revealed = visibleAtReveal({ insights: null, savings: { earnedUsd: '0.00', daily: [] }, protection: null });
  expect(revealed.savings).toBeNull();
  const merged = mergeValues(revealed, { insights: null, savings: { earnedUsd: '0.02', daily: [] }, protection: null });
  expect(merged.savings).toBeNull();
});

it('an older refresh never overwrites a newer visit to the same month (audit #6)', async () => {
  const stale = deferred<any>();
  let calls = 0;
  mockQuery.mockImplementation(({ query }: any) => {
    if (query !== GET_MONTH_INSIGHTS) return Promise.resolve({ data: {} });
    calls += 1;
    if (calls === 2) return stale.promise;                 // the October refresh that answers late
    return Promise.resolve({ data: { monthInsights: insights(calls === 1 ? ['karen'] : ['karen']) } });
  });
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Probe {...base} />); });
  act(() => { latest.refresh(); });                        // October refresh in flight
  await act(async () => { tree.update(<Probe {...base} month={9} isCurrent={false} />); });
  await act(async () => { tree.update(<Probe {...base} />); });   // back to October: a new view
  const fresh = latest.insights;
  await act(async () => { stale.resolve({ data: { monthInsights: { ...insights(['karen']), previousMonthSpendingUsd: '1.00' } } }); });
  expect(latest.insights).toBe(fresh);
});

it('a gained↔stable flip on refocus never swaps the slot card', () => {
  const p = (state: string) => ({ currency: 'BOB', basis: 'purchase', state, source: 'binance_p2p', protectedUsd: '100.00',
    paidLocal: '1', todayLocal: '1', gainLocal: '0', avgRate: '1', todayRate: '1', quotedAt: '' }) as any;
  const merged = mergeValues({ insights: null, savings: null, protection: p('gained') },
    { insights: null, savings: null, protection: p('stable') });
  expect(merged.protection?.state).toBe('gained');
});

it('a settling stocks card resolves in place, or into the invitation when the trade failed', () => {
  const base = { insights: null, savings: null, protection: null };
  const settling = { state: 'settling', valueUsd: '220.00' } as any;
  const gain = { state: 'gain', valueUsd: '220.00', gainUsd: '15.00' } as any;
  expect(mergeValues({ ...base, stocks: settling }, { ...base, stocks: gain }).stocks).toBe(gain);
  const none = { state: 'none', canBuy: true } as any;
  expect(mergeValues({ ...base, stocks: settling }, { ...base, stocks: none }).stocks).toBe(none);
  expect(mergeValues({ ...base, stocks: settling }, { ...base, stocks: null }).stocks).toBe(settling);
  expect(mergeValues({ ...base, stocks: gain }, { ...base, stocks: settling }).stocks).toBe(gain);
  expect(mergeValues({ ...base, stocks: null }, { ...base, stocks: gain }).stocks).toBeNull();
});

it('the invitation gives way to the card after a purchase, never the reverse', () => {
  const base = { insights: null, savings: null, protection: null };
  const none = { state: 'none', canBuy: true } as any;
  const gain = { state: 'gain', gainUsd: '1.00' } as any;
  expect(mergeValues({ ...base, stocks: none }, { ...base, stocks: gain }).stocks).toBe(gain);
  expect(mergeValues({ ...base, stocks: gain }, { ...base, stocks: none }).stocks).toBe(gain);
});

it('a refocus never draws or removes the invitation (canBuy flips stay for the next view)', () => {
  const base = { insights: null, savings: null, protection: null };
  const invite = { state: 'none', canBuy: true } as any;
  const nothing = { state: 'none', canBuy: false } as any;
  expect(mergeValues({ ...base, stocks: nothing }, { ...base, stocks: invite }).stocks).toBe(nothing);
  expect(mergeValues({ ...base, stocks: invite }, { ...base, stocks: nothing }).stocks).toBe(invite);
});

it('a shown gain card that gets a settling answer keeps its value and flags the poll until final', async () => {
  const gain = { state: 'gain', valueUsd: '100.00' };
  let stocks: any = gain;
  mockQuery.mockImplementation(({ query }: any) => Promise.resolve({ data:
    query === GET_STOCK_MONTH ? { stockMonth: stocks } : {} }));
  await act(async () => { renderer.create(<Probe {...base} />); });
  expect(latest.stocks).toEqual(gain);
  expect(latest.stocksSettling).toBe(false);
  stocks = { state: 'settling', valueUsd: '220.00' };
  await act(async () => { latest.refresh(); });
  expect(latest.stocks).toEqual(gain);                 // never swaps the card
  expect(latest.stocksSettling).toBe(true);
  stocks = { state: 'gain', valueUsd: '220.00' };
  await act(async () => { latest.refreshStocks(); });
  expect(latest.stocks.valueUsd).toBe('220.00');
  expect(latest.stocksSettling).toBe(false);
});

it('a settling poll never stacks a second stocks ask on one still in flight', async () => {
  const settling = { state: 'settling', valueUsd: '220.00' };
  mockQuery.mockImplementation(({ query }: any) => Promise.resolve({ data:
    query === GET_STOCK_MONTH ? { stockMonth: settling } : {} }));
  await act(async () => { renderer.create(<Probe {...base} />); });
  const slow = deferred<any>();
  mockQuery.mockReset();
  mockQuery.mockImplementation(() => slow.promise);
  await act(async () => { latest.refreshStocks(); latest.refreshStocks(); });
  expect(mockQuery).toHaveBeenCalledTimes(1);
  await act(async () => { slow.resolve({ data: { stockMonth: { state: 'gain', valueUsd: '220.00' } } }); });
  expect(latest.stocks.state).toBe('gain');
  mockQuery.mockResolvedValue({ data: { stockMonth: { state: 'gain', valueUsd: '221.00' } } });
  await act(async () => { latest.refreshStocks(); });
  expect(mockQuery).toHaveBeenCalledTimes(2);           // free again once answered
});

it('a month switch frees the stocks slot; the old ask finishing later never frees the new one', async () => {
  const settling = { state: 'settling', valueUsd: '220.00' };
  mockQuery.mockImplementation(({ query }: any) => Promise.resolve({ data:
    query === GET_STOCK_MONTH ? { stockMonth: settling } : {} }));
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Probe {...base} />); });
  const oldAsk = deferred<any>();
  mockQuery.mockImplementation(() => oldAsk.promise);
  await act(async () => { latest.refreshStocks(); });                    // October's ask hangs
  mockQuery.mockImplementation(({ query }: any) => Promise.resolve({ data:
    query === GET_STOCK_MONTH ? { stockMonth: settling } : {} }));
  await act(async () => { tree.update(<Probe {...base} month={9} isCurrent={false} />); });
  const newAsk = deferred<any>();
  mockQuery.mockReset();
  mockQuery.mockImplementation(() => newAsk.promise);
  await act(async () => { latest.refreshStocks(); });
  expect(mockQuery).toHaveBeenCalledTimes(1);                             // not blocked by October's
  await act(async () => { oldAsk.resolve({ data: { stockMonth: null } }); });
  await act(async () => { latest.refreshStocks(); });
  expect(mockQuery).toHaveBeenCalledTimes(1);                             // September's still holds it
});

it("a focus refresh's older stocks answer never lands over a newer poll's (no restarted poll)", async () => {
  const settling = { state: 'settling', valueUsd: '220.00' };
  mockQuery.mockImplementation(({ query }: any) => Promise.resolve({ data:
    query === GET_STOCK_MONTH ? { stockMonth: settling } : {} }));
  await act(async () => { renderer.create(<Probe {...base} />); });
  expect(latest.stocksSettling).toBe(true);
  // Focus refresh: stocks answers 'settling' at once, but monthInsights is slow.
  const slowInsights = deferred<any>();
  mockQuery.mockImplementation(({ query }: any) => (query === GET_MONTH_INSIGHTS ? slowInsights.promise
    : Promise.resolve({ data: query === GET_STOCK_MONTH ? { stockMonth: settling } : {} })));
  await act(async () => { latest.refresh(); });
  // A poll sent later answers 'gain' first.
  mockQuery.mockImplementation(() => Promise.resolve({ data: { stockMonth: { state: 'gain', valueUsd: '221.00' } } }));
  await act(async () => { latest.refreshStocks(); });
  expect(latest.stocks.state).toBe('gain');
  expect(latest.stocksSettling).toBe(false);
  await act(async () => { slowInsights.resolve({ data: { monthInsights: null } }); });
  expect(latest.stocks.state).toBe('gain');
  expect(latest.stocksSettling).toBe(false);          // the stale 'settling' did not restart the poll
});

it('a focus refresh never stacks a stocks ask on a poll still in flight', async () => {
  const settling = { state: 'settling', valueUsd: '220.00' };
  mockQuery.mockImplementation(({ query }: any) => Promise.resolve({ data:
    query === GET_STOCK_MONTH ? { stockMonth: settling } : {} }));
  await act(async () => { renderer.create(<Probe {...base} />); });
  const slow = deferred<any>();
  mockQuery.mockReset();
  mockQuery.mockImplementation(({ query }: any) => (query === GET_STOCK_MONTH ? slow.promise
    : Promise.resolve({ data: {} })));
  await act(async () => { latest.refreshStocks(); latest.refresh(); });
  expect(mockQuery.mock.calls.filter(([o]: any) => o.query === GET_STOCK_MONTH)).toHaveLength(1);
  await act(async () => { slow.resolve({ data: { stockMonth: { state: 'gain', valueUsd: '221.00' } } }); });
  expect(latest.stocks.state).toBe('gain');
  expect(latest.stocksSettling).toBe(false);
});

it('from a trade, the reveal waits longer for a slow stocks answer (the card the user came for)', async () => {
  const slow = deferred<any>();
  mockQuery.mockImplementation(({ query }: any) => (query === GET_STOCK_MONTH ? slow.promise
    : Promise.resolve({ data: {} })));
  await act(async () => { renderer.create(<Probe {...base} revealWindowMs={REVEAL_WINDOW_AFTER_TRADE_MS} />); });
  await act(async () => { jest.advanceTimersByTime(REVEAL_WINDOW_MS); });
  expect(latest.revealed).toBe(false);
  await act(async () => { slow.resolve({ data: { stockMonth: { state: 'gain', gainUsd: '1.00' } } }); });
  expect(latest.revealed).toBe(true);
  expect(latest.stocks.state).toBe('gain');
});

it('value only becomes the result once explained, and a view that saw settling keeps asking', () => {
  const base2 = { insights: null, savings: null, protection: null };
  const valueOnly = { state: 'value_only', valueUsd: '220.00' } as any;
  const gain = { state: 'gain', gainUsd: '1.00' } as any;
  expect(mergeValues({ ...base2, stocks: valueOnly }, { ...base2, stocks: gain }).stocks).toBe(gain);
  expect(mergeValues({ ...base2, stocks: gain }, { ...base2, stocks: valueOnly }).stocks).toBe(gain);   // never a downgrade
});

it('after a trade settles, value only is re-asked for a while, then taken as the answer', async () => {
  let stocks: any = { state: 'value_only', valueUsd: '100.00' };
  mockQuery.mockImplementation(({ query }: any) => Promise.resolve({ data:
    query === GET_STOCK_MONTH ? { stockMonth: stocks } : {} }));
  await act(async () => { renderer.create(<Probe {...base} />); });
  expect(latest.stocksSettling).toBe(false);          // an incomplete history alone is never polled
  stocks = { state: 'settling', valueUsd: '220.00' };
  await act(async () => { latest.refresh(); });
  expect(latest.stocksSettling).toBe(true);
  stocks = { state: 'value_only', valueUsd: '220.00' };
  await act(async () => { latest.refreshStocks(); });
  expect(latest.stocksSettling).toBe(true);           // may be a passing race: keep asking
  // Time, not a count: with polls every 30s, two answers already pass it.
  jest.advanceTimersByTime(30000);
  await act(async () => { latest.refreshStocks(); });
  expect(latest.stocksSettling).toBe(true);
  jest.advanceTimersByTime(VALUE_ONLY_RECHECK_MS - 30000 + 1);
  await act(async () => { latest.refreshStocks(); });
  expect(latest.stocksSettling).toBe(false);          // a real value-only answer: the poll ends
  stocks = { state: 'settling', valueUsd: '300.00' };
  await act(async () => { latest.refresh(); });
  expect(latest.stocksSettling).toBe(true);           // a later trade starts over
});
