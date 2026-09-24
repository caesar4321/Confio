import React from 'react';
import {act, create, ReactTestRenderer} from 'react-test-renderer';
import {CountryProvider, useCountry} from '../CountryContext';
import {useCurrency} from '../../hooks/useCurrency';
import {useExchangeRate} from '../../hooks/useExchangeRate';
import {getCountryByIso} from '../../utils/countries';

let mockQueryResult: any;
let mockProfile: any;
let mockAuthenticated: boolean;
let mockRateCurrency: string;
let mockRateValue: unknown;
jest.mock('@apollo/client', () => ({
  useQuery: (_query: unknown, options: any) => {
    if (options?.variables?.sourceCurrency) {
      mockRateCurrency = options.variables.sourceCurrency;
      return {data: {exchangeRateWithFallback: mockRateValue}, loading: false};
    }
    return mockQueryResult;
  },
}));
jest.mock('../../apollo/queries', () => ({GET_ME: 'me'}));
jest.mock('../AuthContext', () => ({useAuth: () => ({userProfile: mockProfile, isAuthenticated: mockAuthenticated})}));

describe('local balance currency', () => {
  let tree: ReactTestRenderer;
  let state: ReturnType<typeof useCountry>;
  let currency: string;
  let rate: number | null;
  const Probe = () => {
    state = useCountry();
    currency = useCurrency().currencyCode;
    rate = useExchangeRate(currency, 'USD').rate;
    return null;
  };
  const render = async () => {
    await act(async () => {
      const element = <CountryProvider><Probe /></CountryProvider>;
      if (tree) tree.update(element);
      else tree = create(element);
    });
  };

  beforeEach(() => {
    mockQueryResult = {data: undefined, loading: false};
    mockProfile = {id: 'current'};
    mockAuthenticated = true;
    mockRateValue = '18';
  });
  afterEach(async () => {
    await act(async () => tree?.unmount());
    tree = undefined as any;
  });

  it('uses the Mexican auth profile when the separate profile query has no data', async () => {
    mockProfile = {phoneCountry: 'MX'};
    await render();
    expect(currency!).toBe('MXN');
    expect(mockRateCurrency).toBe('MXN');
  });

  it.each([undefined, '', 'invalid'])('does not invent an Argentine country for %s', async phoneCountry => {
    mockQueryResult = {data: {me: {id: 'current', phoneCountry}}, loading: false};
    await render();
    expect(state!.userCountry).toBeNull();
    expect(currency!).toBe('USD');
    expect(mockRateCurrency).toBe('USD');
  });

  it('updates to MXN when the country arrives after loading', async () => {
    mockQueryResult = {loading: true};
    await render();
    expect(currency!).toBe('USD');
    mockQueryResult = {data: {me: {id: 'current', phoneCountry: 'MX'}}, loading: false};
    await render();
    expect(currency!).toBe('MXN');
    expect(mockRateCurrency).toBe('MXN');
  });

  it('keeps picker selection separate from the wallet country', async () => {
    await render();
    await act(async () => state!.setSelectedCountry(getCountryByIso('MX')!));
    mockQueryResult = {data: {me: {id: 'current', phoneCountry: 'AR'}}, loading: false};
    await render();
    expect(state!.selectedCountry?.[2]).toBe('MX');
    expect(currency!).toBe('ARS');
    expect(mockRateCurrency).toBe('ARS');
  });

  it('does not change a Mexican wallet when another form selects Argentina', async () => {
    mockProfile = {id: 'luis', phoneCountry: 'MX'};
    await render();
    await act(async () => state!.setSelectedCountry(getCountryByIso('AR')!));
    expect(currency!).toBe('MXN');
    expect(mockRateCurrency).toBe('MXN');
  });

  it('uses the current profile over a stale query and resets selections on user change', async () => {
    mockProfile = {id: 'old', phoneCountry: 'AR'};
    mockQueryResult = {data: {me: mockProfile}, loading: false};
    await render();
    await act(async () => state!.setSelectedCountry(getCountryByIso('VE')!));
    mockProfile = {id: 'new', phoneCountry: 'MX'};
    await render();
    expect(currency!).toBe('MXN');
    expect(mockRateCurrency).toBe('MXN');
    expect(state!.selectedCountry?.[2]).toBe('MX');
    mockProfile = {id: 'third', phoneCountry: ''};
    await render();
    expect(currency!).toBe('USD');
    expect(state!.selectedCountry).toBeNull();
  });

  it('normalizes a profile ISO code', async () => {
    mockProfile = {phoneCountry: ' mx '};
    await render();
    expect(currency!).toBe('MXN');
  });

  it('clears country and selections at logout even if the profile query stays cached', async () => {
    mockProfile = {id: 'old', phoneCountry: 'MX'};
    mockQueryResult = {data: {me: mockProfile}, loading: false};
    await render();
    await act(async () => state!.setSelectedCountry(getCountryByIso('VE')!));
    mockProfile = null;
    mockAuthenticated = false;
    await render();
    expect(currency!).toBe('USD');
    expect(state!.selectedCountry).toBeNull();
    expect(state!.userCountry).toBeNull();
  });

  it('requests the displayed EUR currency for Estonia', async () => {
    mockProfile = {phoneCountry: 'EE'};
    await render();
    expect(currency!).toBe('EUR');
    expect(mockRateCurrency).toBe('EUR');
  });

  it('ignores cached country until the authenticated profile identifies its owner', async () => {
    mockProfile = null;
    mockQueryResult = {data: {me: {id: 'old', phoneCountry: 'AR'}}, loading: false};
    await render();
    expect(currency!).toBe('USD');
    expect(state!.selectedCountry).toBeNull();
  });

  it('continues to show ARS for an Argentine profile', async () => {
    mockQueryResult = {data: {me: {id: 'current', phoneCountry: 'AR'}}, loading: false};
    await render();
    expect(currency!).toBe('ARS');
    expect(mockRateCurrency).toBe('ARS');
  });

  it.each([null, undefined, '', '0', '-1', 'NaN', 'Infinity', '18junk'])('rejects an unavailable or invalid rate: %s', async value => {
    mockProfile = {phoneCountry: 'MX'};
    mockRateValue = value;
    await render();
    expect(rate!).toBeNull();
  });

  it.each(['1', '18.25'])('accepts a positive rate including parity: %s', async value => {
    mockProfile = {phoneCountry: 'MX'};
    mockRateValue = value;
    await render();
    expect(rate!).toBe(Number(value));
  });
});
