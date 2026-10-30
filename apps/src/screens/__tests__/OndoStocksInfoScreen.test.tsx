import React from 'react';
import { setNumberLocaleCountry } from '../../utils/numberLocale';

// Figures follow the user's country (one format app-wide); these tests read
// a Venezuelan user's screen: 1.234,56.
beforeAll(() => setNumberLocaleCountry('VE'));
afterAll(() => setNumberLocaleCountry(null));
import renderer, {ReactTestRenderer, act} from 'react-test-renderer';
import {Linking} from 'react-native';

const FEE = 'OndoStocksInfoFee';
const ADDRESS = 'OndoStocksWalletAddress';

let mockFeePayload: any;
let mockWalletPayload: any;
let mockMarketAssets: any[];
let mockAuthReady: boolean;
const mockUseQuery = jest.fn((query: any, _options: any) => {
  if (typeof query === 'string' && query.includes(FEE)) {
    return {data: mockFeePayload, loading: false};
  }
  if (typeof query === 'string' && query.includes(ADDRESS)) {
    return {data: mockWalletPayload, loading: false};
  }
  return {data: undefined, loading: false};
});

// gql is mocked to return the query body so useQuery can tell the two apart.
jest.mock('@apollo/client', () => ({
  gql: (strings: TemplateStringsArray) => strings.join(''),
  useQuery: (query: any, options: any) => mockUseQuery(query, options),
}));
jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({navigate: jest.fn(), goBack: jest.fn()}),
}));
jest.mock('../../navigation/Header', () => ({Header: 'Header'}));
let mockFeePolicy: any;
jest.mock('../../hooks/useStockFeePolicy', () => ({
  useStockFeePolicy: () => mockFeePolicy,
}));
jest.mock('../../hooks/useSavingsPortfolio', () => ({
  useSavingsPortfolio: () => ({stocks: {enabled: true, buyEnabled: true}}),
}));
let mockTradedUsd: number | null = 3424.6;
jest.mock('../../hooks/useGmMarket', () => ({
  useGmMarket: () => ({stocks: mockMarketAssets}),
  useGmHomeTile: () => ({assetCount: 438, investedUsd: null, tradedUsd: mockTradedUsd, refetch: jest.fn()}),
}));
jest.mock('../../hooks/useCurrency', () => ({
  useCurrency: () => ({
    currency: {thousandsSeparator: '.', decimalSeparator: ','},
  }),
}));
jest.mock('../../contexts/AuthContext', () => ({
  useAuthReady: () => mockAuthReady,
}));
jest.mock('../../components/TickerLogo', () => ({TickerLogo: 'TickerLogo'}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');

import {OndoStocksInfoScreen} from '../OndoStocksInfoScreen';

// Walk the rendered JSON collecting leaf strings. Reading props.children off
// live instances instead pulls in React elements, which are circular.
const collectText = (node: any): string[] => {
  if (node == null || node === false) return [];
  if (typeof node === 'string' || typeof node === 'number')
    return [String(node)];
  if (Array.isArray(node)) return node.flatMap(collectText);
  return collectText(node.children);
};

const render = (): string => {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = renderer.create(<OndoStocksInfoScreen />);
  });
  return collectText(tree.toJSON()).join(' ');
};

beforeEach(() => {
  mockUseQuery.mockClear();
  mockAuthReady = true;
  mockFeePolicy = {feeBps: 30n, mode: 'router'};
  mockFeePayload = {
    cusdPlusConvertParams: {
      gmTradeFeeBps: 30,
    },
    gmCommunity: {
      valueUsd: 12345,
      holderWallets: 3,
      positions: 7,
      updatedAt: '2026-08-13T12:34:00Z',
      assets: [
        {
          symbol: 'TSLAon',
          ticker: 'TSLA',
          name: 'Tesla',
          valueUsd: 2500,
          sharePct: 20.25,
        },
      ],
    },
  };
  mockWalletPayload = {
    stockWalletAddress: '0x1111111111111111111111111111111111111111',
  };
  mockMarketAssets = new Array(438).fill({});
});

describe('OndoStocksInfoScreen headline figures', () => {
  it('repeats the Home Acciones stat so the tap does not dead-end', () => {
    expect(render()).toContain('12.345');
  });

  it('shows the same marked-to-market community holdings snapshot', () => {
    const text = render();
    const compact = text.replace(/\s+/g, '');
    expect(text).toContain('En qué invierte la comunidad');
    expect(text).toContain('TSLA');
    expect(compact).toContain('US$2.500,00');
    expect(compact).toContain('20,3%');
    expect(text).toContain('3 cuentas con acciones');
    expect(text).toContain('7 inversiones');
    expect(text).toContain('Datos al');
  });

  it('refreshes the community snapshot while the screen remains open', () => {
    render();
    expect(mockUseQuery).toHaveBeenCalledWith(
      expect.stringContaining(FEE),
      expect.objectContaining({pollInterval: 300_000}),
    );
  });

  it('hides the TVL pill entirely when the aggregation is unknown', () => {
    mockFeePayload.gmCommunity = null;
    const text = render();
    // Unknown must not be presented as a real zero-value community total.
    expect(text).not.toContain('US$0 en acciones');
  });

  it('shows the all-time volume traded, and nothing when it is unknown', () => {
    expect(render()).toMatch(/US\$\s*3\.425\s*operados/);
    mockTradedUsd = null;
    expect(render()).not.toContain('operados');
    mockTradedUsd = 3424.6;
  });

  it('renders the live asset count, not a hardcoded 400+', () => {
    const text = render();
    expect(text).toContain('438');
    expect(text).not.toContain('400+');
  });

  it('never claims a count while the market list is empty', () => {
    mockMarketAssets = [];
    const text = render();
    expect(text).not.toContain('0 acciones y ETFs');
    expect(text).toContain('Acciones y ETFs de EE.UU.');
  });

  it('renders the fee from the server value', () => {
    expect(render()).toContain('0,30%');
  });

  it('explains the unified 0.9% as the same fee as any withdrawal or deposit', () => {
    mockFeePolicy = {feeBps: 90n, mode: 'perimeter'};
    const text = render();
    expect(text).toContain('0,90%');
    expect(text).toContain('retiro o depósito');
  });

  it('states a fee exists without a number when the server has not answered', () => {
    mockFeePolicy = null;
    const text = render();
    expect(text).toContain('Confío cobra una comisión sobre cada compra y venta completada.');
    expect(text).not.toMatch(/comisión de \d|cobra un \d/);
  });

  it('tracks a changed fee instead of the old hardcoded rate', () => {
    mockFeePolicy = {feeBps: 45n, mode: 'router'};
    expect(render()).toContain('0,45%');
  });

  it('explains ownership without technical language', () => {
    const text = render();
    expect(text).toContain('Comprueba tus acciones');
    expect(text).toContain('Ver mis acciones');
    expect(text).toContain('Tus acciones digitales quedan guardadas');
    expect(text).toContain(
      'Tus acciones digitales permanecen en tu cuenta, no en Confío',
    );
    expect(text).not.toContain('tokens de Ondo Stocks');
    expect(text).not.toContain('Qué representa el token');
  });

  it('does not build public links from missing or malformed addresses', () => {
    mockWalletPayload.stockWalletAddress = 'not-an-address';
    const text = render();

    expect(text).not.toContain('Comprueba tus acciones');
    expect(text).not.toContain('Ver mis acciones');
  });

  it('hides the wallet link while the active account token is changing', () => {
    mockAuthReady = false;
    const text = render();

    expect(text).not.toContain('Ver mis acciones');
    expect(mockUseQuery).toHaveBeenCalledWith(
      expect.stringContaining(ADDRESS),
      expect.objectContaining({skip: true, fetchPolicy: 'network-only'}),
    );
  });

  it('opens the signed-in wallet assets instead of a shared address', () => {
    const openUrl = jest
      .spyOn(Linking, 'openURL')
      .mockReturnValue({catch: jest.fn()} as any);
    let tree!: ReactTestRenderer;
    act(() => {
      tree = renderer.create(<OndoStocksInfoScreen />);
    });

    act(() => {
      tree.root
        .findByProps({accessibilityLabel: 'Ver mis acciones'})
        .props.onPress();
    });

    expect(openUrl).toHaveBeenCalledWith(
      'https://bscscan.com/tokenholdings?a=0x1111111111111111111111111111111111111111',
    );
    openUrl.mockRestore();
  });

  it('no longer links to the stock router', () => {
    expect(render()).not.toContain('Ver cómo funciona Confío');
  });
});
