/** Google's half of the shared wallet replacement: the Drive backup comes first. */
const mockMutate = jest.fn();
const mockGetOrCreateMasterSecret = jest.fn();
const mockGetActiveEvmWallet = jest.fn();
const mockAttest = jest.fn();

jest.mock('@react-native-google-signin/google-signin', () => ({ GoogleSignin: { configure: jest.fn() } }));
jest.mock('@react-native-firebase/auth', () => ({ getAuth: () => ({}) }));
jest.mock('react-native-keychain', () => ({}));
jest.mock('../../apollo/client', () => ({ apolloClient: { mutate: (...args: any[]) => mockMutate(...args) } }));
jest.mock('../../utils/accountManager', () => ({ AccountManager: {} }));
jest.mock('../../utils/deviceFingerprint', () => ({ DeviceFingerprint: {} }));
jest.mock('../algorandService', () => ({}));
jest.mock('../oauthStorageService', () => ({ oauthStorage: {} }));
jest.mock('../secureDeterministicWallet', () => ({
  getOrCreateMasterSecret: (...args: any[]) => mockGetOrCreateMasterSecret(...args),
  getActiveEvmWallet: (...args: any[]) => mockGetActiveEvmWallet(...args),
  createWalletReenrollmentDriveAttestation: (...args: any[]) => mockAttest(...args),
}));
jest.mock('../../config/env', () => ({
  GOOGLE_CLIENT_IDS: { production: { web: 'web', ios: 'ios' }, development: { web: 'dev', ios: 'ios-dev' } },
  API_URL: 'https://confio.lat/graphql',
}));

import { AuthService, driveWalletBackup } from '../authService';

const NEW_BSC = '0x' + '5'.repeat(40);
const wallet = { address: NEW_BSC, privKeyHex: '0xkey' };

describe('replacing a proven-unused wallet on Google', () => {
  let invalidateSession: jest.Mock;
  let persistSession: jest.Mock;
  let onCloudSyncResult: jest.Mock;
  let authData: any;

  const replace = (driveToken: string | undefined = 'drive-token') => (AuthService.getInstance() as any).replaceUnusedWallet({
    authData, invalidateSession, persistSession,
    backup: driveWalletBackup({
      subject: 'google-sub', driveToken: () => driveToken, sessionToken: 'jwt', onCloudSyncResult,
    }),
  });

  beforeEach(() => {
    jest.resetAllMocks();
    invalidateSession = jest.fn().mockResolvedValue(undefined);
    persistSession = jest.fn().mockResolvedValue(undefined);
    onCloudSyncResult = jest.fn();
    authData = { accessToken: 'jwt', walletReenrollmentChallenge: 'challenge', walletReenrollmentGrant: 'grant',
      user: { algorandAddress: 'OLD', bscAddress: null } };
    mockGetActiveEvmWallet.mockResolvedValue(wallet);
    mockAttest.mockResolvedValue({ ownershipSignature: '0xdrive' });
    mockGetOrCreateMasterSecret.mockImplementation(async (_sub, _token, options) => options.onCloudSyncResult(true));
    mockMutate.mockResolvedValue({ data: { completeWalletReenrollment: { success: true } } });
  });

  it('commits only after a verified upload, signed by the Drive attestation', async () => {
    // protects=the Drive path kept its checks through the move to the shared step; fails_when=the upload is optional or the attestation is skipped; no_claim=what Drive stores
    await expect(replace()).resolves.toBe(NEW_BSC);

    expect(mockGetOrCreateMasterSecret).toHaveBeenCalledWith('google-sub', 'drive-token', expect.objectContaining({
      allowGenerate: true, provider: 'google', requireCloudSync: true, backupReportAuthToken: 'jwt',
    }));
    expect(mockAttest).toHaveBeenCalledWith('drive-token', 'challenge', NEW_BSC, '0xkey');
    expect(mockMutate.mock.calls[0][0].variables).toEqual({ bscAddress: NEW_BSC, reenrollmentGrant: 'grant', bscSignature: '0xdrive' });
    expect(onCloudSyncResult).toHaveBeenLastCalledWith(true);
    expect(authData.user).toEqual({ algorandAddress: null, bscAddress: NEW_BSC });
    expect(persistSession).toHaveBeenCalledTimes(1);
  });

  it('keeps the session when there is no Drive access yet', async () => {
    // protects=a valid session survives a repair that could not start; fails_when=the session is dropped before prerequisites hold; no_claim=the wording
    await expect(replace('')).rejects.toThrow('activa el respaldo en Google Drive');
    expect(invalidateSession).not.toHaveBeenCalled();
    expect(mockGetOrCreateMasterSecret).not.toHaveBeenCalled();
  });

  it('never commits when the Drive upload did not verify', async () => {
    // protects=a replacement wallet always has an off-device backup; fails_when=a failed sync still retires the old wallet; no_claim=why the upload failed
    mockGetOrCreateMasterSecret.mockImplementation(async (_sub, _token, options) => options.onCloudSyncResult(false));

    await expect(replace()).rejects.toThrow('No pudimos verificar el respaldo');

    expect(mockMutate).not.toHaveBeenCalled();
    expect(invalidateSession).toHaveBeenLastCalledWith('after wallet reenrollment failure');
    expect(persistSession).not.toHaveBeenCalled();
  });
});
