import React from 'react';
import renderer, {act} from 'react-test-renderer';

const mockNavigate = jest.fn();
let mockPositions: {ticker: string; name?: string; valueUsd: number}[] = [];
const mockStocks = [
  {ticker: 'NVDA', symbol: 'NVDAon', name: 'NVIDIA', priceUsd: 181, dayChangePct: 1.3, color: '#000', logoUrl: '', offHours: false, sparkline24h: []},
  {ticker: 'AAPL', symbol: 'AAPLon', name: 'Apple', priceUsd: 231, dayChangePct: -0.4, color: '#000', logoUrl: '', offHours: false, sparkline24h: []},
  {ticker: 'SPY', symbol: 'SPYon', name: 'S&P 500', priceUsd: 662, dayChangePct: 0.8, color: '#000', logoUrl: '', offHours: false, sparkline24h: []},
  {ticker: 'GLD', symbol: 'GLDon', name: 'Oro', priceUsd: 300, dayChangePct: 0.1, color: '#000', logoUrl: '', offHours: false, sparkline24h: []},
];

jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-safe-area-context', () => ({SafeAreaView: 'SafeAreaView'}));
jest.mock('react-native-svg', () => ({
  __esModule: true, default: 'Svg', Defs: 'Defs', Stop: 'Stop', LinearGradient: 'LinearGradient', Rect: 'Rect', Circle: 'Circle',
}));
jest.mock('@react-navigation/native', () => ({useNavigation: () => ({navigate: mockNavigate, goBack: jest.fn()})}));
jest.mock('../../components/TickerLogo', () => ({TickerLogo: 'TickerLogo'}));
jest.mock('../../hooks/useGmMarket', () => ({useGmMarket: () => ({session: 'core', stocks: mockStocks, loading: false})}));
jest.mock('../../hooks/useSavingsPortfolio', () => ({
  useSavingsPortfolio: () => ({
    savings: {balanceUsd: 120},
    stocks: {
      enabled: true,
      positions: mockPositions,
      totalUsd: mockPositions.reduce((sum, p) => sum + p.valueUsd, 0),
      earnedTodayUsd: 0,
    },
  }),
}));
jest.mock('../../utils/numberFormatting', () => ({
  useNumberFormat: () => ({formatNumber: (v: number) => v.toFixed(2)}),
}));

import {StocksListScreen} from '../StocksListScreen';

const texts = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAllByType('Text' as any).map(t => [].concat(t.props.children).join(''));

beforeEach(() => {
  jest.clearAllMocks();
  mockPositions = [];
});

it('invites a first-time investor, with a factual starter shelf and no warning box', async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<StocksListScreen />);});
  const t = texts(tree);
  expect(t).toContain('Invierte en las empresas que usas');
  expect(t).toContain('Empieza por aquí');
  expect(t).toContain('500 grandes empresas en una compra');
  expect(t.join('|')).not.toMatch(/No sabes por dónde empezar|pueden bajar de valor\. Explora/);
  expect(t).not.toContain('Tus acciones');
  expect(t).toContain('Todas · 4');
  await act(async () => tree.unmount());
});

it('leads with what the user owns, largest first', async () => {
  mockPositions = [{ticker: 'AAPL', name: 'Apple', valueUsd: 5} as any, {ticker: 'NVDA', name: 'NVIDIA', valueUsd: 20} as any];
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<StocksListScreen />);});
  const t = texts(tree);
  expect(t).toContain('Tu inversión en EE.UU.');
  // What it is made of, largest first, shares adding up to 100.
  expect(t).toContain('NVIDIA 80%');
  expect(t).toContain('Apple 20%');
  expect(t).not.toContain('Invierte en las empresas que usas');
  const mine = t.indexOf('Tus acciones');
  const all = t.indexOf('Todas · 4');
  expect(mine).toBeGreaterThan(-1);
  expect(mine).toBeLessThan(all);
  const firstOwned = t.indexOf('NVDA', mine);
  expect(firstOwned).toBeGreaterThan(mine);
  expect(firstOwned).toBeLessThan(t.indexOf('AAPL', mine));
  await act(async () => tree.unmount());
});

it('keeps "¿Cómo funciona?" reachable at the top, not after 450 rows', async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<StocksListScreen />);});
  await act(async () => {
    tree.root.findByProps({accessibilityLabel: 'Cómo funcionan las acciones de Estados Unidos'}).props.onPress();
  });
  expect(mockNavigate).toHaveBeenCalledWith('OndoStocksInfo');
  await act(async () => tree.unmount());
});

it('rounds the allocation legend to exactly 100%', async () => {
  mockPositions = [
    {ticker: 'AAPL', name: 'Apple', valueUsd: 10},
    {ticker: 'NVDA', name: 'NVIDIA', valueUsd: 10},
    {ticker: 'SPY', name: 'S&P 500', valueUsd: 10},
  ];
  let tree!: renderer.ReactTestRenderer;
  await act(async () => {tree = renderer.create(<StocksListScreen />);});
  const pcts = texts(tree)
    .map(x => x.match(/^(Apple|NVIDIA|S&P 500) (\d+)%$/))
    .filter(Boolean)
    .map(m => Number(m![2]));
  expect(pcts).toHaveLength(3);
  expect(pcts.reduce((a, b) => a + b, 0)).toBe(100);
  await act(async () => tree.unmount());
});
