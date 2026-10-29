/**
 * The "already registered from this device" marker must name the ACCOUNT.
 *
 * 2026-10-29: a test account was deleted and signed up again on the same
 * device. One Google identity derives the same master secret, so the same BSC
 * address came back, the address-keyed marker from the previous account said
 * "already registered", and the NEW account never got a BSC address at all -
 * a live account the server had no wallet for.
 */
const mockMutate = jest.fn();
const mockGetGenericPassword = jest.fn();
const mockSetGenericPassword = jest.fn();
const mockEvmWallet = jest.fn();
const mockGetInternetCredentials = jest.fn();

// The same shallow mock set the other authService tests use, so importing the
// module does not drag in the native graph.
jest.mock('@react-native-google-signin/google-signin', () => ({
  GoogleSignin: { clearCachedAccessToken: jest.fn(), signOut: jest.fn(), configure: jest.fn(),
    hasPlayServices: jest.fn(), getCurrentUser: jest.fn(), signIn: jest.fn(), getTokens: jest.fn(), addScopes: jest.fn() },
  isSuccessResponse: () => false, isCancelledResponse: () => false, isErrorWithCode: () => false, statusCodes: {},
}));
jest.mock('@react-native-firebase/auth', () => ({ getAuth: () => ({}) }));
jest.mock('../../utils/accountManager', () => ({ AccountManager: {} }));
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
  getInternetCredentials: (...args: any[]) => mockGetInternetCredentials(...args),
  resetGenericPassword: jest.fn(),
  ACCESSIBLE: { AFTER_FIRST_UNLOCK: 'AfterFirstUnlock' },
}));
jest.mock('../../apollo/client', () => ({
  apolloClient: { mutate: (...args: any[]) => mockMutate(...args), query: jest.fn() },
  AUTH_KEYCHAIN_SERVICE: 'auth',
  AUTH_KEYCHAIN_USERNAME: 'user',
}));
jest.mock('../../apollo/queries', () => ({ UPDATE_ACCOUNT_BSC_ADDRESS: 'updateBsc' }));
jest.mock('../secureDeterministicWallet', () => ({
  getActiveEvmWallet: (...args: any[]) => mockEvmWallet(...args),
}));

import { Buffer } from 'buffer';
import { AuthService, ensureBscAddressRegistered } from '../authService';

const ADDRESS = '0x' + 'ab'.repeat(20);
// A JWT is three dot-joined segments; only the payload is read. exp must be
// well outside the proactive-refresh window or registration defers.
const tokenWith = (claims: Record<string, unknown>) =>
  `h.${Buffer.from(JSON.stringify({
    account_type: 'personal', account_index: 0,
    exp: Math.floor(Date.now() / 1000) + 3600,
    ...claims,
  })).toString('base64').replace(/=+$/, '')}.s`;
const tokenFor = (userId: number) => tokenWith({ user_id: userId });

describe('BSC address registration marker', () => {
  const markerStore = new Set<string>();
  let currentToken = '';
  const service = AuthService.getInstance() as any;

  beforeEach(() => {
    jest.clearAllMocks();
    markerStore.clear();
    service.getActiveAccountContext = jest.fn().mockResolvedValue({ type: 'personal', index: 0 });
    mockEvmWallet.mockResolvedValue({ address: ADDRESS });
    mockMutate.mockResolvedValue({ data: { updateAccountBscAddress: { success: true } } });
    mockGetGenericPassword.mockImplementation(async ({ service: name }: any) => {
      if (name === 'auth') return { password: JSON.stringify({ accessToken: currentToken }) };
      return markerStore.has(name) ? { password: '1' } : false;
    });
    mockSetGenericPassword.mockImplementation(async (_u: string, _p: string, { service: name }: any) => {
      markerStore.add(name);
      return true;
    });
    jest.spyOn(console, 'log').mockImplementation(() => {});
  });
  afterEach(() => jest.restoreAllMocks());

  const signedInAs = (userId: number) => { currentToken = tokenFor(userId); };

  it('registers again for a different account on the same device', async () => {
    signedInAs(13735);
    await ensureBscAddressRegistered();
    expect(mockMutate).toHaveBeenCalledTimes(1);

    // Same device, same Google identity, same derived address: a new account.
    signedInAs(13736);
    await ensureBscAddressRegistered();

    expect(mockMutate).toHaveBeenCalledTimes(2);
  });

  it('still skips a repeat for the same account', async () => {
    signedInAs(13735);
    await ensureBscAddressRegistered();
    await ensureBscAddressRegistered();

    expect(mockMutate).toHaveBeenCalledTimes(1);
  });

  // Without a usable id the marker cannot name an account, so a shared
  // "null-identity" marker would skip registration for everyone after the
  // first. Refuse instead of registering under a name we do not have.
  it.each([
    ['absent', {}],
    ['malformed', { user_id: 'not-a-number' }],
    ['beyond safe integers', { user_id: 9007199254740993 }],
    ['zero', { user_id: 0 }],
  ])('registers nothing when the token carries a %s user id', async (_label, claims) => {
    currentToken = tokenWith(claims);

    await ensureBscAddressRegistered();

    expect(mockMutate).not.toHaveBeenCalled();
    expect(mockSetGenericPassword).not.toHaveBeenCalled();
  });
});
