import React from 'react';
import renderer, {act, ReactTestRenderer} from 'react-test-renderer';

let mockResult: any;
let mockOptions: any;
const mockRefetch = jest.fn();

jest.mock('@apollo/client', () => ({
  gql: (s: TemplateStringsArray) => s,
  useQuery: (_q: any, options: any) => { mockOptions = options; return mockResult; },
}));
jest.mock('@react-navigation/native', () => ({useNavigation: () => ({goBack: jest.fn()})}));
jest.mock('../../navigation/Header', () => ({Header: 'Header'}));
jest.mock('../../components/common/BrandFieldBackground', () => ({BrandFieldBackground: 'BrandFieldBackground'}));
jest.mock('../../components/EmptyState', () => ({EmptyState: 'EmptyState'}));
jest.mock('react-native-vector-icons/Feather', () => 'Icon');
jest.mock('../../hooks/useCurrency', () => ({
  useCurrency: () => ({currency: {thousandsSeparator: '.', decimalSeparator: ','}}),
}));

import {FundFlowScreen, withdrawalTimeLabel} from '../FundFlowScreen';

const flow = {
  totalUsd: 141708.82,
  depositedUsd: 78887.26,
  withdrawnUsd: 62821.57,
  depositCount: 216,
  withdrawalCount: 35,
  operationCount: 251,
  medianWithdrawalMinutes: 9.5,
  withdrawalTimingSamples: 29,
  since: '2026-03-22T07:30:28+00:00',
  countries: [
    {countryIso: 'BR', countryName: 'Brasil', operationCount: 168},
    {countryIso: 'AR', countryName: 'Argentina', operationCount: 64},
  ],
};

const render = (): ReactTestRenderer => {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = renderer.create(<FundFlowScreen />);
  });
  return tree;
};

const text = (tree: ReactTestRenderer) =>
  tree.root.findAllByType('Text' as any)
    .map(t => [].concat(t.props.children).map(c => (typeof c === 'string' || typeof c === 'number' ? c : '')).join(''))
    .join(' | ');

beforeEach(() => {
  mockResult = {data: {fundFlowStats: flow}, loading: false, error: undefined, refetch: mockRefetch};
});

describe('withdrawalTimeLabel', () => {
  it('names the next whole unit above the median, so "menos de" is strictly true', () => {
    expect(withdrawalTimeLabel(9.5)).toBe('menos de 10 minutos');
    expect(withdrawalTimeLabel(10)).toBe('menos de 11 minutos');
    expect(withdrawalTimeLabel(0.4)).toBe('menos de 1 minuto');
    expect(withdrawalTimeLabel(58.9)).toBe('menos de 59 minutos');
    expect(withdrawalTimeLabel(59)).toBe('menos de 1 hora');
    expect(withdrawalTimeLabel(60)).toBe('menos de 2 horas');
    expect(withdrawalTimeLabel(61)).toBe('menos de 2 horas');
  });
});

describe('FundFlowScreen', () => {
  it('shows the split, the median withdrawal time and countries by operations', () => {
    const t = text(render());
    expect(t).toContain('141.709');
    expect(t).toContain('251 depósitos y retiros · desde marzo de 2026');
    expect(t).toContain('78.887 USD');
    expect(t).toContain('62.822 USD');
    expect(t).toContain('La mitad de los retiros llegó en menos de 10 minutos');
    expect(t).toContain('Mediana de 29 retiros');
    expect(t).toContain('Brasil');
    expect(t).toContain('168');
    // Countries are counts, never dollars.
    expect(t).not.toMatch(/Brasil[^|]*USD/);
  });

  it('reads its own snapshot, not the cache the Home tile writes', () => {
    render();
    expect(mockOptions.fetchPolicy).toBe('no-cache');
  });

  it('treats a partial snapshot as unavailable, never as zeros', () => {
    mockResult.data.fundFlowStats = {totalUsd: 141708.82, operationCount: 251};
    const tree = render();
    expect(text(tree)).not.toContain('0 USD');
    expect(tree.root.findAllByType('EmptyState' as any)).toHaveLength(1);
  });

  it('hides the timing claim when the server has too few withdrawals', () => {
    mockResult.data.fundFlowStats = {...flow, medianWithdrawalMinutes: null};
    expect(text(render())).not.toContain('La mitad de los retiros');
  });

  it('offers a retry instead of zeros when the data is unavailable', () => {
    mockResult = {data: undefined, loading: false, error: new Error('down'), refetch: mockRefetch};
    const tree = render();
    expect(text(tree)).not.toContain('0 USD');
    const empty = tree.root.findByType('EmptyState' as any);
    empty.props.onAction();
    expect(mockRefetch).toHaveBeenCalled();
  });
});
