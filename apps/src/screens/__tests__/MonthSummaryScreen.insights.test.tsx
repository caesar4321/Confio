import React from 'react';
import renderer, { act } from 'react-test-renderer';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
// The full-screen intro is covered in TuMesIntro.test.tsx.
jest.mock('../../components/tuMes/TuMesIntro', () => ({ TuMesIntro: () => null }));
// Entrance motion is covered in motion.test.tsx; here the cards render in place.
jest.mock('../../components/tuMes/motion', () => ({ Rise: ({ children }: any) => children, Grow: ({ children }: any) => children }));
// Asset marks are SVG art (covered elsewhere); here only the rows matter.
jest.mock('../../components/CryptoAssetMark', () => ({ CryptoAssetMark: () => null }));
jest.mock('react-native-svg', () => {
  const R = require('react');
  const C = (p: any) => R.createElement('Svg', p, p.children);
  return { __esModule: true, default: C, Defs: C, LinearGradient: C, Rect: C, Stop: C };
});
jest.mock('../../navigation/Header', () => ({ Header: () => null }));
jest.mock('../../services/analyticsService', () => ({ AnalyticsService: { logFunnelEvent: jest.fn() } }));
jest.mock('../../contexts/NumberLocaleProvider', () => ({ useNumberLocale: () => ({ separators: { decimal: '.', group: ',' } }) }));
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: { id: 'a1', type: 'personal' } }) }));
let mockParams: any = {};
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ navigate: jest.fn() }),
  useRoute: () => ({ params: mockParams }),
  useFocusEffect: () => undefined,
}));
let mockSummary: any;
let mockComprar: any = null;
jest.mock('@apollo/client', () => ({
  ...jest.requireActual('@apollo/client'),
  useQuery: (q: any) => {
    const name = q.definitions?.[0]?.name?.value;
    if (name === 'MonthSummary') {
      return { data: { monthSummary: mockSummary }, loading: false, error: undefined, refetch: jest.fn().mockResolvedValue({}) };
    }
    if (name === 'MonthComprar') {
      return mockComprar === 'pending'
        ? { data: undefined, loading: true, refetch: jest.fn().mockResolvedValue({}) }
        : { data: { monthComprar: mockComprar }, loading: false, refetch: jest.fn().mockResolvedValue({}) };
    }
    return { data: { monthMovements: [] }, refetch: jest.fn().mockResolvedValue({}) };
  },
}));
let mockInsights: any;
const mockRefreshStocks = jest.fn();
const mockRefreshCrypto = jest.fn();
jest.mock('../../hooks/useMonthInsights', () => ({
  // Like the hook: polling follows the latest stocks answer of a shown card.
  useMonthInsights: () => ({
    stocksSettling: Boolean(mockInsights?.stocks) && mockInsights.stocks.state === 'settling',
    cryptoSettling: Boolean(mockInsights?.crypto) && mockInsights.crypto.state === 'settling',
    ...mockInsights, refresh: jest.fn(), refreshStocks: mockRefreshStocks, refreshCrypto: mockRefreshCrypto,
  }),
}));

import {
  comprarMonthRows, MonthSummaryScreen, SETTLING_FAST_TRIES, SETTLING_MAX_TRIES, SETTLING_POLL_MS, SETTLING_SLOW_MS,
} from '../MonthSummaryScreen';

const totals = (spending: string, count: number) => ({
  incomeUsd: '215.00', spendingUsd: spending, topUpsUsd: '0', withdrawalsUsd: '0', savingsNetUsd: '0',
  investmentNetUsd: '0', movementCount: count, spendingByCategory: count ? [{ category: 'food', amountUsd: spending }] : [],
});
const now = new Date();
const summary = (count: number, past = false) => ({
  year: past ? 2025 : now.getFullYear(), month: past ? 3 : now.getMonth() + 1, timezone: 'UTC', previousIsPartial: !past,
  current: totals(count ? '176.00' : '0', count), previous: totals('150.00', 2),
  counterparties: count ? [{ key: 'user:2', name: 'Karen', receivedUsd: '0', sentUsd: '100.00' }] : [],
});
const recurring = { previousMonthSpendingUsd: '390.00', recurring: [
  { counterpartyKey: 'user:2', name: 'Karen', expectedDay: 5, expectedAmountUsd: '100.00', category: null }] };
const savings = { earnedUsd: '0.42', daily: [] };

function mount() {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<MonthSummaryScreen />); });
  return tree;
}
const has = (tree: renderer.ReactTestRenderer, id: string) =>
  tree.root.findAll((n) => typeof n.type === 'string' && n.props.testID === id).length > 0;
const order = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAll((n) => typeof n.type === 'string' && typeof n.props.testID === 'string'
    && n.props.testID.startsWith('tumes-') && n.props.testID.endsWith('-card')).map((n) => n.props.testID);

beforeEach(() => { mockParams = {}; mockComprar = null; });

it('gives Comprar its own section only in a month with orders', () => {
  mockSummary = summary(3);
  mockInsights = { revealed: true, insights: recurring, savings };
  expect(has(mount(), 'tumes-comprar')).toBe(false);
  mockComprar = { purchasesUsd: '54.00', purchaseCount: 2, salesUsd: '27.60', saleCount: 1 };
  const tree = mount();
  expect(has(tree, 'tumes-comprar')).toBe(true);
  const text = tree.root.findAll((n) => typeof n.props.children === 'string').map((n) => n.props.children);
  expect(text).toEqual(expect.arrayContaining(['Comprar', 'Compraste', '2 pedidos', 'Vendiste', '1 venta, ya sin comisión']));
});

it('never inserts a late Comprar answer above sections already shown', () => {
  jest.useFakeTimers();
  try {
    mockSummary = summary(3);
    mockInsights = { revealed: true, insights: recurring, savings };
    mockComprar = 'pending';
    const tree = mount();
    expect(has(tree, 'tumes-sections-loading')).toBe(true);   // sections wait for it
    act(() => { jest.advanceTimersByTime(4000); });          // ...but not forever
    expect(has(tree, 'tumes-sections-loading')).toBe(false);
    mockComprar = { purchasesUsd: '54.00', purchaseCount: 2, salesUsd: '0.00', saleCount: 0 };
    act(() => { tree.update(<MonthSummaryScreen />); });
    expect(has(tree, 'tumes-comprar')).toBe(false);          // decided for this view
  } finally {
    jest.useRealTimers();
  }
});

it('lists only the Comprar rows that happened', () => {
  expect(comprarMonthRows({ purchasesUsd: '0.00', purchaseCount: 0, salesUsd: '9.20', saleCount: 1 }).map((r) => r.value))
    .toEqual(['sale']);
  expect(comprarMonthRows({ purchasesUsd: '0.00', purchaseCount: 0, salesUsd: '0.00', saleCount: 0 })).toEqual([]);
  // A revealed section keeps its rows: a refund zeroes "Compraste", a new sale adds nothing.
  const frozen = comprarMonthRows({ purchasesUsd: '0.00', purchaseCount: 0, salesUsd: '9.20', saleCount: 1 }, ['buy']);
  expect(frozen.map((r) => [r.value, r.amount])).toEqual([['buy', 0]]);
});

it('shows Card A first and holds every insight and section until the reveal', () => {
  mockSummary = summary(3);
  mockInsights = { revealed: false };
  const tree = mount();
  expect(has(tree, 'tumes-summary-card')).toBe(true);
  expect(has(tree, 'tumes-revealed')).toBe(false);
  expect(has(tree, 'categorize-cta')).toBe(false);
  expect(has(tree, 'tumes-insights-loading')).toBe(true);     // placeholders, never a blank screen
});

it('reveals the dollar slot, then habitual payments, in fixed order', () => {
  mockSummary = summary(3);
  mockInsights = { revealed: true, insights: recurring, savings, protection: null };
  const tree = mount();
  expect(order(tree)).toEqual(['tumes-summary-card', 'tumes-savings-card', 'tumes-recurring-card']);
  expect(has(tree, 'tumes-insights-loading')).toBe(false);    // the placeholders give way
});

it('a quiet month shows every section with inviting empty states (founder 2026-10-04)', () => {
  mockSummary = summary(0);
  mockInsights = { revealed: true, insights: { previousMonthSpendingUsd: '0.00', recurring: [] }, savings: null, protection: null };
  const tree = mount();
  expect(order(tree)).toEqual(['tumes-summary-card', 'tumes-recurring-card']);
  for (const id of ['tumes-quiet-actions', 'tumes-savings-invite', 'tumes-recurring-empty', 'empty-spending',
    'empty-own', 'empty-people']) {
    expect(has(tree, id)).toBe(true);
  }
});

it('an unknown answer never shows a fake zero: a failed insights query hides the habitual-payments card', () => {
  mockSummary = summary(0);
  mockInsights = { revealed: true, insights: null, savings: null, protection: null };
  const tree = mount();
  expect(has(tree, 'tumes-recurring-card')).toBe(false);
});

it('a quiet past month keeps savings (23A)', () => {
  mockSummary = summary(0, true);
  mockParams = { year: 2025, month: 3 };
  mockInsights = { revealed: true, insights: recurring, savings, protection: null };
  const tree = mount();
  expect(order(tree)).toEqual(['tumes-summary-card', 'tumes-savings-card', 'tumes-recurring-card']);
  expect(has(tree, 'tumes-savings-invite')).toBe(false);
});

const stockGain = {
  state: 'gain', canBuy: true, valueUsd: '220.00', valueStartUsd: '100.00', boughtUsd: '105.00', soldUsd: '0.00',
  gainUsd: '15.00', gainPct: '7.32', holdings: 1, topMover: { ticker: 'NVDA', name: 'NVIDIA', changePct: '10.00' },
};

it('"Tus acciones" sits under the dollar slot, above habitual payments', () => {
  mockSummary = summary(3);
  mockInsights = { revealed: true, insights: recurring, savings, protection: null, stocks: stockGain };
  const tree = mount();
  expect(order(tree)).toEqual(['tumes-summary-card', 'tumes-savings-card', 'tumes-stocks-card', 'tumes-recurring-card']);
});

it('no stocks: an invitation only where buying is offered; unknown shows nothing', () => {
  mockSummary = summary(3);
  const none = { ...stockGain, state: 'none', gainUsd: null, topMover: null };
  mockInsights = { revealed: true, insights: recurring, savings, protection: null, stocks: none };
  expect(has(mount(), 'tumes-stocks-invite')).toBe(true);
  mockInsights = { ...mockInsights, stocks: { ...none, canBuy: false } };
  expect(has(mount(), 'tumes-stocks-invite')).toBe(false);
  mockInsights = { ...mockInsights, stocks: null };
  const tree = mount();
  expect(has(tree, 'tumes-stocks-invite') || has(tree, 'tumes-stocks-card')).toBe(false);
});

it('a settling trade (arriving from a buy) shows the card and re-asks stocks until it resolves, bounded', () => {
  jest.useFakeTimers();
  mockRefreshStocks.mockClear();
  mockSummary = summary(3);
  mockInsights = { revealed: true, insights: recurring, savings, protection: null,
    stocks: { ...stockGain, state: 'settling', gainUsd: null, gainPct: null, valueStartUsd: null } };
  const tree = mount();
  expect(has(tree, 'tumes-stocks-card')).toBe(true);
  expect(has(tree, 'tumes-stocks-settling-note')).toBe(true);
  const note = () => tree.root.findAll((n) => typeof n.type === 'string'
    && n.props.testID === 'tumes-stocks-settling-note')[0].props.children;
  act(() => { jest.advanceTimersByTime(SETTLING_POLL_MS * 2); });
  expect(mockRefreshStocks).toHaveBeenCalledTimes(2);
  expect(note()).toMatch(/En unos segundos/);
  act(() => { jest.advanceTimersByTime(SETTLING_POLL_MS * (SETTLING_FAST_TRIES - 2)); });
  expect(mockRefreshStocks).toHaveBeenCalledTimes(SETTLING_FAST_TRIES);
  expect(note()).toMatch(/tardando/);                  // no "seconds" promise past the first minute
  act(() => { jest.advanceTimersByTime(SETTLING_POLL_MS); });
  expect(mockRefreshStocks).toHaveBeenCalledTimes(SETTLING_FAST_TRIES);   // now every 30s
  act(() => { jest.advanceTimersByTime(SETTLING_SLOW_MS * 100); });
  expect(mockRefreshStocks).toHaveBeenCalledTimes(SETTLING_MAX_TRIES);
  expect(note()).toMatch(/Vuelve más tarde/);
  act(() => tree.unmount());
  jest.useRealTimers();
});

const cryptoGain = {
  state: 'gain', valueUsd: '140.00', valueStartUsd: '60.00', boughtUsd: '66.00', soldUsd: '0.00',
  gainUsd: '14.00', gainPct: '11.11', holdings: 1,
  assets: [{ symbol: 'BTCB', ticker: 'BTC', name: 'Bitcoin', category: 'crypto', changePct: '16.67' }],
};

it('"Oro y Bitcoin" sits under "Tus acciones"; none or unknown draws nothing', () => {
  mockSummary = summary(3);
  mockInsights = { revealed: true, insights: recurring, savings, protection: null, stocks: stockGain, crypto: cryptoGain };
  expect(order(mount())).toEqual(['tumes-summary-card', 'tumes-savings-card', 'tumes-stocks-card',
    'tumes-crypto-card', 'tumes-recurring-card']);
  mockInsights = { ...mockInsights, crypto: { ...cryptoGain, state: 'none', assets: [] } };
  expect(has(mount(), 'tumes-crypto-card')).toBe(false);
  mockInsights = { ...mockInsights, crypto: null };
  expect(has(mount(), 'tumes-crypto-card')).toBe(false);
});

it('a settling crypto card is polled alone (stocks resolved stays quiet)', () => {
  jest.useFakeTimers();
  mockRefreshStocks.mockClear();
  mockRefreshCrypto.mockClear();
  mockSummary = summary(3);
  mockInsights = { revealed: true, insights: recurring, savings, protection: null, stocks: stockGain,
    crypto: { ...cryptoGain, state: 'settling', gainUsd: null, gainPct: null, valueStartUsd: null } };
  const tree = mount();
  expect(has(tree, 'tumes-crypto-settling-note')).toBe(true);
  act(() => { jest.advanceTimersByTime(SETTLING_POLL_MS * 2); });
  expect(mockRefreshCrypto).toHaveBeenCalledTimes(2);
  expect(mockRefreshStocks).not.toHaveBeenCalled();
  act(() => tree.unmount());
  jest.useRealTimers();
});

it('each card has its own poll budget: a stalled crypto poll never blocks a new stocks one', () => {
  jest.useFakeTimers();
  mockRefreshStocks.mockClear();
  mockRefreshCrypto.mockClear();
  mockSummary = summary(3);
  const settlingCrypto = { ...cryptoGain, state: 'settling', gainUsd: null, gainPct: null, valueStartUsd: null };
  mockInsights = { revealed: true, insights: recurring, savings, protection: null, stocks: stockGain, crypto: settlingCrypto };
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<MonthSummaryScreen />); });
  act(() => { jest.advanceTimersByTime(SETTLING_POLL_MS * SETTLING_FAST_TRIES + SETTLING_SLOW_MS * 100); });
  expect(mockRefreshCrypto).toHaveBeenCalledTimes(SETTLING_MAX_TRIES);      // crypto stalled
  mockInsights = { ...mockInsights, stocks: { ...stockGain, state: 'settling', gainUsd: null, gainPct: null, valueStartUsd: null } };
  act(() => { tree.update(<MonthSummaryScreen />); });
  act(() => { jest.advanceTimersByTime(SETTLING_POLL_MS * 2); });
  expect(mockRefreshStocks).toHaveBeenCalledTimes(2);
  expect(mockRefreshCrypto).toHaveBeenCalledTimes(SETTLING_MAX_TRIES);      // still stalled, not restarted
  act(() => tree.unmount());
  jest.useRealTimers();
});

it('a resolved month does not poll', () => {
  jest.useFakeTimers();
  mockRefreshStocks.mockClear();
  mockSummary = summary(3);
  mockInsights = { revealed: true, insights: recurring, savings, protection: null, stocks: stockGain };
  const tree = mount();
  act(() => { jest.advanceTimersByTime(SETTLING_POLL_MS * 5); });
  expect(mockRefreshStocks).not.toHaveBeenCalled();
  act(() => tree.unmount());
  jest.useRealTimers();
});

it('a link back with a month (pop + merge) shows that month, not the one being browsed', () => {
  mockSummary = summary(3);
  mockInsights = { revealed: false };
  mockParams = { year: 2025, month: 3 };
  const tree = mount();
  const title = () => tree.root.findAll((n) => typeof n.type === 'string' && n.props.accessibilityRole === 'header')
    .map((n) => [].concat(n.props.children).join('')).join('|');
  expect(title()).toContain('2025');
  mockParams = { year: now.getFullYear(), month: now.getMonth() + 1 };
  act(() => { tree.update(<MonthSummaryScreen />); });
  expect(title()).toContain(String(now.getFullYear()));
  expect(title()).not.toContain('2025');
  act(() => { tree.unmount(); });
});
