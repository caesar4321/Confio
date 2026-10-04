/**
 * The Home month row is always present for owners (fixed footprint), so its
 * content may change whenever data lands. What must hold: never another
 * account's numbers, employees see nothing, last month early in the month,
 * the invitation when there is nothing to show, and the hero never writes the
 * shared summary cache.
 */
import React from 'react';
import renderer, { act } from 'react-test-renderer';

// A value applies to every month; a function picks per {year, month}.
let mockCached: any = null;
let mockNetwork: any = null;
const per = (v: any, vars: any) => (typeof v === 'function' ? v(vars) : v);
const mockQuery = jest.fn((opts: any) => Promise.resolve({ data: { monthSummary: per(mockNetwork, opts.variables) } }));
const mockReadQuery = jest.fn((opts: any) => {
  const v = per(mockCached, opts.variables);
  return v ? { monthSummary: v } : null;
});
// Stable like the real client (a new object per render would re-run load).
const mockClient = { readQuery: (o: any) => mockReadQuery(o), query: (o: any) => mockQuery(o) };

jest.mock('@apollo/client', () => ({
  gql: (s: TemplateStringsArray) => s.join(''),
  useApolloClient: () => mockClient,
}));
// Focus behaves like the real hook on an always-focused screen: runs on
// mount and again whenever the callback identity changes.
jest.mock('@react-navigation/native', () => ({
  useFocusEffect: (cb: () => void | (() => void)) => require('react').useEffect(cb, [cb]),
}));

import { useMonthHeroLine, type HeroMonthState } from '../useMonthHeroLine';

const summary = (movementCount: number, month = 10) => ({
  year: 2026, month, timezone: 'UTC', previousIsPartial: true,
  current: { incomeUsd: '420', spendingUsd: '310', movementCount, spendingByCategory: [] },
  previous: null, counterparties: [],
});

const count = (s: HeroMonthState) => (s.kind === 'month' ? s.summary.current.movementCount : s.kind);

const mounted: renderer.ReactTestRenderer[] = [];
const mount = (accountKey: string | null, enabled = true, switching = false) => {
  let api!: HeroMonthState;
  const Probe = ({ k, e, w }: { k: string | null; e: boolean; w: boolean }) => {
    api = useMonthHeroLine(k, e, w);
    return null;
  };
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<Probe k={accountKey} e={enabled} w={switching} />); });
  mounted.push(tree);
  return {
    state: () => api,
    rerender: (k: string | null, e = true, w = false) => act(() => tree.update(<Probe k={k} e={e} w={w} />)),
  };
};

const flush = () => act(async () => {});

beforeEach(() => {
  mockCached = null;
  mockNetwork = null;
  mockQuery.mockClear();
  mockReadQuery.mockClear();
});
// The hook keeps a month-boundary timer; unmount so it cannot outlive a test.
afterEach(() => {
  while (mounted.length) act(() => mounted.pop()!.unmount());
});

describe('useMonthHeroLine', () => {
  it('starts as loading, then shows the month once data lands', async () => {
    mockNetwork = summary(5);
    const { state } = mount('acc-1');
    expect(state().kind).toBe('loading');
    await flush();
    expect(count(state())).toBe(5);
  });

  it('shows a cached month immediately', async () => {
    mockCached = summary(4);
    const { state } = mount('acc-1');
    expect(count(state())).toBe(4);
  });

  it('invites (never hides) when neither this nor last month has 3 movements', async () => {
    mockNetwork = summary(1);
    const { state } = mount('acc-1');
    await flush();
    expect(state().kind).toBe('invite');
  });

  it('early in the month shows last month until this one has 3 movements', async () => {
    const now = new Date();
    const thisMonth = now.getMonth() + 1;
    mockNetwork = (v: any) => (v.month === thisMonth ? summary(1, thisMonth) : summary(12, v.month));
    const { state } = mount('acc-1');
    await flush();
    const s = state();
    expect(s.kind).toBe('month');
    expect(s.kind === 'month' && s.summary.month).not.toBe(thisMonth);
  });

  it('is hidden for employees: no reads, no requests', async () => {
    mockCached = summary(10);
    const { state } = mount('acc-1', false);
    await flush();
    expect(state().kind).toBe('hidden');
    expect(mockReadQuery).not.toHaveBeenCalled();
    expect(mockQuery).not.toHaveBeenCalled();
  });

  it('never writes the shared summary cache (no-cache)', async () => {
    mockNetwork = summary(4);
    mount('acc-1');
    await flush();
    expect(mockQuery).toHaveBeenCalledWith(expect.objectContaining({ fetchPolicy: 'no-cache' }));
  });

  it('mid-switch: never shows or fetches with the previous account\'s cache and token', async () => {
    mockNetwork = summary(5);
    const { state, rerender } = mount('acc-1');
    await flush();
    mockQuery.mockClear();
    mockReadQuery.mockClear();
    mockCached = summary(5); // still acc-1's cache
    rerender('acc-2', true, true);
    await flush();
    expect(state().kind).toBe('loading');
    expect(mockReadQuery).not.toHaveBeenCalled();
    expect(mockQuery).not.toHaveBeenCalled();

    mockCached = null;
    mockNetwork = summary(8);
    rerender('acc-2', true, false); // switch settled: new token, empty cache
    await flush();
    expect(count(state())).toBe(8);
  });

  it('drops an answer that was requested for an earlier account', async () => {
    mockNetwork = summary(5);
    const { state, rerender } = mount('acc-1');
    await flush();
    let release!: (v: any) => void;
    mockQuery.mockImplementationOnce(() => new Promise(r => { release = r; }));
    rerender('acc-2'); // request for acc-2 in flight...
    mockNetwork = summary(4);
    rerender('acc-3'); // ...superseded by acc-3
    await flush();
    await act(async () => release({ data: { monthSummary: summary(99) } }));
    expect(count(state())).toBe(4);
  });

  it('a failed first load falls back to the invitation, not a placeholder forever', async () => {
    mockQuery.mockImplementationOnce(() => Promise.reject(new Error('offline')));
    const { state } = mount('acc-1');
    await flush();
    expect(state().kind).toBe('invite');
  });

  it('a failed refresh keeps the month already shown', async () => {
    mockNetwork = summary(6);
    const { state, rerender } = mount('acc-1');
    await flush();
    mockQuery.mockImplementationOnce(() => Promise.reject(new Error('offline')));
    rerender('acc-1', true, true);
    rerender('acc-1', true, false); // re-load (stands in for foreground)
    await flush();
    expect(count(state())).toBe(6);
  });
});
