import React from 'react';
import renderer, {ReactTestRenderer, act} from 'react-test-renderer';

const FEE = 'OndoStocksInfoFee';

let mockFeePayload: any;
let mockMarketAssets: any[];
const mockUseQuery = jest.fn((query: any, _options: any) => {
  if (typeof query === 'string' && query.includes(FEE)) {
    return {data: mockFeePayload, loading: false};
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
jest.mock('../../hooks/useSavingsPortfolio', () => ({
  useSavingsPortfolio: () => ({stocks: {enabled: true, buyEnabled: true}}),
}));
jest.mock('../../hooks/useGmMarket', () => ({
  useGmMarket: () => ({stocks: mockMarketAssets}),
}));
jest.mock('../../hooks/useCurrency', () => ({
  useCurrency: () => ({currency: {thousandsSeparator: '.', decimalSeparator: ','}}),
}));
jest.mock('../../components/TickerLogo', () => ({TickerLogo: 'TickerLogo'}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');

import {OndoStocksInfoScreen} from '../OndoStocksInfoScreen';

// Walk the rendered JSON collecting leaf strings. Reading props.children off
// live instances instead pulls in React elements, which are circular.
const collectText = (node: any): string[] => {
  if (node == null || node === false) return [];
  if (typeof node === 'string' || typeof node === 'number') return [String(node)];
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
  mockFeePayload = {
    cusdPlusConvertParams: {gmTradeFeeBps: 30},
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
    expect(text).toContain('3 carteras con posiciones');
    expect(text).toContain('7 posiciones');
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
    // Neither a fake zero nor a dangling em dash.
    expect(text).not.toContain('en acciones');
    expect(text).not.toContain('—');
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

  it('states a fee exists without a number when the server has not answered', () => {
    mockFeePayload = undefined;
    const text = render();
    expect(text).toContain('una comisión');
    expect(text).not.toContain('%');
  });

  it('tracks a changed fee instead of the old hardcoded rate', () => {
    mockFeePayload.cusdPlusConvertParams.gmTradeFeeBps = 45;
    expect(render()).toContain('0,45%');
  });
});
