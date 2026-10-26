import React from 'react';
import renderer, { act } from 'react-test-renderer';

let mockCaps: any = null;
let mockPerpsCaps: any = null;
let mockHoldings: any[] | null = [];
const mockNavigate = jest.fn();
const mockAssets = [
  { symbol: 'BTCB', ticker: 'BTC', name: 'Bitcoin', category: 'crypto', priceUsd: 100000, dayChangePct: 1.2 },
  { symbol: 'XAUT', ticker: 'XAUT', name: 'Tether Gold', category: 'metal', priceUsd: 4000, dayChangePct: -0.4 },
];

jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({ navigate: mockNavigate }),
  useIsFocused: () => true,
  useFocusEffect: jest.fn(),
}));
jest.mock('@apollo/client', () => ({ useQuery: () => ({ data: undefined, loading: false, refetch: () => Promise.resolve() }) }));
jest.mock('../../apollo/queries', () => ({}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../components/common/BrandFieldBackground', () => ({ BrandFieldBackground: 'BrandFieldBackground' }));
jest.mock('../../components/svg/StocksMark', () => 'StocksMark');
jest.mock('../../components/svg/FuturesMark', () => 'FuturesMark');
jest.mock('../../hooks/usePerps', () => ({
  usePerpsCapabilities: () => ({ capabilities: mockPerpsCaps, refetch: () => Promise.resolve() }),
  usePerpsMarkets: () => ({ markets: [] }),
  usePerpsPositions: () => ({ positions: [] }),
}));
jest.mock('../../components/CryptoAssetMark', () => ({ CryptoAssetMark: 'CryptoAssetMark' }));
jest.mock('../../assets/png/Ondo.png', () => 1);
jest.mock('../../assets/png/CONFIO.png', () => 1);
jest.mock('../../contexts/AccountContext', () => ({ useAccount: () => ({ activeAccount: { isEmployee: false } }) }));
jest.mock('../../utils/numberFormatting', () => ({ useNumberFormat: () => ({ formatNumber: (v: number) => String(v) }) }));
jest.mock('../../hooks/useSavingsPortfolio', () => ({
  useSavingsPortfolio: () => ({ stocks: { enabled: true, positions: [], totalUsd: 0, earnedTodayUsd: 0, eligibilityKnown: true } }),
}));
jest.mock('../../hooks/useGmMarket', () => ({
  useGmMarket: () => ({
    stocks: ['SPY', 'QQQ', 'GLD', 'SLV'].map((ticker) => ({ ticker, name: `${ticker} fund`, dayChangePct: 1 })),
  }),
}));
jest.mock('../../hooks/useCrypto', () => ({
  useCryptoCapabilities: () => ({ capabilities: mockCaps, refetch: () => Promise.resolve() }),
  useCryptoMarket: (enabled: boolean) => ({ assets: enabled ? mockAssets : [] }),
  useCryptoHoldings: () => ({ holdings: mockHoldings }),
}));

import { InvestScreen } from '../InvestScreen';

const strings = (tree: renderer.ReactTestRenderer) =>
  tree.root.findAll(() => true).flatMap((n) => n.children.filter((c): c is string => typeof c === 'string'));

const render = async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<InvestScreen />); });
  return tree;
};

beforeEach(() => { mockPerpsCaps = null; mockCaps = { enabled: true }; mockHoldings = []; mockNavigate.mockReset(); });

it('orders the cards stocks → Oro y Bitcoin → $CONFIO, one row per listed asset', async () => {
  const tree = await render();
  const s = strings(tree);
  const stocks = s.indexOf('Acciones de EE.UU.');
  const crypto = s.indexOf('Oro y Bitcoin');
  const confio = s.findIndex((t) => t.startsWith('$CONFIO'));
  expect(stocks).toBeGreaterThanOrEqual(0);
  expect(crypto).toBeGreaterThan(stocks);
  expect(confio).toBeGreaterThan(crypto);
  expect(s).toContain('Para guardar valor, 24/7');
  expect(s).toContain('Bitcoin');
  expect(s).toContain('Tether Gold');
  const row = tree.root.find((n) => n.props?.accessibilityLabel === 'Tether Gold' && typeof n.props.onPress === 'function');
  await act(async () => { row.props.onPress(); });
  expect(mockNavigate).toHaveBeenCalledWith('CryptoDetail', { symbol: 'XAUT' });
});

it('keeps gold out of the stocks ticker strip', async () => {
  const s = strings(await render());
  expect(s).toContain('SPY fund');
  expect(s).not.toContain('GLD fund');
  expect(s).not.toContain('SLV fund');
});

it('hides the card unless cryptoCapabilities.enabled', async () => {
  mockCaps = { enabled: false };
  expect(strings(await render())).not.toContain('Oro y Bitcoin');
  mockCaps = null; // older server: the query failed
  expect(strings(await render())).not.toContain('Oro y Bitcoin');
});

it('a country-blocked holder still sees what they hold, sell-only, and can open it (Codex P1)', async () => {
  mockCaps = { enabled: false };
  mockHoldings = [{
    symbol: 'ETH', ticker: 'ETH', name: 'Ethereum', address: '0xeth', custody: 'binance_peg', listed: false,
    category: 'crypto', units: '1000', decimals: 18, valueUsd: 12.5, dayChangePct: null,
  }];
  const tree = await render();
  const s = strings(tree);
  expect(s).toContain('Oro y Bitcoin');
  expect(s).toContain('Ethereum');
  expect(s).toContain('ETH · Solo venta');
  expect(s).not.toContain('Bitcoin'); // no catalog rows while blocked
  const row = tree.root.find((n) => n.props?.accessibilityLabel === 'Ethereum' && typeof n.props.onPress === 'function');
  await act(async () => { row.props.onPress(); });
  expect(mockNavigate).toHaveBeenCalledWith('CryptoDetail', { symbol: 'ETH' });
});

it('a delisted holding shows next to the listed rows when discovery is on', async () => {
  mockHoldings = [{
    symbol: 'ETH', ticker: 'ETH', name: 'Ethereum', address: '0xeth', custody: 'binance_peg', listed: false,
    category: 'crypto', units: '1000', decimals: 18, valueUsd: 12.5, dayChangePct: null,
  }];
  const s = strings(await render());
  expect(s).toContain('Bitcoin');
  expect(s).toContain('Tether Gold');
  expect(s).toContain('ETH · Solo venta');
});

it('places Futuros below Oro y Bitcoin and above $CONFIO, only when enabled', async () => {
  expect(strings(await render())).not.toContain('Futuros');
  mockPerpsCaps = { enabled: true };
  const tree = await render();
  const s = strings(tree);
  const crypto = s.indexOf('Oro y Bitcoin');
  const futures = s.indexOf('Futuros');
  const confio = s.findIndex((t) => t.startsWith('$CONFIO'));
  expect(futures).toBeGreaterThan(crypto);
  expect(confio).toBeGreaterThan(futures);
  await act(async () => { tree.root.find((n) => n.props?.testID === 'invest-futures-card' && typeof n.props.onPress === 'function').props.onPress(); });
  expect(mockNavigate).toHaveBeenCalledWith('FuturesMarkets');
});
