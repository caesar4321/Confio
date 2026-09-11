jest.mock('react-native-keychain', () => ({
  getGenericPassword: jest.fn(),
  setGenericPassword: jest.fn(),
  resetGenericPassword: jest.fn(),
  ACCESSIBLE: { AFTER_FIRST_UNLOCK: 'after-first-unlock' },
}));
jest.mock('../../config/env', () => ({ getApiUrl: () => 'https://example.test/graphql' }));
jest.mock('../../utils/accountManager', () => ({}));
jest.mock('../../services/appCheckService', () => ({
  __esModule: true,
  default: { getTokenForHeader: async () => null, getLastErrorForDebug: () => null },
}));
jest.mock('react-native-device-info', () => ({ getBuildNumber: () => '1' }));
jest.mock('../../services/emergencyExit/banSignal', () => ({
  successProvesUnbanned: () => false,
  looksLikeBanResponse: () => true,
  markBanSignal: jest.fn(),
}));
jest.mock('../../navigation/RootNavigation', () => ({ routeToBlockedAccount: jest.fn() }));
jest.mock('../../services/emergencyExit/store', () => ({ emergencyStore: {} }));
jest.mock('jwt-decode', () => ({
  jwtDecode: () => ({ user_id: 1, type: 'access', exp: Date.now() / 1000 + 60 }),
}));

import { execute, gql } from '@apollo/client';
import * as Keychain from 'react-native-keychain';
import { apolloClient } from '../client';

const query = gql`query SessionProbe { sessionProbe }`;
const mockFetch = jest.fn();
let storedTokens: { accessToken: string; refreshToken: string } | null;
const originalFetch = globalThis.fetch;
const response = (body: unknown, status = 200) => ({
  status,
  ok: status >= 200 && status < 300,
  headers: { get: () => 'application/json' },
  json: async () => body,
  text: async () => JSON.stringify(body),
});

describe('session refresh through the Apollo client', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
    globalThis.fetch = mockFetch;
    storedTokens = { accessToken: 'old-access', refreshToken: 'saved-refresh' };
    (Keychain.getGenericPassword as jest.Mock).mockImplementation(async () => storedTokens && ({
      username: 'auth_tokens', password: JSON.stringify(storedTokens),
    }));
    (Keychain.setGenericPassword as jest.Mock).mockImplementation(async (_username, password) => {
      storedTokens = JSON.parse(password);
      return true;
    });
    (Keychain.resetGenericPassword as jest.Mock).mockImplementation(async () => {
      storedTokens = null;
      return true;
    });
    jest.spyOn(console, 'error').mockImplementation(() => {});
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    jest.restoreAllMocks();
  });

  it('preserves the session on a network failure and retries refresh on the next request', async () => {
    mockFetch
      .mockRejectedValueOnce(new TypeError('Network request failed'))
      .mockResolvedValueOnce(response({ data: { sessionProbe: 'first' } }))
      .mockResolvedValueOnce(response({ data: { refreshToken: { token: 'new-access' } } }))
      .mockResolvedValueOnce(response({ data: { sessionProbe: 'second' } }));

    await apolloClient.query({ query, fetchPolicy: 'no-cache' });
    expect(Keychain.resetGenericPassword).not.toHaveBeenCalled();
    expect(mockFetch.mock.calls[1][1].headers.authorization).toBe('JWT old-access');

    await apolloClient.query({ query, fetchPolicy: 'no-cache' });
    expect(mockFetch).toHaveBeenCalledTimes(4);
    expect(Keychain.setGenericPassword).toHaveBeenCalledWith(
      'auth_tokens',
      JSON.stringify({ accessToken: 'new-access', refreshToken: 'saved-refresh' }),
      expect.any(Object),
    );
    expect(mockFetch.mock.calls[3][1].headers.authorization).toBe('JWT new-access');
  });

  it.each([500, 401, 403])('preserves credentials on HTTP %i during refresh', async status => {
    mockFetch
      .mockResolvedValueOnce(response({ errors: [{ message: 'Temporary failure' }] }, status))
      .mockResolvedValueOnce(response({ data: { sessionProbe: 'ok' } }));
    await apolloClient.query({ query, fetchPolicy: 'no-cache' });
    expect(Keychain.resetGenericPassword).not.toHaveBeenCalled();
  });

  it('preserves credentials when the refresh response is not JSON', async () => {
    mockFetch
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => { throw new SyntaxError('Invalid JSON'); } })
      .mockResolvedValueOnce(response({ data: { sessionProbe: 'ok' } }));
    await apolloClient.query({ query, fetchPolicy: 'no-cache' });
    expect(Keychain.resetGenericPassword).not.toHaveBeenCalled();
  });

  it.each(['Signature has expired', 'Token version mismatch', 'Invalid refresh token'])(
    'clears a session explicitly rejected by the refresh resolver: %s', async message => {
      mockFetch
        .mockResolvedValueOnce(response({ errors: [{ message }] }))
        .mockResolvedValueOnce(response({ data: { sessionProbe: null } }));
      await expect(apolloClient.query({ query, fetchPolicy: 'no-cache' })).rejects.toThrow('Invalid refresh token');
      expect(Keychain.resetGenericPassword).toHaveBeenCalledTimes(1);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    },
  );

  it('replays a server-expired request with the refreshed Authorization header', async () => {
    mockFetch
      .mockResolvedValueOnce(response({ errors: [{ message: 'Signature has expired' }] }))
      .mockResolvedValueOnce(response({ data: { refreshToken: { token: 'new-access' } } }))
      .mockResolvedValueOnce(response({ data: { sessionProbe: 'ok' } }));
    // This operation deliberately bypasses proactive refresh in the real client.
    await apolloClient.query({ query: gql`query GetUserAccounts { sessionProbe }`, fetchPolicy: 'no-cache' });
    expect(mockFetch.mock.calls[0][1].headers.authorization).toBe('JWT old-access');
    expect(mockFetch.mock.calls[2][1].headers.authorization).toBe('JWT new-access');
    expect(Keychain.resetGenericPassword).not.toHaveBeenCalled();
  });

  it('never replays an account-pinned request with another session', async () => {
    mockFetch.mockResolvedValueOnce(response({ errors: [{ message: 'Signature has expired' }] }));
    await expect(apolloClient.query({
      query, fetchPolicy: 'no-cache', context: { pinnedAuthToken: 'verified-account-token' },
    })).rejects.toThrow('Signature has expired');
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(mockFetch.mock.calls[0][1].headers.authorization).toBe('JWT verified-account-token');
    expect(Keychain.setGenericPassword).not.toHaveBeenCalled();
  });

  it.each(['sign-out', 'account-switch'])('does not persist an old refresh after %s', async change => {
    let release!: (value: unknown) => void;
    let started!: () => void;
    const refreshing = new Promise<void>(resolve => { started = resolve; });
    mockFetch.mockImplementationOnce(() => {
      started();
      return new Promise(resolve => { release = resolve; });
    }).mockResolvedValue(response({ data: { sessionProbe: 'wrong-session' } }));
    const pending = apolloClient.query({ query, fetchPolicy: 'no-cache' });
    await refreshing;
    // Account switches preserve the refresh token and replace only access.
    storedTokens = change === 'sign-out' ? null : { accessToken: 'business-access', refreshToken: 'saved-refresh' };
    release(response({ data: { refreshToken: { token: 'stale-refreshed-access' } } }));
    await expect(pending).rejects.toThrow('Session changed');
    expect(Keychain.setGenericPassword).not.toHaveBeenCalled();
    expect(Keychain.resetGenericPassword).not.toHaveBeenCalled();
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it('does not erase replacement credentials when an old refresh is rejected', async () => {
    mockFetch.mockImplementationOnce(async () => {
      storedTokens = { accessToken: 'replacement-access', refreshToken: 'replacement-refresh' };
      return response({ errors: [{ message: 'Token version mismatch' }] });
    });
    await expect(apolloClient.query({ query, fetchPolicy: 'no-cache' })).rejects.toThrow('Session changed');
    expect(Keychain.resetGenericPassword).not.toHaveBeenCalled();
    expect(storedTokens?.accessToken).toBe('replacement-access');
  });

  it('does not replay an expired request after switching accounts before its response', async () => {
    mockFetch.mockImplementationOnce(async () => {
      storedTokens = { accessToken: 'business-access', refreshToken: 'saved-refresh' };
      return response({ errors: [{ message: 'Signature has expired' }] });
    });
    await expect(apolloClient.query({ query, fetchPolicy: 'no-cache', context: { skipProactiveRefresh: true } }))
      .rejects.toThrow('Session changed');
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(Keychain.resetGenericPassword).not.toHaveBeenCalled();
  });

  it('settles the request when clearing a rejected session fails', async () => {
    (Keychain.resetGenericPassword as jest.Mock).mockRejectedValueOnce(new Error('Keychain write failed'));
    mockFetch
      .mockResolvedValueOnce(response({ errors: [{ message: 'Signature has expired' }] }))
      .mockResolvedValueOnce(response({ errors: [{ message: 'Invalid refresh token' }] }));
    await expect(apolloClient.query({ query: gql`query GetUserAccounts { sessionProbe }`, fetchPolicy: 'no-cache' }))
      .rejects.toThrow('Invalid refresh token');
  });

  it('preserves the business account context on refresh', async () => {
    jest.spyOn(require('jwt-decode'), 'jwtDecode').mockReturnValue({
      user_id: 1, type: 'access', exp: Date.now() / 1000 + 60,
      account_type: 'business', account_index: 2, business_id: 'business-7',
    });
    mockFetch
      .mockResolvedValueOnce(response({ data: { refreshToken: { token: 'new-access' } } }))
      .mockResolvedValueOnce(response({ data: { sessionProbe: 'ok' } }));
    await apolloClient.query({ query, fetchPolicy: 'no-cache' });
    expect(JSON.parse(mockFetch.mock.calls[0][1].body).variables).toEqual({
      refreshToken: 'saved-refresh', accountType: 'business', accountIndex: 2, businessId: 'business-7',
    });
  });

  it('does not replay a cancelled request when refresh completes later', async () => {
    let release!: (value: unknown) => void;
    let started!: () => void;
    const refreshing = new Promise<void>(resolve => { started = resolve; });
    mockFetch
      .mockResolvedValueOnce(response({ errors: [{ message: 'Signature has expired' }] }))
      .mockImplementationOnce(() => {
        started();
        return new Promise(resolve => { release = resolve; });
      })
      .mockResolvedValue(response({ data: { sessionProbe: 'unwanted-replay' } }));
    const subscription = execute(apolloClient.link, {
      query, context: { skipProactiveRefresh: true },
    }).subscribe({ error: () => {} });
    await refreshing;
    subscription.unsubscribe();
    release(response({ data: { refreshToken: { token: 'new-access' } } }));
    // Drain the async refresh / Keychain / replay chain.
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });
});
