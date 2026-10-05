import React from 'react';
import renderer, { act } from 'react-test-renderer';

const mockRefetch = jest.fn(() => Promise.resolve({}));
let mockData: any;
let mockFocus: () => void = () => undefined;
jest.mock('@apollo/client', () => ({
  ...jest.requireActual('@apollo/client'),
  useQuery: (_q: any, opts: any) => ({ data: opts.skip ? undefined : mockData, refetch: mockRefetch }),
}));
jest.mock('@react-navigation/native', () => ({
  useFocusEffect: (cb: () => void) => { mockFocus = cb; },
}));

import { stockMonthGain, useStockMonthNow } from '../useStockMonthNow';

let latest: any;
function Probe({ enabled }: { enabled: boolean }) {
  latest = useStockMonthNow(enabled);
  return null;
}

beforeEach(() => { mockRefetch.mockClear(); mockData = { stockMonth: { state: 'gain', gainUsd: '4.20' } }; });

it('re-reads on every refocus after the first, so a trade shows up', () => {
  act(() => { renderer.create(<Probe enabled />); });
  act(() => mockFocus());                 // first focus: the mount already fetched
  expect(mockRefetch).not.toHaveBeenCalled();
  act(() => mockFocus());                 // back from a buy
  expect(mockRefetch).toHaveBeenCalledTimes(1);
  expect(stockMonthGain(latest)).toBe(4.2);
});

it('disabled: no data and no refetch', () => {
  act(() => { renderer.create(<Probe enabled={false} />); });
  act(() => mockFocus());
  act(() => mockFocus());
  expect(mockRefetch).not.toHaveBeenCalled();
  expect(latest).toBeNull();
});

it('only an exact month result is a number', () => {
  expect(stockMonthGain({ state: 'value_only', gainUsd: null } as any)).toBeNull();
  expect(stockMonthGain(null)).toBeNull();
  expect(stockMonthGain({ state: 'gain', gainUsd: '-3.10' } as any)).toBe(-3.1);
});

describe('openTuMesNow', () => {
  const { openTuMesNow } = require('../useStockMonthNow');
  const mockHidden = jest.spyOn(require('../../utils/balanceVisibility'), 'isBalanceHidden');

  it('never unmasks a Tu mes already in the stack', async () => {
    mockHidden.mockResolvedValue(false);
    const navigate = jest.fn();
    const navigation = {
      navigate,
      getState: () => ({ routes: [{ name: 'MonthSummary', params: { masked: true } }, { name: 'BuyStock' }] }),
    };
    await openTuMesNow(navigation as any);
    expect(navigate.mock.calls[0][1].masked).toBe(true);
  });

  it('reads the Tu mes the pop goes back to (the topmost one)', async () => {
    mockHidden.mockResolvedValue(false);
    const navigate = jest.fn();
    const navigation = {
      navigate,
      getState: () => ({ routes: [{ name: 'MonthSummary', params: { masked: false } }, { name: 'AccountDetail' },
        { name: 'MonthSummary', params: { masked: true } }, { name: 'StocksList' }] }),
    };
    await openTuMesNow(navigation as any);
    expect(navigate.mock.calls[0][1].masked).toBe(true);
  });

  it('masks like Home when no Tu mes is in the stack', async () => {
    mockHidden.mockResolvedValue(true);
    const navigate = jest.fn();
    await openTuMesNow({ navigate, getState: () => ({ routes: [{ name: 'BuyStock' }] }) } as any);
    expect(navigate.mock.calls[0][1].masked).toBe(true);
    mockHidden.mockResolvedValue(false);
    await openTuMesNow({ navigate, getState: () => ({ routes: [] }) } as any);
    expect(navigate.mock.calls[1][1].masked).toBe(false);
  });

  it('marks a visit from a trade (longer reveal for the stocks card) and keeps pop + merge', async () => {
    mockHidden.mockResolvedValue(false);
    const navigate = jest.fn();
    await openTuMesNow({ navigate, getState: () => ({ routes: [] }) } as any, { fromTrade: true });
    expect(navigate.mock.calls[0][1].fromTrade).toBe(true);
    expect(navigate.mock.calls[0][2]).toEqual({ pop: true, merge: true });
    await openTuMesNow({ navigate, getState: () => ({ routes: [] }) } as any);
    expect(navigate.mock.calls[1][1].fromTrade).toBe(false);
  });
});
