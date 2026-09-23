const mockStored = { current: null as null | { password: string } };

jest.mock('react-native-keychain', () => ({
  getGenericPassword: jest.fn(async () => mockStored.current),
  setGenericPassword: jest.fn(async (_user: string, password: string) => {
    mockStored.current = { password };
    return true;
  }),
  resetGenericPassword: jest.fn(async () => true),
  ACCESSIBLE: { AFTER_FIRST_UNLOCK: 'AFTER_FIRST_UNLOCK' },
}));
jest.mock('react-native-device-info', () => ({ getVersion: () => '0', getBuildNumber: () => '0' }));
jest.mock('../../config/env', () => ({ getApiUrl: () => 'https://api.test/graphql/' }));
jest.mock('../../services/appCheckService', () => ({ __esModule: true, default: {} }));
jest.mock('../../utils/appCheckDiagnostics', () => ({ appCheckDiagnosticCode: () => '' }));

import { REFRESH_TIMEOUT_MS, refreshAccessToken } from '../client';

// Header {"alg":"HS256"}, payload {"account_type":"personal","account_index":0}.
const accessToken = 'eyJhbGciOiJIUzI1NiJ9.eyJhY2NvdW50X3R5cGUiOiJwZXJzb25hbCIsImFjY291bnRfaW5kZXgiOjB9.sig';
const tokens = { accessToken, refreshToken: 'refresh-1' };

describe('token refresh deadline', () => {
  const realFetch = globalThis.fetch;

  beforeEach(() => {
    jest.useFakeTimers();
    mockStored.current = { password: JSON.stringify(tokens) };
  });
  afterEach(() => {
    jest.useRealTimers();
    globalThis.fetch = realFetch;
  });

  it('a hung refresh times out, releases its slot, and the retry refreshes afresh', async () => {
    const signals: AbortSignal[] = [];
    globalThis.fetch = jest.fn((_url: string, init: { signal: AbortSignal }) => {
      signals.push(init.signal);
      if (signals.length === 1) {
        // Hangs until aborted.
        return new Promise((_resolve, reject) => {
          init.signal.addEventListener('abort', () => reject(new Error('Aborted')));
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({ data: { refreshToken: { token: 'fresh-access' } } }),
      });
    }) as any;

    const hung = refreshAccessToken(tokens);
    // A second caller shares the in-flight refresh instead of starting one.
    const shared = refreshAccessToken(tokens);
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);

    jest.advanceTimersByTime(REFRESH_TIMEOUT_MS);
    await expect(hung).rejects.toThrow('Aborted');
    await expect(shared).rejects.toThrow('Aborted');
    expect(signals[0].aborted).toBe(true);

    await expect(refreshAccessToken(tokens)).resolves.toBe('fresh-access');
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });
});
