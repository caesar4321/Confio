import { appVersionUrl } from '../appUpdate';

jest.mock('../../config/env', () => ({ API_URL: 'https://confio.lat/graphql/' }));
jest.mock('react-native-device-info', () => ({ getVersion: () => '5.2.3', getBuildNumber: () => '168' }));

describe('appVersionUrl', () => {
  it('points beside the GraphQL endpoint on the same host', () => {
    expect(appVersionUrl('https://confio.lat/graphql/')).toBe('https://confio.lat/api/app-version/');
    expect(appVersionUrl('http://10.0.2.2:8000/graphql')).toBe('http://10.0.2.2:8000/api/app-version/');
  });
});
