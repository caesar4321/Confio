/**
 * App Review, 2026-10-20 (user 2176): an Apple account still on its V1 wallet,
 * holding only sponsor ALGO and empty opt-ins, could never sign in. The Apple
 * path asked the legacy check without the registered address, got no legacy
 * address back for an "empty" V1, and then demanded a V2 secret deriving to
 * that V1 address: RECOVERY-APPLE-KEYCHAIN every time.
 */
const mockMutate = jest.fn();

jest.mock('react-native', () => ({ Platform: { OS: 'ios' } }));
jest.mock('@react-native-google-signin/google-signin', () => ({ GoogleSignin: { configure: jest.fn() } }));
jest.mock('@invertase/react-native-apple-authentication', () => ({
  appleAuth: {
    performRequest: jest.fn().mockResolvedValue({ identityToken: 'apple-id-token', nonce: 'n', user: 'apple-sub' }),
    Operation: { LOGIN: 1 },
    Scope: { EMAIL: 0, FULL_NAME: 1 },
  },
}));
jest.mock('@react-native-firebase/auth', () => ({
  getAuth: () => ({}),
  AppleAuthProvider: { credential: jest.fn() },
  signInWithCredential: jest.fn().mockResolvedValue({ user: {} }),
  getIdToken: jest.fn().mockResolvedValue('firebase-token'),
}));
jest.mock('react-native-keychain', () => ({
  setGenericPassword: jest.fn().mockResolvedValue(true),
  getGenericPassword: jest.fn().mockResolvedValue({ password: 'jwt' }),
  getInternetCredentials: jest.fn().mockResolvedValue(null),
}));
jest.mock('../../apollo/client', () => ({
  apolloClient: { mutate: (...args: any[]) => mockMutate(...args) },
  AUTH_KEYCHAIN_SERVICE: 'auth', AUTH_KEYCHAIN_USERNAME: 'auth',
}));
jest.mock('../../apollo/mutations', () => ({ WEB3AUTH_LOGIN: {} }));
jest.mock('../../utils/accountManager', () => ({
  AccountManager: { getInstance: () => ({ setActiveAccountContext: jest.fn() }) },
}));
jest.mock('../../utils/deviceFingerprint', () => ({ DeviceFingerprint: { generateFingerprint: jest.fn().mockResolvedValue(null) } }));
jest.mock('../algorandService', () => ({}));
jest.mock('../oauthStorageService', () => ({
  oauthStorage: {
    storeOAuthSubject: jest.fn(),
    getOAuthSubject: jest.fn().mockResolvedValue({ subject: 'google-sub', provider: 'google' }),
  },
}));
jest.mock('../appCheckService', () => ({ appCheckService: { primeTokenForAuth: jest.fn() } }));
const mockGetOrCreateMasterSecret = jest.fn();
const mockGetActiveEvmWallet = jest.fn();
jest.mock('../secureDeterministicWallet', () => ({
  SecureDeterministicWalletService: { getInstance: () => ({}) },
  getOrCreateMasterSecret: (...args: any[]) => mockGetOrCreateMasterSecret(...args),
  getActiveEvmWallet: (...args: any[]) => mockGetActiveEvmWallet(...args),
  reportTerminalRecoveryFailure: jest.fn(),
}));
jest.mock('../evmWallet', () => ({ signEip191Message: jest.fn(() => '0xsigned') }));
jest.mock('../signInWalletReconciliation', () => ({ reconcileSignInWallet: jest.fn() }));
jest.mock('../signInSessionStorage', () => ({ persistSignInSession: jest.fn() }));
jest.mock('../../config/env', () => ({
  GOOGLE_CLIENT_IDS: { production: { web: 'web', ios: 'ios' }, development: { web: 'dev', ios: 'ios-dev' } },
  API_URL: 'https://confio.lat/graphql',
}));

import { AuthService } from '../authService';
import { WalletRecoveryError } from '../walletRecoveryErrors';

const V1_ADDRESS = 'UM3DCWWAUHXYHHKRMYZIOWTQ6CVEIUHBOCMZQSTFCCLC37I64MZ6AZMF2E';

it('gives the legacy check the registered V1 address and the session token', async () => {
  mockMutate.mockResolvedValue({ data: { web3AuthLogin: {
    success: true, accessToken: 'jwt', refreshToken: 'refresh',
    user: { id: '2176', algorandAddress: V1_ADDRESS, bscAddress: null },
  } } });
  const service = AuthService.getInstance() as any;
  const stop = new Error('stop after the legacy check');
  const inspect = jest.spyOn(service, 'getLegacyAddressIfMigrationPending').mockRejectedValue(stop);

  await expect(service.signInWithApple()).rejects.toBeDefined();

  expect(inspect).toHaveBeenCalledWith(
    'https://appleid.apple.com', 'apple-sub', 'com.confio.app', 'apple',
    { type: 'personal', index: 0 }, V1_ADDRESS, 'jwt',
  );
  inspect.mockRestore();
});

describe('the other legacy checks get the registered address too (Google and Apple)', () => {
  const personal = { type: 'personal', index: 0 };
  const stop = new Error('stop after the legacy check');
  let service: any;
  let inspect: jest.SpyInstance;

  beforeEach(() => {
    service = AuthService.getInstance() as any;
    service.auth = { currentUser: {} };
    jest.spyOn(service, 'getServerAccountForContext')
      .mockResolvedValue({ algorandAddress: V1_ADDRESS, isKeylessMigrated: false });
    inspect = jest.spyOn(service, 'getLegacyAddressIfMigrationPending').mockRejectedValue(stop);
  });
  afterEach(() => jest.restoreAllMocks());

  const lastAnchor = () => inspect.mock.calls[inspect.mock.calls.length - 1][5];

  it('when computing the account address', async () => {
    await service.computeAndStoreAlgorandAddress(personal);
    expect(inspect).toHaveBeenCalled();
    expect(lastAnchor()).toBe(V1_ADDRESS);
  });

  it('when a switch re-derives a stored address (and could register a replacement)', async () => {
    jest.spyOn(service, 'getStoredAlgorandAddress').mockResolvedValue(V1_ADDRESS);
    await service.switchAccount('personal_0');
    expect(inspect).toHaveBeenCalled();
    expect(lastAnchor()).toBe(V1_ADDRESS);
  });

  it('when a switch derives an address that was never stored', async () => {
    jest.spyOn(service, 'getStoredAlgorandAddress').mockResolvedValue(null);
    await service.switchAccount('personal_0');
    expect(inspect).toHaveBeenCalled();
    expect(lastAnchor()).toBe(V1_ADDRESS);
  });
});

describe('a registered wallet missing from iCloud Keychain (App Review, user 3478, 2026-10-30)', () => {
  const NEW_BSC = '0x' + '4'.repeat(40);
  const login = (offer: object) => ({ data: { web3AuthLogin: {
    success: true, accessToken: 'jwt', refreshToken: 'refresh',
    user: { id: '3478', algorandAddress: V1_ADDRESS, bscAddress: null }, ...offer,
  } } });
  const offer = { walletReenrollmentAllowed: true, walletReenrollmentChallenge: 'challenge', walletReenrollmentGrant: 'grant' };
  let service: any;
  let finish: jest.SpyInstance;

  beforeEach(() => {
    mockMutate.mockReset();
    mockGetOrCreateMasterSecret.mockReset();
    mockGetActiveEvmWallet.mockReset().mockResolvedValue({ address: NEW_BSC, privKeyHex: '0xkey' });
    service = AuthService.getInstance() as any;
    jest.spyOn(service, 'getLegacyAddressIfMigrationPending').mockResolvedValue({
      legacyAddress: null, derivedLegacyAddress: 'OTHER', inspectionSucceeded: true,
    });
    jest.spyOn(service, 'invalidateSignInSession').mockResolvedValue(undefined);
    finish = jest.spyOn(service, 'finishAppleSignIn').mockResolvedValue('signed-in');
    mockGetOrCreateMasterSecret.mockRejectedValueOnce(new WalletRecoveryError('missing')).mockResolvedValue(new Uint8Array(32));
  });
  afterEach(() => jest.restoreAllMocks());

  it('replaces a wallet the server offered, through the shared step', async () => {
    // protects=an Apple account with a proven-unused wallet can get in on a clean device; fails_when=Apple sign-in stops at RECOVERY-APPLE-KEYCHAIN or skips the server commit; no_claim=the server's proof of non-use
    mockMutate.mockResolvedValueOnce(login(offer))
      .mockResolvedValue({ data: { completeWalletReenrollment: { success: true } } });

    await expect(service.signInWithApple()).resolves.toBe('signed-in');

    expect(mockGetOrCreateMasterSecret.mock.calls[0][2]).toMatchObject({ allowGenerate: false, expectedAddress: V1_ADDRESS });
    expect(mockGetOrCreateMasterSecret.mock.calls[1][2]).toMatchObject({ allowGenerate: true, provider: 'apple' });
    expect(mockMutate.mock.calls[1][0].variables).toEqual({ bscAddress: NEW_BSC, reenrollmentGrant: 'grant', bscSignature: '0xsigned' });
    expect(finish).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({
      user: expect.objectContaining({ algorandAddress: null, bscAddress: NEW_BSC }),
    }), null);
  });

  it('never generates a wallet without the offer', async () => {
    // protects=funded or unproven wallets keep the lockout instead of being replaced; fails_when=a missing secret alone mints a new wallet; no_claim=the wording of the guidance
    mockMutate.mockResolvedValue(login({}));

    await expect(service.signInWithApple()).rejects.toThrow('RECOVERY-APPLE-KEYCHAIN');

    expect(mockGetOrCreateMasterSecret).toHaveBeenCalledTimes(1);
    expect(finish).not.toHaveBeenCalled();
  });
});
