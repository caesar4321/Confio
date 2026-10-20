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
jest.mock('react-native-keychain', () => ({ setGenericPassword: jest.fn().mockResolvedValue(true) }));
jest.mock('../../apollo/client', () => ({
  apolloClient: { mutate: (...args: any[]) => mockMutate(...args) },
  AUTH_KEYCHAIN_SERVICE: 'auth', AUTH_KEYCHAIN_USERNAME: 'auth',
}));
jest.mock('../../apollo/mutations', () => ({ WEB3AUTH_LOGIN: {} }));
jest.mock('../../utils/accountManager', () => ({ AccountManager: {} }));
jest.mock('../../utils/deviceFingerprint', () => ({ DeviceFingerprint: { generateFingerprint: jest.fn().mockResolvedValue(null) } }));
jest.mock('../algorandService', () => ({}));
jest.mock('../oauthStorageService', () => ({ oauthStorage: { storeOAuthSubject: jest.fn() } }));
jest.mock('../appCheckService', () => ({ appCheckService: { primeTokenForAuth: jest.fn() } }));
jest.mock('../signInWalletReconciliation', () => ({ reconcileSignInWallet: jest.fn() }));
jest.mock('../signInSessionStorage', () => ({ persistSignInSession: jest.fn() }));
jest.mock('../../config/env', () => ({
  GOOGLE_CLIENT_IDS: { production: { web: 'web', ios: 'ios' }, development: { web: 'dev', ios: 'ios-dev' } },
  API_URL: 'https://confio.lat/graphql',
}));

import { AuthService } from '../authService';

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
});
