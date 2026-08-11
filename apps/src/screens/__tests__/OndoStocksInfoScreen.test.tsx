import React from 'react';
import renderer, {ReactTestRenderer, act} from 'react-test-renderer';

const STATS = 'GET_STATS_SUMMARY';
const FEE = 'OndoStocksInfoFee';

let mockStatsPayload: any;
let mockFeePayload: any;
let mockMarketAssets: any[];

// gql is mocked to return the query body so useQuery can tell the two apart.
jest.mock('@apollo/client', () => ({
  gql: (strings: TemplateStringsArray) => strings.join(''),
  useQuery: (query: any) => {
    if (query === STATS) return {data: mockStatsPayload, loading: false};
    if (typeof query === 'string' && query.includes(FEE)) {
      return {data: mockFeePayload, loading: false};
    }
    return {data: undefined, loading: false};
  },
}));
jest.mock('../../apollo/queries', () => ({GET_STATS_SUMMARY: 'GET_STATS_SUMMARY'}));
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
  mockStatsPayload = {statsSummary: {ondoStocksTvl: 12345}};
  mockFeePayload = {cusdPlusConvertParams: {gmTradeFeeBps: 30}};
  mockMarketAssets = new Array(438).fill({});
});

describe('OndoStocksInfoScreen headline figures', () => {
  it('repeats the Home Acciones stat so the tap does not dead-end', () => {
    expect(render()).toContain('12.345');
  });

  it('hides the TVL pill entirely when the aggregation is unknown', () => {
    mockStatsPayload = {statsSummary: {ondoStocksTvl: null}};
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
    mockFeePayload = {cusdPlusConvertParams: {gmTradeFeeBps: 45}};
    expect(render()).toContain('0,45%');
  });
});
