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
jest.mock('../../hooks/useMonthInsights', () => ({ useMonthInsights: () => ({ ...mockInsights, refresh: jest.fn() }) }));

import { MonthSummaryScreen } from '../MonthSummaryScreen';

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

it('a quiet current month still shows savings and habitual payments, with the empty message below (R25)', () => {
  mockSummary = summary(0);
  mockInsights = { revealed: true, insights: recurring, savings, protection: null };
  const tree = mount();
  expect(has(tree, 'tumes-summary-card')).toBe(false);
  expect(order(tree)).toEqual(['tumes-savings-card', 'tumes-recurring-card']);
  expect(has(tree, 'month-summary-empty')).toBe(true);
});

it('a quiet past month keeps savings but not habitual payments (23A, R25)', () => {
  mockSummary = summary(0, true);
  mockParams = { year: 2025, month: 3 };
  mockInsights = { revealed: true, insights: recurring, savings, protection: null };
  const tree = mount();
  expect(order(tree)).toEqual(['tumes-savings-card']);
});

it('a quiet month waits on the skeleton until the reveal decides', () => {
  mockSummary = summary(0);
  mockInsights = { revealed: false };
  const tree = mount();
  expect(has(tree, 'month-summary-loading')).toBe(true);
});
