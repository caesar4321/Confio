import React from 'react';
import renderer, { act } from 'react-test-renderer';

jest.mock('react-native', () => ({
  Platform: { OS: 'ios' },
  PermissionsAndroid: { PERMISSIONS: {}, RESULTS: {}, check: jest.fn(), request: jest.fn() },
}));
const mockGetCurrentPosition = jest.fn();
jest.mock('@react-native-community/geolocation', () => ({
  __esModule: true,
  default: {
    setRNConfiguration: jest.fn(),
    getCurrentPosition: (...args: any[]) => mockGetCurrentPosition(...args),
    requestAuthorization: jest.fn(),
  },
}));
const mockMutate = jest.fn();
const mockQuery = jest.fn();
// A stable client, like Apollo's real one (a fresh object per render would
// re-create the hook's callbacks and re-run its mount effect forever).
const mockClient = {
  mutate: (...a: any[]) => mockMutate(...a),
  query: (...a: any[]) => mockQuery(...a),
};
jest.mock('@apollo/client', () => ({
  useApolloClient: () => mockClient,
  gql: (s: any) => s,
}));
jest.mock('../../contexts/CountryContext', () => ({ useCountry: () => ({ userCountry: ['Bolivia', '+591', 'BO'] }) }));
jest.mock('../../services/comprar', () => ({ GET_MARKETPLACE_CITIES: 'cities', LOCATE_MARKETPLACE_CITY: 'locate' }));

import { useComprarLocation } from '../useComprarLocation';

let hook: ReturnType<typeof useComprarLocation>;
const Probe = () => {
  hook = useComprarLocation();
  return null;
};

const mount = async () => {
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Probe />); });
  return tree;
};

beforeEach(() => {
  jest.useRealTimers();
  mockGetCurrentPosition.mockReset();
  mockMutate.mockReset();
  mockQuery.mockReset().mockResolvedValue({ data: { marketplaceCities: [{ city: 'La Paz', isLive: false }] } });
});

it('moves to the matched GPS city', async () => {
  mockGetCurrentPosition.mockImplementation((ok: any) => ok({ coords: { latitude: -16.5, longitude: -68.13, accuracy: 20 } }));
  mockMutate.mockResolvedValue({ data: { locateMarketplaceCity: { city: { countryCode: 'BO', city: 'La Paz' } } } });
  const tree = await mount();
  expect(hook.location).toEqual({ countryCode: 'BO', city: 'La Paz', source: 'gps' });
  let outcome;
  await act(async () => { outcome = await hook.relocate(); });
  expect(outcome).toBe('found');
  await act(async () => tree.unmount());
});

it('reports a denied permission instead of doing nothing', async () => {
  mockGetCurrentPosition.mockImplementation((_ok: any, fail: any) => fail({ code: 1 }));
  const tree = await mount();
  let outcome;
  await act(async () => { outcome = await hook.relocate(); });
  expect(outcome).toBe('denied');
  expect(mockMutate).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it('reports no_city and keeps the city being browsed', async () => {
  mockGetCurrentPosition.mockImplementation((ok: any) => ok({ coords: { latitude: -19.04, longitude: -65.26, accuracy: 30 } }));
  mockMutate.mockResolvedValue({ data: { locateMarketplaceCity: { city: null } } });
  const tree = await mount();
  await act(async () => { hook.choose('AR', 'Rosario'); });
  let outcome;
  await act(async () => { outcome = await hook.relocate(); });
  expect(outcome).toBe('no_city');
  expect(hook.location).toEqual({ countryCode: 'AR', city: 'Rosario', source: 'manual' });
  await act(async () => tree.unmount());
});

it('never hangs when the position call never answers', async () => {
  jest.useFakeTimers();
  mockGetCurrentPosition.mockImplementation(() => {});  // no callback, ever
  let tree!: renderer.ReactTestRenderer;
  await act(async () => { tree = renderer.create(<Probe />); });
  let outcome: any;
  await act(async () => {
    const p = hook.relocate().then((o) => { outcome = o; });
    jest.advanceTimersByTime(26_000);
    await p;
  });
  expect(outcome).toBe('unavailable');
  expect(hook.resolving).toBe(false);
  await act(async () => tree.unmount());
});

it('a manual pick beats a lookup still in flight', async () => {
  let answer: any;
  mockGetCurrentPosition.mockImplementation((ok: any) => { answer = ok; });
  mockMutate.mockResolvedValue({ data: { locateMarketplaceCity: { city: { countryCode: 'BO', city: 'La Paz' } } } });
  const tree = await mount();
  await act(async () => { hook.choose('AR', 'Córdoba'); });
  await act(async () => { answer({ coords: { latitude: -16.5, longitude: -68.13, accuracy: 20 } }); });
  expect(hook.location).toEqual({ countryCode: 'AR', city: 'Córdoba', source: 'manual' });
  await act(async () => tree.unmount());
});

it('a result after leaving the screen is stale (no alert)', async () => {
  let answer: any;
  mockGetCurrentPosition.mockImplementation((ok: any) => { answer = ok; });
  mockMutate.mockResolvedValue({ data: { locateMarketplaceCity: { city: null } } });
  const tree = await mount();
  let outcome: any;
  const p = hook.relocate().then((o) => { outcome = o; });
  await act(async () => tree.unmount());
  answer({ coords: { latitude: -19, longitude: -65, accuracy: 20 } });
  await p;
  expect(outcome).toBe('stale');
});

it('a throwing position call is an outcome, not a stuck spinner', async () => {
  mockGetCurrentPosition.mockImplementation(() => { throw new Error('native boom'); });
  const tree = await mount();
  expect(hook.resolving).toBe(false);
  let outcome;
  await act(async () => { outcome = await hook.relocate(); });
  expect(outcome).toBe('unavailable');
  expect(hook.resolving).toBe(false);
  await act(async () => tree.unmount());
});
