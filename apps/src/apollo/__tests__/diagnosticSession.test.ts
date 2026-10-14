/**
 * Wallet-recovery telemetry must leave the session exactly as it found it.
 *
 * It is sent from inside a FAILING sign-in, on whatever token happens to be
 * in Keychain. If that request can refresh the token or clear the session,
 * best-effort telemetry rewrites the credentials the recovery is still using.
 * Context flags alone did not cover this: the error link does its own
 * reactive refresh, and an unpinned caller never set the flag. So these run
 * through the real link chain, not a stub.
 */
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
jest.mock('react-native-device-info', () => ({ getVersion: () => '5.1.5', getBuildNumber: () => '1' }));
jest.mock('../../services/emergencyExit/banSignal', () => ({
  // The real rule: an authenticated 200 proves the middleware let us
  // through. Stubbing this to false would quietly disable the ban-clear
  // path for every test in this file.
  successProvesUnbanned: (headers?: Record<string, unknown>) =>
    !!(headers && (headers.Authorization || headers.authorization)),
  looksLikeBanResponse: () => false,
  markBanSignal: jest.fn(),
  clearBanSignal: jest.fn(),
}));
jest.mock('../../navigation/RootNavigation', () => ({ routeToBlockedAccount: jest.fn() }));
jest.mock('../../services/emergencyExit/store', () => ({ emergencyStore: {} }));
// Already expired: a proactive refresh would fire for any ordinary operation.
jest.mock('jwt-decode', () => ({
  jwtDecode: () => ({ user_id: 1, type: 'access', exp: Date.now() / 1000 - 60 }),
}));

import { gql } from '@apollo/client';
import * as Keychain from 'react-native-keychain';
import { apolloClient } from '../client';

const diagnostic = gql`
  mutation ReportWalletRecoveryDiagnostic($code: String!) {
    reportWalletRecoveryDiagnostic(code: $code) { success }
  }
`;
const ordinary = gql`
  mutation SomeOtherThing($code: String!) {
    someOtherThing(code: $code) { success }
  }
`;

const mockFetch = jest.fn();
const originalFetch = globalThis.fetch;
let storedTokens: { accessToken: string; refreshToken: string } | null;

const response = (body: unknown, status = 200) => ({
  status,
  ok: status >= 200 && status < 300,
  headers: { get: () => 'application/json' },
  json: async () => body,
  text: async () => JSON.stringify(body),
});
const bodyOf = (call: any) => JSON.parse(call[1].body);
const refreshCalls = () =>
  mockFetch.mock.calls.filter(call => bodyOf(call).query?.includes('RefreshToken'));

describe('wallet recovery diagnostics never move the session', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
    globalThis.fetch = mockFetch;
    storedTokens = { accessToken: 'stored-access', refreshToken: 'stored-refresh' };
    (Keychain.getGenericPassword as jest.Mock).mockImplementation(async () => storedTokens && ({
      username: 'auth_tokens', password: JSON.stringify(storedTokens),
    }));
    (Keychain.setGenericPassword as jest.Mock).mockImplementation(async (_u, password) => {
      storedTokens = JSON.parse(password);
      return true;
    });
    (Keychain.resetGenericPassword as jest.Mock).mockImplementation(async () => {
      storedTokens = null;
      return true;
    });
    jest.spyOn(console, 'error').mockImplementation(() => {});
    jest.spyOn(console, 'warn').mockImplementation(() => {});
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    jest.restoreAllMocks();
  });

  it('sends the stored token as-is instead of refreshing it first', async () => {
    mockFetch.mockResolvedValueOnce(
      response({ data: { reportWalletRecoveryDiagnostic: { success: true } } }),
    );

    await apolloClient.mutate({ mutation: diagnostic, variables: { code: 'unreadable' } });

    expect(refreshCalls()).toHaveLength(0);
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(mockFetch.mock.calls[0][1].headers.authorization).toBe('JWT stored-access');
    expect(Keychain.setGenericPassword).not.toHaveBeenCalled();
    expect(storedTokens).toEqual({ accessToken: 'stored-access', refreshToken: 'stored-refresh' });
  });

  it('does not refresh or replay when the server rejects the token as expired', async () => {
    mockFetch.mockResolvedValue(response({ errors: [{ message: 'Signature has expired' }] }));

    await apolloClient
      .mutate({ mutation: diagnostic, variables: { code: 'unreadable' } })
      .catch(() => {});

    expect(refreshCalls()).toHaveLength(0);
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(storedTokens).toEqual({ accessToken: 'stored-access', refreshToken: 'stored-refresh' });
  });

  it('does not clear the session when the server says the token was invalidated', async () => {
    mockFetch.mockResolvedValue(response({ errors: [{ message: 'Token has been invalidated' }] }));

    await apolloClient
      .mutate({ mutation: diagnostic, variables: { code: 'unreadable' } })
      .catch(() => {});

    expect(Keychain.resetGenericPassword).not.toHaveBeenCalled();
    expect(storedTokens).toEqual({ accessToken: 'stored-access', refreshToken: 'stored-refresh' });
  });

  it('does not route to BlockedAccount when only the diagnostic gets a 403', async () => {
    const { routeToBlockedAccount } = require('../../navigation/RootNavigation');
    const { markBanSignal } = require('../../services/emergencyExit/banSignal');
    mockFetch.mockResolvedValue(response({ errors: [{ message: 'Forbidden' }] }, 403));

    await apolloClient
      .mutate({ mutation: diagnostic, variables: { code: 'unreadable' } })
      .catch(() => {});

    expect(routeToBlockedAccount).not.toHaveBeenCalled();
    expect(markBanSignal).not.toHaveBeenCalled();
  });

  it('still routes to BlockedAccount on an ordinary 403', async () => {
    const { routeToBlockedAccount } = require('../../navigation/RootNavigation');
    mockFetch.mockResolvedValue(response({ errors: [{ message: 'Forbidden' }] }, 403));

    await apolloClient
      .mutate({ mutation: ordinary, variables: { code: 'unreadable' } })
      .catch(() => {});

    await new Promise(resolve => setTimeout(resolve, 0));
    expect(routeToBlockedAccount).toHaveBeenCalled();
  });

  it('does not clear a ban flag just because the diagnostic got through', async () => {
    const { clearBanSignal } = require('../../services/emergencyExit/banSignal');
    mockFetch.mockResolvedValueOnce(
      response({ data: { reportWalletRecoveryDiagnostic: { success: true } } }),
    );

    await apolloClient.mutate({ mutation: diagnostic, variables: { code: 'unreadable' } });
    await new Promise(resolve => setTimeout(resolve, 0));

    expect(clearBanSignal).not.toHaveBeenCalled();
  });

  it('still clears the ban flag on an ordinary authenticated success', async () => {
    const { clearBanSignal } = require('../../services/emergencyExit/banSignal');
    mockFetch
      .mockResolvedValueOnce(response({ data: { refreshToken: { token: 'fresh-access' } } }))
      .mockResolvedValueOnce(response({ data: { someOtherThing: { success: true } } }));

    await apolloClient
      .mutate({ mutation: ordinary, variables: { code: 'unreadable' } })
      .catch(() => {});
    await new Promise(resolve => setTimeout(resolve, 0));

    expect(clearBanSignal).toHaveBeenCalled();
  });

  it('still refreshes for an ordinary operation, so the checks above mean something', async () => {
    mockFetch
      .mockResolvedValueOnce(response({ data: { refreshToken: { token: 'fresh-access' } } }))
      .mockResolvedValueOnce(response({ data: { someOtherThing: { success: true } } }));

    await apolloClient
      .mutate({ mutation: ordinary, variables: { code: 'unreadable' } })
      .catch(() => {});

    expect(refreshCalls()).toHaveLength(1);
    expect(storedTokens).toEqual({ accessToken: 'fresh-access', refreshToken: 'stored-refresh' });
  });
});
