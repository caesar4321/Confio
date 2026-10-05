import React from 'react';
import renderer, { act } from 'react-test-renderer';

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
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
jest.mock('@apollo/client', () => ({
  ...jest.requireActual('@apollo/client'),
  useQuery: (q: any) => (q.definitions?.[0]?.name?.value === 'MonthSummary'
    ? { data: { monthSummary: mockSummary }, loading: false, error: undefined, refetch: jest.fn().mockResolvedValue({}) }
    : { data: { monthMovements: [] }, refetch: jest.fn().mockResolvedValue({}) }),
}));
let mockInsights: any;
const mockRefreshStocks = jest.fn();
jest.mock('../../hooks/useMonthInsights', () => ({
  useMonthInsights: () => ({ ...mockInsights, refresh: jest.fn(), refreshStocks: mockRefreshStocks }),
}));

import { MonthSummaryScreen, SETTLING_MAX_TRIES, SETTLING_POLL_MS } from '../MonthSummaryScreen';

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

beforeEach(() => { mockParams = {}; });

it('shows Card A first and holds every insight and section until the reveal', () => {
  mockSummary = summary(3);
  mockInsights = { revealed: false };
  const tree = mount();
  expect(has(tree, 'tumes-summary-card')).toBe(true);
  expect(has(tree, 'tumes-revealed')).toBe(false);
  expect(has(tree, 'categorize-cta')).toBe(false);
});

it('reveals the dollar slot, then habitual payments, in fixed order', () => {
  mockSummary = summary(3);
  mockInsights = { revealed: true, insights: recurring, savings, protection: null };
  const tree = mount();
  expect(order(tree)).toEqual(['tumes-summary-card', 'tumes-savings-card', 'tumes-recurring-card']);
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
  act(() => { jest.advanceTimersByTime(SETTLING_POLL_MS * 2); });
  expect(mockRefreshStocks).toHaveBeenCalledTimes(2);
  act(() => { jest.advanceTimersByTime(SETTLING_POLL_MS * 100); });
  expect(mockRefreshStocks).toHaveBeenCalledTimes(SETTLING_MAX_TRIES);
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
