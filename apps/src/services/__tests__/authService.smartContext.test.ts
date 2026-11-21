/**
 * Switching to a Cuenta inteligente FAILS CLOSED (authService.switchToSmartAccount,
 * ensureSmartContextToken): a smart context with a personal or business token
 * would show one account's screens over another account's money. Without a
 * server token that names the exact smart account, the previous context comes
 * back and nothing is written to the keychain.
 */
const mockGetGenericPassword = jest.fn();
const mockSetGenericPassword = jest.fn();

jest.mock('@react-native-google-signin/google-signin', () => ({
  GoogleSignin: { clearCachedAccessToken: jest.fn(), signOut: jest.fn(), configure: jest.fn(),
    hasPlayServices: jest.fn(), getCurrentUser: jest.fn(), signIn: jest.fn(), getTokens: jest.fn(), addScopes: jest.fn() },
  isSuccessResponse: () => false, isCancelledResponse: () => false, isErrorWithCode: () => false, statusCodes: {},
}));
jest.mock('@react-native-firebase/auth', () => ({ getAuth: () => ({}) }));
jest.mock('../../utils/deviceFingerprint', () => ({ DeviceFingerprint: {} }));
jest.mock('../algorandService', () => ({}));
jest.mock('../oauthStorageService', () => ({ oauthStorage: {} }));
jest.mock('../../config/env', () => ({
  GOOGLE_CLIENT_IDS: { production: { web: 'web', ios: 'ios' }, development: { web: 'dev', ios: 'ios-dev' } },
  API_URL: 'https://confio.lat/graphql',
}));
jest.mock('react-native-keychain', () => ({
  getGenericPassword: (...args: any[]) => mockGetGenericPassword(...args),
  setGenericPassword: (...args: any[]) => mockSetGenericPassword(...args),
  getInternetCredentials: jest.fn(),
  resetGenericPassword: jest.fn(),
  ACCESSIBLE: { AFTER_FIRST_UNLOCK: 'AfterFirstUnlock' },
}));
jest.mock('../../apollo/client', () => ({
  apolloClient: { mutate: jest.fn(), query: jest.fn() },
  AUTH_KEYCHAIN_SERVICE: 'auth',
  AUTH_KEYCHAIN_USERNAME: 'user',
}));
jest.mock('../../apollo/queries', () => ({ SWITCH_ACCOUNT_TOKEN: 'switchAccountToken' }));
jest.mock('../secureDeterministicWallet', () => ({ getActiveEvmWallet: jest.fn() }));

// The real id parser, an in-memory active context.
const mockManager: any = {};
jest.mock('../../utils/accountManager', () => {
  const actual = jest.requireActual('../../utils/accountManager');
  return { ...actual, AccountManager: { getInstance: () => mockManager } };
});

import { Buffer } from 'buffer';
import { AuthService } from '../authService';

const { AccountManager: RealManager } = jest.requireActual('../../utils/accountManager');
const real = Object.create(RealManager.prototype);

const token = (claims: Record<string, unknown>) =>
  `h.${Buffer.from(JSON.stringify({ user_id: 7, exp: Math.floor(Date.now() / 1000) + 3600, ...claims }))
    .toString('base64').replace(/=+$/, '')}.s`;

let active: any;
const service = AuthService.getInstance() as any;
const apollo = { mutate: jest.fn() };

beforeEach(() => {
  jest.clearAllMocks();
  active = { type: 'personal', index: 0 };
  mockManager.parseAccountId = (id: string) => real.parseAccountId(id);
  mockManager.contextToAccountId = (ctx: any) => real.contextToAccountId(ctx);
  mockManager.getDefaultAccountContext = () => ({ type: 'personal', index: 0 });
  mockManager.getActiveAccountContext = jest.fn(async () => active);
  mockManager.setActiveAccountContext = jest.fn(async (ctx: any) => { active = ctx; });
  mockGetGenericPassword.mockResolvedValue({ password: JSON.stringify({ accessToken: token({ account_type: 'personal', account_index: 0 }), refreshToken: 'r1' }) });
  mockSetGenericPassword.mockResolvedValue(true);
  jest.spyOn(console, 'log').mockImplementation(() => {});
  jest.spyOn(console, 'warn').mockImplementation(() => {});
  jest.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => jest.restoreAllMocks());

const switchTokenReturns = (t: string | null) =>
  apollo.mutate.mockResolvedValue({ data: { switchAccountToken: t ? { token: t } : null } });

describe('switchAccount to a smart account', () => {
  it('stores a token that names the smart account and keeps the refresh token', async () => {
    switchTokenReturns(token({ account_type: 'smart', account_index: 0 }));
    await service.switchAccount('smart_0', apollo);
    expect(apollo.mutate.mock.calls[0][0].variables).toEqual({ accountType: 'smart', accountIndex: 0 });
    expect(active).toEqual(expect.objectContaining({ type: 'smart', index: 0 }));
    const stored = JSON.parse(mockSetGenericPassword.mock.calls[0][1]);
    expect(stored.refreshToken).toBe('r1');
    expect(stored.accessToken).toContain('h.');
  });

  it.each([
    ['an older server answering with a personal token', token({ account_type: 'personal', account_index: 0 })],
    ['a token for another inherited account', token({ account_type: 'smart', account_index: 2 })],
  ])('fails closed on %s', async (_label, t) => {
    switchTokenReturns(t);
    await expect(service.switchAccount('smart_1', apollo)).rejects.toThrow('smart_switch_wrong_context');
    expect(active).toEqual({ type: 'personal', index: 0 });
    expect(mockSetGenericPassword).not.toHaveBeenCalled();
  });

  it('fails closed when the server refuses or cannot be reached', async () => {
    switchTokenReturns(null);
    await expect(service.switchAccount('smart_0', apollo)).rejects.toThrow('smart_switch_refused');
    expect(active).toEqual({ type: 'personal', index: 0 });
    apollo.mutate.mockRejectedValue(new Error('Network request failed'));
    await expect(service.switchAccount('smart_0', apollo)).rejects.toThrow('Network request failed');
    expect(active).toEqual({ type: 'personal', index: 0 });
    expect(mockSetGenericPassword).not.toHaveBeenCalled();
  });

  it('refuses without a server client at all', async () => {
    await expect(service.switchAccount('smart_0')).rejects.toThrow('smart_switch_requires_server');
    expect(active).toEqual({ type: 'personal', index: 0 });
  });
});

describe('ensureSmartContextToken at app start', () => {
  it('does nothing outside a smart context', async () => {
    expect(await service.ensureSmartContextToken(apollo)).toBe('ok');
    expect(apollo.mutate).not.toHaveBeenCalled();
  });

  it('accepts a stored token that already names the smart account', async () => {
    active = { type: 'smart', index: 1 };
    mockGetGenericPassword.mockResolvedValue({ password: JSON.stringify({ accessToken: token({ account_type: 'smart', account_index: 1 }) }) });
    expect(await service.ensureSmartContextToken(apollo)).toBe('ok');
    expect(apollo.mutate).not.toHaveBeenCalled();
  });

  it('realigns a lagging token through the server', async () => {
    active = { type: 'smart', index: 0 };
    switchTokenReturns(token({ account_type: 'smart', account_index: 0 }));
    expect(await service.ensureSmartContextToken(apollo)).toBe('ok');
    expect(active).toEqual(expect.objectContaining({ type: 'smart', index: 0 }));
  });

  it('returns to the personal wallet when the smart token cannot be confirmed', async () => {
    active = { type: 'smart', index: 0 };
    apollo.mutate.mockRejectedValue(new Error('Network request failed'));
    const personalSwitch = jest.spyOn(service, 'switchAccount').mockImplementation(async (id: any) => {
      if (id === 'personal_0') {
        active = { type: 'personal', index: 0 };
        return;
      }
      throw new Error('unexpected');
    });
    expect(await service.ensureSmartContextToken(apollo)).toBe('reset');
    expect(personalSwitch).toHaveBeenCalledWith('personal_0', apollo);
    expect(active).toEqual({ type: 'personal', index: 0 });
  });

  it('falls back to the default context even if the personal switch fails too', async () => {
    active = { type: 'smart', index: 0 };
    apollo.mutate.mockRejectedValue(new Error('Network request failed'));
    jest.spyOn(service, 'switchAccount').mockRejectedValue(new Error('offline'));
    expect(await service.ensureSmartContextToken(apollo)).toBe('reset');
    expect(active).toEqual({ type: 'personal', index: 0 });
  });
});
