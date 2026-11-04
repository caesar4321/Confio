import React from 'react';
import renderer, { act } from 'react-test-renderer';

const mockUseQuery = jest.fn((..._a: any[]) => ({ data: { gmMarket: { assets: [{ ticker: 'TSLA', logoUrl: 'https://x/TSLA.png' }] } } }));
jest.mock('@apollo/client', () => ({ useQuery: (...a: any[]) => mockUseQuery(...a) }));
jest.mock('../useGmMarket', () => ({ GM_MARKET: 'GM_MARKET' }));

import { useLogoGate, useStockLogoUrl } from '../useShareLogo';

function probe<T>(fn: () => T) {
  const out: { current?: T } = {};
  const P = () => { out.current = fn(); return null; };
  act(() => { renderer.create(<P />); });
  return out;
}

describe('useStockLogoUrl', () => {
  it('reads the cache once (no polling) and finds the logo case-insensitively', () => {
    expect(probe(() => useStockLogoUrl('tsla')).current).toBe('https://x/TSLA.png');
    const opts = mockUseQuery.mock.calls[0][1];
    expect(opts).toEqual({ skip: false, fetchPolicy: 'cache-first' });
    expect(opts.pollInterval).toBeUndefined();
  });

  it('skips the query entirely without a ticker (crypto cards)', () => {
    mockUseQuery.mockClear();
    expect(probe(() => useStockLogoUrl(null)).current).toBeUndefined();
    expect(mockUseQuery.mock.calls[0][1].skip).toBe(true);
  });
});

describe('useLogoGate', () => {
  it('waits for the image of that url, released by its own load', async () => {
    const gate = probe(() => useLogoGate()).current!;
    gate.onPending('a');
    let done = false;
    const w = gate.wait('a', 10_000).then(() => { done = true; });
    gate.onSettled('b');
    await Promise.resolve();
    expect(done).toBe(false);
    gate.onSettled('a');
    await w;
    expect(done).toBe(true);
  });

  it('a remounted image is pending again', async () => {
    jest.useFakeTimers();
    const gate = probe(() => useLogoGate()).current!;
    gate.onSettled('a');
    await expect(gate.wait('a')).resolves.toBeUndefined();
    gate.onPending('a');
    let done = false;
    gate.wait('a', 500).then(() => { done = true; });
    await Promise.resolve();
    expect(done).toBe(false);
    jest.advanceTimersByTime(500);
    await Promise.resolve();
    expect(done).toBe(true);
    jest.useRealTimers();
  });

  it('no url means no wait', async () => {
    await expect(probe(() => useLogoGate()).current!.wait(undefined)).resolves.toBeUndefined();
  });
});
