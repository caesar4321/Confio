import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Pressable } from 'react-native';
import { setNumberLocaleCountry } from '../../utils/numberLocale';

beforeAll(() => setNumberLocaleCountry('VE'));
afterAll(() => setNumberLocaleCountry(null));

let mockStats: any;
let mockInvestError = true; // default: an older server, the stock-only screen
let mockStocksEnabled = true;
const mockNavigate = jest.fn();
jest.mock('@apollo/client', () => ({
  gql: (strings: TemplateStringsArray) => strings.join(''),
  useQuery: (query: string, options: any) => {
    if (options?.skip) return { data: undefined, loading: false, refetch: jest.fn() };
    if (query.includes('investTradingStats')) {
      return mockInvestError
        ? { data: undefined, error: new Error('Cannot query field'), loading: false, refetch: jest.fn() }
        : { data: mockStats === undefined ? undefined : { investTradingStats: mockStats }, loading: false, refetch: jest.fn() };
    }
    return { data: mockStats === undefined ? undefined : { gmTradingStats: mockStats }, loading: false, refetch: jest.fn() };
  },
}));
jest.mock('../../hooks/useSavingsPortfolio', () => ({
  useSavingsPortfolio: () => ({ stocks: { enabled: mockStocksEnabled } }),
}));
jest.mock('@react-navigation/native', () => ({ useNavigation: () => ({ navigate: mockNavigate }) }));
jest.mock('../../navigation/Header', () => ({ Header: 'Header' }));
jest.mock('../../components/common/BrandFieldBackground', () => ({ BrandFieldBackground: () => null }));
jest.mock('../../components/EmptyState', () => {
  const ReactLocal = require('react');
  const { Text } = require('react-native');
  return { EmptyState: (props: any) => ReactLocal.createElement(Text, null, props.title) };
});
jest.mock('react-native-vector-icons/Feather', () => 'Icon');

import { StocksActivityScreen, typicalPurchaseLabel } from '../StocksActivityScreen';

const STATS = {
  totalUsd: 3424.6, buyUsd: 1900, sellUsd: 1524.6, buyCount: 140, sellCount: 104, traderCount: 18,
  medianBuyUsd: 2.4, since: '2026-08-05T00:00:00Z',
  topAssets: [
    { symbol: 'NVDAon', ticker: 'NVDA', name: 'NVIDIA', tradeCount: 26, traderCount: 7 },
    { symbol: 'AAPLon', ticker: 'AAPL', name: 'Apple', tradeCount: 24, traderCount: 8 },
  ],
};

const render = () => {
  let tree!: renderer.ReactTestRenderer;
  act(() => { tree = renderer.create(<StocksActivityScreen />); });
  return tree;
};
const text = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAll((n) => typeof n.props.children === 'string' || Array.isArray(n.props.children))
    .map((n) => [].concat(n.props.children).filter((c: any) => typeof c === 'string' || typeof c === 'number').join(''))
    .join(' ');

describe('StocksActivityScreen', () => {
  beforeEach(() => { mockStats = STATS; mockInvestError = true; mockStocksEnabled = true; mockNavigate.mockClear(); });

  it('tells the trading story: total, split, the typical purchase, the ranking', () => {
    const shown = text(render());
    expect(shown).toContain('3.425');
    expect(shown).toContain('244 compras y ventas · desde agosto de 2026');
    expect(shown).toContain('Compras');
    expect(shown).toContain('Ventas');
    expect(shown).toContain('La mitad de las compras fue de US$3 o menos');
    expect(shown).toContain('NVDA');
    expect(shown).toContain('al menos 3 personas');
  });

  it('opens a stock from the ranking, and the explorer from the button', () => {
    const tree = render();
    act(() => tree.root.find((n) => n.type === Pressable && n.props.accessibilityHint === 'Ver NVDA').props.onPress());
    expect(mockNavigate).toHaveBeenLastCalledWith('StockDetail', { ticker: 'NVDA' });
    act(() => tree.root.find((n) => n.type === Pressable && text({ root: n } as any).includes('Explorar acciones')).props.onPress());
    expect(mockNavigate).toHaveBeenLastCalledWith('StocksList');
  });

  it('never shows zeros when the stats are unknown', () => {
    mockStats = null;
    const shown = text(render());
    expect(shown).toContain('No pudimos cargar estos datos');
    expect(shown).not.toContain('0 USD');
  });

  it('shows only counts when the split is withheld for privacy', () => {
    mockStats = { ...STATS, buyUsd: null, sellUsd: null };
    const shown = text(render());
    expect(shown).toContain('140 operaciones');
    expect(shown).not.toContain('1.900 USD');
  });

  it('hides the typical purchase until it means something', () => {
    mockStats = { ...STATS, medianBuyUsd: null };
    expect(text(render())).not.toContain('La mitad de las compras');
  });

  it('rounds the typical purchase up so "o menos" stays true', () => {
    expect(typicalPurchaseLabel(2.01)).toBe('US$3');
    expect(typicalPurchaseLabel(3)).toBe('US$3');
    expect(typicalPurchaseLabel(0.4)).toBe('US$1');
  });
});

describe('StocksActivityScreen as Inversiones en movimiento', () => {
  const INVEST = {
    ...STATS,
    topAssets: [
      { symbol: 'BTCB', ticker: 'BTC', name: 'Bitcoin', tradeCount: 30, traderCount: 9, assetKind: 'crypto' },
      { symbol: 'NVDAon', ticker: 'NVDA', name: 'NVIDIA', tradeCount: 26, traderCount: 7, assetKind: 'stock' },
    ],
  };
  beforeEach(() => { mockStats = INVEST; mockInvestError = false; mockStocksEnabled = true; mockNavigate.mockClear(); });

  it('names stocks, gold and bitcoin and opens crypto rows on their own detail', () => {
    const tree = render();
    expect(tree.root.findByType('Header' as any).props.title).toBe('Inversiones en movimiento');
    expect(text(tree)).toContain('OPERADO EN ACCIONES, ORO Y BITCOIN');
    act(() => tree.root.find((n) => n.type === Pressable && n.props.accessibilityHint === 'Ver BTC').props.onPress());
    expect(mockNavigate).toHaveBeenLastCalledWith('CryptoDetail', { symbol: 'BTCB' });
  });

  it('a crypto-only member cannot open a stock or the stock explorer', () => {
    mockStocksEnabled = false;
    const tree = render();
    expect(tree.root.find((n) => n.type === Pressable && n.props.accessibilityHint === 'Ver NVDA').props.disabled).toBe(true);
    expect(tree.root.find((n) => n.type === Pressable && n.props.accessibilityHint === 'Ver BTC').props.disabled).toBe(false);
    expect(text(tree)).not.toContain('Explorar acciones');
  });

  it('an older server keeps the stock-only screen', () => {
    mockInvestError = true;
    mockStats = STATS;
    const tree = render();
    expect(tree.root.findByType('Header' as any).props.title).toBe('Acciones en movimiento');
  });
});
