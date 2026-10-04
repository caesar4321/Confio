/**
 * The hero line sits above Enviar/Recibir, so it must never pop in from a late
 * network answer while the user may be reaching for those buttons (design 2A).
 * It shows only from cache, only at >= 3 movements, and never for employees.
 */
import React from 'react';
import renderer, { act } from 'react-test-renderer';

let mockCached: any = null;
let mockNetwork: any = null;
const mockQuery = jest.fn(() => Promise.resolve({ data: { monthSummary: mockNetwork } }));
const mockReadQuery = jest.fn(() => (mockCached ? { monthSummary: mockCached } : null));

jest.mock('@apollo/client', () => ({
  gql: (s: TemplateStringsArray) => s.join(''),
  useApolloClient: () => ({ readQuery: mockReadQuery, query: mockQuery }),
}));
// Focus behaves like the real hook on an always-focused screen: runs on
// mount and again whenever the callback identity changes.
jest.mock('@react-navigation/native', () => ({
  useFocusEffect: (cb: () => void | (() => void)) => require('react').useEffect(cb, [cb]),
}));

import { useMonthHeroLine } from '../useMonthHeroLine';

const summary = (movementCount: number) => ({
  year: 2026, month: 10, timezone: 'UTC', previousIsPartial: true,
  current: { incomeUsd: '420', spendingUsd: '310', movementCount, spendingByCategory: [] },
  previous: null, counterparties: [],
});

const mount = (accountKey: string | null, enabled = true, switching = false) => {
  let api!: ReturnType<typeof useMonthHeroLine>;
  const Probe = ({ k, e, w }: { k: string | null; e: boolean; w: boolean }) => {
    api = useMonthHeroLine(k, e, w);
    return null;
  };
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<Probe k={accountKey} e={enabled} w={switching} />); });
  mounted.push(tree);
  return {
    hook: () => api,
    rerender: (k: string | null, e = true, w = false) => act(() => tree.update(<Probe k={k} e={e} w={w} />)),
  };
};

const flush = () => act(async () => {});

// The hook keeps a month-boundary timer; unmount so it cannot outlive a test.
const mounted: renderer.ReactTestRenderer[] = [];
afterEach(() => {
  while (mounted.length) act(() => mounted.pop()!.unmount());
});

beforeEach(() => {
  mockCached = null;
  mockNetwork = null;
  mockQuery.mockClear();
  mockReadQuery.mockClear();
});

describe('useMonthHeroLine', () => {
  it('shows a cached month with 3+ movements immediately', async () => {
    mockCached = summary(3);
    const { hook } = mount('acc-1');
    await flush();
    expect(hook().summary?.current.movementCount).toBe(3);
  });

  it('hides the line below 3 movements', async () => {
    mockCached = summary(2);
    const { hook } = mount('acc-1');
    await flush();
    expect(hook().summary).toBeNull();
  });

  it('never inserts a late network answer on a cold cache (no layout jump)', async () => {
    mockNetwork = summary(10);
    const { hook } = mount('acc-1');
    await flush();
    expect(mockQuery).toHaveBeenCalled();
    expect(hook().summary).toBeNull();
  });

  it('is disabled for employees: no reads, no requests, nothing shown', async () => {
    mockCached = summary(10);
    const { hook } = mount('acc-1', false);
    await flush();
    expect(hook().summary).toBeNull();
    expect(mockReadQuery).not.toHaveBeenCalled();
    expect(mockQuery).not.toHaveBeenCalled();
  });

  it('replaces the previous account\'s month after an account switch', async () => {
    mockCached = summary(5);
    const { hook, rerender } = mount('acc-1');
    await flush();
    expect(hook().summary?.current.movementCount).toBe(5);

    mockCached = null; // Apollo store is cleared on account switch
    mockNetwork = summary(7);
    rerender('acc-2');
    expect(hook().summary).toBeNull(); // never the other account's numbers
    await flush();
    expect(hook().summary?.current.movementCount).toBe(7);
  });

  it('mid-switch, never shows or fetches with the previous account\'s cache and token', async () => {
    mockCached = summary(5);
    const { hook, rerender } = mount('acc-1');
    await flush();
    mockQuery.mockClear();
    mockReadQuery.mockClear();

    // activeAccount already says acc-2, but the JWT/cache are still acc-1's
    rerender('acc-2', true, true);
    await flush();
    expect(hook().summary).toBeNull();
    expect(mockReadQuery).not.toHaveBeenCalled();
    expect(mockQuery).not.toHaveBeenCalled();

    mockCached = null;
    mockNetwork = summary(8);
    rerender('acc-2', true, false); // switch settled: new token, empty cache
    await flush();
    expect(hook().summary?.current.movementCount).toBe(8);
  });

  it('drops an answer that was requested for an earlier account', async () => {
    mockCached = summary(5);
    const { hook, rerender } = mount('acc-1');
    await flush();
    let release!: (v: any) => void;
    mockCached = null;
    mockQuery.mockImplementationOnce(() => new Promise(r => { release = r; }));
    rerender('acc-2'); // request for acc-2 in flight...
    mockNetwork = summary(4);
    rerender('acc-3'); // ...superseded by acc-3
    await flush();
    await act(async () => release({ data: { monthSummary: summary(99) } }));
    expect(hook().summary?.current.movementCount).toBe(4);
  });

  it('a repeated load for the new account still lets its answer replace the line', async () => {
    mockCached = summary(5);
    const { hook, rerender } = mount('acc-1');
    await flush();
    mockCached = null;
    mockNetwork = summary(6);
    rerender('acc-2', true, true);
    rerender('acc-2', true, false); // load #1 marks acc-2 for replacement
    rerender('acc-2', true, true);
    rerender('acc-2', true, false); // load #2 supersedes #1 before it answers
    await flush();
    expect(hook().summary?.current.movementCount).toBe(6);
  });

  it('returning from an employee account still replaces the line', async () => {
    mockCached = summary(5);
    const { hook, rerender } = mount('personal');
    await flush();
    rerender('employee', false); // employees: disabled
    await flush();
    expect(hook().summary).toBeNull();
    mockCached = null;
    mockNetwork = summary(9);
    rerender('personal', true);
    await flush();
    expect(hook().summary?.current.movementCount).toBe(9);
  });

  it('never writes the shared summary cache (no-cache) and reuses its own answer next focus', async () => {
    mockNetwork = summary(4);
    const { hook, rerender } = mount('acc-1');
    await flush();
    expect(mockQuery).toHaveBeenCalledWith(expect.objectContaining({ fetchPolicy: 'no-cache' }));
    expect(hook().summary).toBeNull(); // cold start: no late insert
    rerender('acc-1', true, true); // any re-load (stands in for the next focus)
    rerender('acc-1', true, false);
    await flush();
    expect(hook().summary?.current.movementCount).toBe(4);
  });
});

