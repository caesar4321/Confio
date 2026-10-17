import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Pressable } from 'react-native';
import { setNumberLocaleCountry } from '../../utils/numberLocale';

beforeAll(() => setNumberLocaleCountry('VE'));
afterAll(() => setNumberLocaleCountry(null));

let mockStats: any;
const mockNavigate = jest.fn();
jest.mock('@apollo/client', () => ({
  gql: (strings: TemplateStringsArray) => strings.join(''),
  useQuery: () => ({ data: mockStats === undefined ? undefined : { gmTradingStats: mockStats }, loading: false, refetch: jest.fn() }),
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
  beforeEach(() => { mockStats = STATS; mockNavigate.mockClear(); });

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
