jest.mock('../secureDeterministicWallet', () => ({ createMissingSignInWalletCandidate: jest.fn(), getSignInWalletCandidate: jest.fn(), clearReconciledLegacyWallets: jest.fn().mockResolvedValue(undefined), reportBackupStatus: jest.fn().mockResolvedValue(true), reportTerminalRecoveryFailure: jest.fn(async (_e: any, _t: any, sink: any) => { if (sink) sink.reported = true; }) }));
jest.mock('../cloudKitBackup', () => ({ findCloudKitBackups: jest.fn() }));
import { createMissingSignInWalletCandidate, getSignInWalletCandidate, reportBackupStatus } from '../secureDeterministicWallet';
import { findCloudKitBackups } from '../cloudKitBackup';
import { reconcileSignInWallet } from '../signInWalletReconciliation';
import { WalletRecoveryError } from '../walletRecoveryErrors';

const discover = getSignInWalletCandidate as jest.Mock;
const lookup = findCloudKitBackups as jest.Mock;
const wallet = (bscAddress: string) => ({ algorandAddress: 'algo', bscAddress,
  persist: jest.fn().mockResolvedValue(undefined), publish: jest.fn().mockResolvedValue(undefined),
  hasPendingBackupReport: jest.fn().mockResolvedValue(false), clearPendingBackupReport: jest.fn().mockResolvedValue(undefined),
  sign: jest.fn().mockReturnValue('signature'), forAccount: jest.fn().mockImplementation(function(this: any) { return this; }) });

function fixture(provider: 'google' | 'apple', overrides: any = {}) {
  const args = { provider, subject: 'subject', firebaseToken: 'identity',
    authData: { user: { algorandAddress: null, bscAddress: '0xregistered' }, accessToken: 'session',
      isKeylessMigrated: true, isNewUser: false, ...overrides },
    getGoogleDriveToken: jest.fn().mockResolvedValue(provider === 'google' ? 'drive-token' : null),
    beforeWalletChange: jest.fn().mockResolvedValue(undefined),
    client: { mutate: jest.fn() },
  };
  args.client.mutate.mockImplementation(async ({ variables }: any) => {
    if ('firebaseIdToken' in variables) return { data: { prepareWalletReconciliation: {
      success: true, grant: 'grant', challenge: 'challenge',
      accounts: [{ accountId: '1', accountType: 'personal', accountIndex: 0, businessId: null,
        isKeylessMigrated: args.authData.isKeylessMigrated, ...args.authData.user }],
    } } };
    throw new Error('registration must not change');
  });
  return args;
}

beforeEach(() => {
  jest.clearAllMocks();
  discover.mockReset();
  lookup.mockReset();
  lookup.mockResolvedValue({ payloads: [], unknown: false });
});

it('never asks CloudKit when the local key already matches', async () => {
  discover.mockResolvedValueOnce(wallet('0xregistered'));
  await reconcileSignInWallet(fixture('apple'));
  expect(lookup).not.toHaveBeenCalled();
});

it('restores an Apple account from CloudKit and reports it as icloud', async () => {
  const restored = wallet('0xregistered');
  discover.mockResolvedValueOnce(null).mockResolvedValueOnce(restored);
  lookup.mockResolvedValue({ payloads: ['body'], unknown: false });
  expect(await reconcileSignInWallet(fixture('apple'))).toBe(false);
  expect(discover).toHaveBeenLastCalledWith('subject', undefined, expect.objectContaining({ cloudKitPayload: 'body' }));
  expect(restored.persist).toHaveBeenCalledTimes(1);
  expect(reportBackupStatus).toHaveBeenCalledWith('icloud', 'session');
});

it('restores a Google account without Drive and never claims Drive did it', async () => {
  const restored = wallet('0xregistered');
  discover.mockResolvedValueOnce(null).mockResolvedValueOnce(restored);
  lookup.mockResolvedValue({ payloads: ['body'], unknown: false });
  const args = fixture('google');
  await reconcileSignInWallet(args);
  expect(args.getGoogleDriveToken).not.toHaveBeenCalled();
  expect(reportBackupStatus).toHaveBeenCalledWith('icloud', 'session');
});

it('refuses a CloudKit record for another wallet and keeps the lockout answer', async () => {
  discover.mockResolvedValueOnce(null).mockResolvedValueOnce(wallet('0xother'));
  lookup.mockResolvedValue({ payloads: ['body'], unknown: false });
  await expect(reconcileSignInWallet(fixture('apple'))).rejects.toThrow(/RECOVERY-APPLE-KEYCHAIN/);
});

it('keeps today\'s answer when CloudKit has nothing', async () => {
  discover.mockResolvedValueOnce(null);
  await expect(reconcileSignInWallet(fixture('apple'))).rejects.toThrow(/RECOVERY-APPLE-KEYCHAIN/);
});

it('asks for a retry when iCloud cannot answer, not a lockout', async () => {
  discover.mockResolvedValueOnce(null);
  lookup.mockResolvedValue({ payloads: [], unknown: true });
  await expect(reconcileSignInWallet(fixture('apple'))).rejects.toThrow(/RECOVERY-ICLOUD-READ/);
});

it('does not leave a proven-unused wallet to replacement while iCloud cannot answer', async () => {
  discover.mockResolvedValueOnce(null);
  lookup.mockResolvedValue({ payloads: [], unknown: true });
  const args = fixture('apple', { user: { algorandAddress: 'algo-old', bscAddress: null },
    walletReenrollmentAllowed: true, isKeylessMigrated: false });
  await expect(reconcileSignInWallet(args)).rejects.toThrow(/RECOVERY-ICLOUD-READ/);
});

it('never swaps the registration to a local key while iCloud cannot answer', async () => {
  discover.mockResolvedValueOnce(wallet('0xother'));
  lookup.mockResolvedValue({ payloads: [], unknown: true });
  const args = fixture('apple');
  await expect(reconcileSignInWallet(args)).rejects.toThrow(/RECOVERY-ICLOUD-READ/);
  expect(args.beforeWalletChange).not.toHaveBeenCalled();
});

it('never provisions a new wallet while iCloud cannot answer and Drive is empty', async () => {
  discover.mockResolvedValueOnce(null)
    .mockRejectedValueOnce(new WalletRecoveryError('missing'))
    .mockRejectedValueOnce(new WalletRecoveryError('missing'));
  lookup.mockResolvedValue({ payloads: [], unknown: true });
  await expect(reconcileSignInWallet(fixture('google'))).rejects.toBeDefined();
  expect(createMissingSignInWalletCandidate).not.toHaveBeenCalled();
});

it('lets Drive finish the recovery when only iCloud is down', async () => {
  const fromDrive = wallet('0xregistered');
  discover.mockResolvedValueOnce(null).mockResolvedValueOnce(fromDrive);
  lookup.mockResolvedValue({ payloads: [], unknown: true });
  await reconcileSignInWallet(fixture('google'));
  expect(fromDrive.persist).toHaveBeenCalledTimes(1);
  expect(reportBackupStatus).toHaveBeenCalledWith('google_drive', 'session');
});
