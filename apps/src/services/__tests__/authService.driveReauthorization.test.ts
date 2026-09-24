jest.mock('@react-native-google-signin/google-signin', () => ({
  GoogleSignin: { clearCachedAccessToken: jest.fn(), signOut: jest.fn(), configure: jest.fn(),
    hasPlayServices: jest.fn(), getCurrentUser: jest.fn(), signIn: jest.fn(), getTokens: jest.fn(), addScopes: jest.fn() },
  isSuccessResponse: (r: any) => r?.type === 'success',
  isCancelledResponse: (r: any) => r?.type === 'cancelled',
  isErrorWithCode: () => false, statusCodes: {},
}));
jest.mock('@react-native-firebase/auth', () => ({ getAuth: () => ({}) }));
jest.mock('react-native-keychain', () => ({}));
jest.mock('../../apollo/client', () => ({ apolloClient: {} }));
jest.mock('../../utils/accountManager', () => ({ AccountManager: {} }));
jest.mock('../../utils/deviceFingerprint', () => ({ DeviceFingerprint: {} }));
jest.mock('../algorandService', () => ({}));
jest.mock('../oauthStorageService', () => ({ oauthStorage: {} }));
jest.mock('../../config/env', () => ({
  GOOGLE_CLIENT_IDS: { production: { web: 'web', ios: 'ios' }, development: { web: 'dev', ios: 'ios-dev' } },
  API_URL: 'https://confio.lat/graphql',
}));

import { GoogleSignin } from '@react-native-google-signin/google-signin';
import { AuthService } from '../authService';

const google = GoogleSignin as jest.Mocked<typeof GoogleSignin>;
const service = AuthService.getInstance() as any;
const scopedUser = (id: string) => ({ user: { id }, scopes: ['https://www.googleapis.com/auth/drive.appdata'] });

beforeEach(() => {
  jest.resetAllMocks();
  service.driveAccessToken = 'rejected';
  google.clearCachedAccessToken.mockResolvedValue(null);
  google.signOut.mockResolvedValue(null);
  google.getCurrentUser.mockReturnValue(scopedUser('subject') as any);
  google.getTokens.mockResolvedValue({ accessToken: 'fresh', idToken: 'id' });
});

it('clears the exact rejected token before fresh same-account authorization', async () => {
  google.getCurrentUser.mockReturnValueOnce(null);
  google.signIn.mockResolvedValue({ type: 'success', data: scopedUser('subject') } as any);
  expect(await service.renewSignInDriveAccess('rejected', 'subject')).toBe('fresh');
  expect(google.clearCachedAccessToken).toHaveBeenCalledWith('rejected');
  expect(google.clearCachedAccessToken.mock.invocationCallOrder[0]).toBeLessThan(google.signOut.mock.invocationCallOrder[0]);
  expect(google.signOut.mock.invocationCallOrder[0]).toBeLessThan(google.getTokens.mock.invocationCallOrder[0]);
  expect(google.signIn).toHaveBeenCalledTimes(1);
  expect(service.driveAccessToken).toBe('fresh');
});

it('rejects a different account before obtaining its Drive token', async () => {
  google.getCurrentUser.mockReturnValue(scopedUser('other-subject') as any);
  await expect(service.renewSignInDriveAccess('rejected', 'subject')).rejects.toMatchObject({ name: 'GoogleDriveAccountMismatchError' });
  expect(google.getTokens).not.toHaveBeenCalled();
  expect(service.driveAccessToken).toBeNull();
});

it('returns cancellation without fetching a token or retaining the rejected token', async () => {
  google.getCurrentUser.mockReturnValue(null);
  google.signIn.mockResolvedValue({ type: 'cancelled', data: null } as any);
  expect(await service.renewSignInDriveAccess('rejected', 'subject')).toBeNull();
  expect(google.getTokens).not.toHaveBeenCalled();
  expect(service.driveAccessToken).toBeNull();
});

it('clears the supplied rejected token even if memory currently holds another token', async () => {
  service.driveAccessToken = 'other';
  await service.clearRejectedDriveToken('rejected');
  expect(google.clearCachedAccessToken).toHaveBeenCalledWith('rejected');
  expect(service.driveAccessToken).toBe('other');
});
