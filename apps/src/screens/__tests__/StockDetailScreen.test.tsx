import React from 'react';
import renderer, {ReactTestRenderer, act} from 'react-test-renderer';

let mockCloses: number[];
let mockChartLoading: boolean;
let mockChartFailed: boolean;

const mockStock = {
  symbol: 'NVDAon',
  ticker: 'NVDA',
  name: 'NVIDIA',
  priceUsd: 180,
  dayChangePct: 1.25,
  color: '#059669',
  logoUrl: '',
  offHours: true,
  sparkline24h: [178, 180],
};

jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({navigate: jest.fn(), goBack: jest.fn()}),
  useRoute: () => ({params: {ticker: 'NVDA'}}),
}));
jest.mock('../../navigation/Header', () => ({Header: 'Header'}));
jest.mock('../../components/TickerLogo', () => ({TickerLogo: 'TickerLogo'}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('react-native-svg', () => ({
  __esModule: true,
  default: 'Svg',
  Polyline: 'Polyline',
}));
jest.mock('../../utils/numberFormatting', () => ({
  useNumberFormat: () => ({formatNumber: (value: number) => String(value)}),
}));
jest.mock('../../hooks/useSavingsPortfolio', () => ({
  useSavingsPortfolio: () => ({
    savings: {balanceUsd: 100},
    stocks: {
      enabled: true,
      tradingEnabled: false,
      buyEnabled: false,
      positions: [],
    },
  }),
}));
jest.mock('../../hooks/useGmMarket', () => ({
  GM_RANGES: ['1H', '6H', '12H', '1D', '1M', '3M', '6M', '1Y', 'MAX'],
  GM_RANGE_ACCESSIBILITY_LABELS: {
    '1H': '1 hora',
    '6H': '6 horas',
    '12H': '12 horas',
    '1D': '1 día',
    '1M': '1 mes',
    '3M': '3 meses',
    '6M': '6 meses',
    '1Y': '1 año',
    MAX: 'Máximo',
  },
  useGmMarket: () => ({
    byTicker: () => mockStock,
    tradabilityFor: () => 'open',
  }),
  useGmOhlc: () => ({
    closes: mockCloses,
    loading: mockChartLoading,
    failed: mockChartFailed,
  }),
  sparklineFor: () => [178, 180],
}));

import {StockDetailScreen} from '../StockDetailScreen';

const collectText = (node: any): string[] => {
  if (node == null || node === false) return [];
  if (typeof node === 'string' || typeof node === 'number')
    return [String(node)];
  if (Array.isArray(node)) return node.flatMap(collectText);
  return collectText(node.children);
};

const renderOneHour = (): ReactTestRenderer => {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = renderer.create(<StockDetailScreen />);
  });
  act(() => {
    tree.root.findByProps({accessibilityLabel: '1 hora'}).props.onPress();
  });
  return tree;
};

beforeEach(() => {
  mockCloses = [];
  mockChartLoading = false;
  mockChartFailed = false;
});

describe('StockDetailScreen intraday chart states', () => {
  it('does not mask a default one-day failure with fallback chart data', () => {
    mockChartFailed = true;
    let tree!: ReactTestRenderer;
    act(() => {
      tree = renderer.create(<StockDetailScreen />);
    });
    const text = collectText(tree.toJSON()).join(' ');
    expect(tree.root.findAllByType('Polyline' as any)).toHaveLength(0);
    expect(text).toContain('No se pudo cargar el gráfico');
  });

  it('shows loading copy while the one-hour candles are loading', () => {
    mockChartLoading = true;
    const tree = renderOneHour();
    const text = collectText(tree.toJSON()).join(' ');
    expect(
      tree.root.findByProps({accessibilityLiveRegion: 'polite'}).props
        .accessibilityRole,
    ).toBe('alert');
    expect(text).toContain('Cargando gráfico…');
    expect(text).not.toContain('Aún no hay suficientes datos');
  });

  it('explains when an intraday range has fewer than two candles', () => {
    mockCloses = [180];
    const text = collectText(renderOneHour().toJSON()).join(' ');
    expect(text).toContain('Aún no hay suficientes datos');
    expect(text).not.toContain('Cargando gráfico…');
  });

  it('reports an upstream failure instead of calling it sparse data', () => {
    mockChartFailed = true;
    const text = collectText(renderOneHour().toJSON()).join(' ');
    expect(text).toContain('No se pudo cargar el gráfico');
    expect(text).not.toContain('Aún no hay suficientes datos');
  });

  it('renders the chart once an intraday range has two candles', () => {
    mockCloses = [179, 180];
    const tree = renderOneHour();
    const text = collectText(tree.toJSON()).join(' ');
    expect(tree.root.findAllByType('Polyline' as any)).toHaveLength(1);
    expect(text).not.toContain('Cargando gráfico…');
    expect(text).not.toContain('Aún no hay suficientes datos');
  });
});
