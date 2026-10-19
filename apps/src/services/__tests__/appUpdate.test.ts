import { AppUpdatePolicy, appUpdateView, appVersionUrl, fetchAppUpdatePolicy } from '../appUpdate';

jest.mock('../../config/env', () => ({ API_URL: 'https://confio.lat/graphql/' }));
jest.mock('react-native-device-info', () => ({ getVersion: () => '5.2.3', getBuildNumber: () => '168' }));

describe('appVersionUrl', () => {
  it('points beside the GraphQL endpoint on the same host', () => {
    expect(appVersionUrl('https://confio.lat/graphql/')).toBe('https://confio.lat/api/app-version/');
    expect(appVersionUrl('http://10.0.2.2:8000/graphql')).toBe('http://10.0.2.2:8000/api/app-version/');
  });
});

const policy = (status: AppUpdatePolicy['status'], latestVersion = '5.2.6'): AppUpdatePolicy =>
  ({ status, latestVersion, message: '' });

describe('appUpdateView', () => {
  it('blocks on a required update, even one already put off', () => {
    expect(appUpdateView(policy('update_required'), null, false)).toBe('blocked');
    expect(appUpdateView(policy('update_required'), '5.2.6', false)).toBe('blocked');
  });

  it('stands down once Salida de emergencia is open', () => {
    expect(appUpdateView(policy('update_required'), null, true)).toBeNull();
    expect(appUpdateView(policy('update_available'), null, true)).toBeNull();
  });

  it('offers an available update until that version is put off', () => {
    expect(appUpdateView(policy('update_available'), null, false)).toBe('prompt');
    expect(appUpdateView(policy('update_available'), '5.2.6', false)).toBeNull();
    expect(appUpdateView(policy('update_available', '5.2.7'), '5.2.6', false)).toBe('prompt');
  });

  it('shows nothing without a policy or when current', () => {
    expect(appUpdateView(null, null, false)).toBeNull();
    expect(appUpdateView(policy('current'), null, false)).toBeNull();
  });
});

describe('fetchAppUpdatePolicy', () => {
  const respond = (body: unknown, ok = true) => {
    (globalThis as any).fetch = jest.fn().mockResolvedValue({ ok, json: async () => body });
  };

  it('reads a required update', async () => {
    respond({ status: 'update_required', latestVersion: '5.2.6', minimumVersion: '5.2.6', message: '' });
    expect(await fetchAppUpdatePolicy()).toEqual(policy('update_required'));
  });

  it('fails open: errors and unknown answers never block', async () => {
    (globalThis as any).fetch = jest.fn().mockRejectedValue(new Error('offline'));
    expect(await fetchAppUpdatePolicy()).toBeNull();
    respond({ status: 'update_required' }, false);
    expect(await fetchAppUpdatePolicy()).toBeNull();
    respond({ status: 'something_new' });
    expect(await fetchAppUpdatePolicy()).toBeNull();
    respond('<html>');
    expect(await fetchAppUpdatePolicy()).toBeNull();
  });
});
