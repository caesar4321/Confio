jest.mock('../secureDeterministicWallet', () => ({ getSignInWalletCandidate: jest.fn(), clearReconciledLegacyWallets: jest.fn().mockResolvedValue(undefined), reportBackupStatus: jest.fn().mockResolvedValue(true) }));
import { getSignInWalletCandidate, reportBackupStatus } from '../secureDeterministicWallet';
import { reconcileSignInWallet } from '../signInWalletReconciliation';
import { WalletRecoveryError } from '../walletRecoveryErrors';

const recover = getSignInWalletCandidate as jest.Mock;
const candidate = () => ({ algorandAddress: 'new-algo', bscAddress: '0xnew',
  persist: jest.fn().mockResolvedValue(undefined), publish: jest.fn().mockResolvedValue(undefined),
  hasPendingBackupReport: jest.fn().mockResolvedValue(false), clearPendingBackupReport: jest.fn().mockResolvedValue(undefined),
  sign: jest.fn().mockReturnValue('signature'), forAccount: jest.fn().mockImplementation(function(this: any) { return this; }) });
function fixture(provider: 'google' | 'apple' = 'google') {
  const args = { provider, subject: 'subject', firebaseToken: 'fresh-identity',
    authData: { user: { algorandAddress: 'old-algo', bscAddress: '0xold' },
      accessToken: 'session', isKeylessMigrated: true, isNewUser: false },
    getGoogleDriveToken: jest.fn().mockResolvedValue('drive-token'),
    beforeWalletChange: jest.fn().mockResolvedValue(undefined),
    client: { mutate: jest.fn() },
  };
  args.client.mutate.mockImplementation(async ({ variables }) => {
    const accounts = [{ accountId: '1', accountType: 'personal', accountIndex: 0, businessId: null,
      isKeylessMigrated: args.authData.isKeylessMigrated, ...args.authData.user }];
    if ('firebaseIdToken' in variables) return { data: { prepareWalletReconciliation: {
      success: true, grant: 'grant', challenge: 'challenge', accounts,
    } } };
    return { data: { completeWalletReconciliation: {
      success: true, bscAddress: '0xnew', accounts: accounts.map(row => ({
        ...row, algorandAddress: null, bscAddress: '0xnew', isKeylessMigrated: true,
      })),
    } } };
  });
  return args;
}
beforeEach(() => { jest.clearAllMocks(); recover.mockReset(); });

it('Google activates the canonical Drive wallet without checking old funds', async () => {
  const local = candidate();
  const canonical = candidate();
  recover.mockResolvedValueOnce(local).mockResolvedValueOnce(canonical);
  const args = fixture();
  expect(await reconcileSignInWallet(args)).toBe(true);
  expect(recover.mock.calls).toEqual([['subject'], ['subject', 'drive-token']]);
  expect(local.persist).not.toHaveBeenCalled();
  expect(canonical.persist).toHaveBeenCalledTimes(1);
  expect(args.beforeWalletChange.mock.invocationCallOrder[0]).toBeLessThan(canonical.persist.mock.invocationCallOrder[0]);
  expect(canonical.publish).toHaveBeenCalledTimes(1);
  expect(canonical.publish.mock.invocationCallOrder[0]).toBeGreaterThan(args.client.mutate.mock.invocationCallOrder[1]);
  expect(args.authData.user).toEqual({ algorandAddress: null, bscAddress: '0xnew' });
  expect(args.client.mutate.mock.calls[2][0].variables).toEqual({ grant: 'grant', signature: 'signature',
    wallets: [{ accountId: '1', bscAddress: '0xnew', signature: 'signature' }] });
});
it('Apple reconciles from Keychain with no Google authorization', async () => {
  recover.mockResolvedValueOnce(candidate());
  const args = fixture('apple');
  expect(await reconcileSignInWallet(args)).toBe(true);
  expect(args.getGoogleDriveToken).not.toHaveBeenCalled();
});
it('matching wallets do not upload backups or change registration', async () => {
  const wallet = candidate();
  recover.mockResolvedValueOnce(wallet);
  const args = fixture();
  args.authData.user = { algorandAddress: 'new-algo', bscAddress: '0xNEW' };
  expect(await reconcileSignInWallet(args)).toBe(false);
  expect(args.client.mutate).toHaveBeenCalledTimes(1);
  expect(wallet.persist).not.toHaveBeenCalled();
  expect(wallet.publish).toHaveBeenCalledTimes(1);
  expect(args.getGoogleDriveToken).not.toHaveBeenCalled();
});

it('does not finish sign-in until the active receiving cache is published', async () => {
  const wallet = candidate();
  recover.mockResolvedValueOnce(wallet);
  wallet.publish.mockRejectedValueOnce(new Error('Keychain unavailable'));
  const args = fixture('apple');
  await expect(reconcileSignInWallet(args)).rejects.toThrow('Keychain unavailable');
  // The committed wallet is recovered again on retry; cache failure is not
  // permission to enter the app with the retired receiving address.
  expect(args.authData.user.bscAddress).toBe(wallet.bscAddress);
  expect(args.client.mutate).toHaveBeenCalledTimes(3);
});
it('matching Google wallet with an unfinished backup can reach backup setup', async () => {
  const wallet = candidate();
  recover.mockResolvedValueOnce(wallet);
  const args = fixture();
  args.authData.user = { algorandAddress: 'new-algo', bscAddress: '0xNEW' };
  (args.authData as any).requiresBackupCompletion = true;
  expect(await reconcileSignInWallet(args)).toBe(false);
  expect((args.authData as any).requiresBackupCompletion).toBe(true);
  expect(args.getGoogleDriveToken).not.toHaveBeenCalled();
  expect(reportBackupStatus).not.toHaveBeenCalled();
  expect(args.client.mutate).toHaveBeenCalledTimes(1);
  expect(wallet.persist).not.toHaveBeenCalled();
});
it.each(['missing', 'unreadable', 'drive_access'] as const)('does not replace on %s backup', async code => {
  recover.mockResolvedValueOnce(candidate()).mockRejectedValueOnce(new WalletRecoveryError(code));
  if (code === 'missing') recover.mockRejectedValueOnce(new WalletRecoveryError('missing'));
  const args = fixture();
  await expect(reconcileSignInWallet(args)).rejects.toThrow();
  expect(args.client.mutate).toHaveBeenCalledTimes(1);
  expect(args.authData.user.bscAddress).toBe('0xold');
});
it('Keychain write failure prevents server commit', async () => {
  const wallet = candidate();
  wallet.persist.mockRejectedValueOnce(new Error('locked'));
  recover.mockResolvedValueOnce(wallet);
  const args = fixture('apple');
  await expect(reconcileSignInWallet(args)).rejects.toThrow('locked');
  expect(args.client.mutate).toHaveBeenCalledTimes(2);
});

it('does not overwrite key material when the previous session cannot be suspended', async () => {
  const wallet = candidate();
  recover.mockResolvedValueOnce(wallet);
  const args = fixture('apple');
  args.beforeWalletChange.mockRejectedValueOnce(new Error('Keychain locked'));
  await expect(reconcileSignInWallet(args)).rejects.toThrow('Keychain locked');
  expect(wallet.persist).not.toHaveBeenCalled();
  expect(wallet.publish).not.toHaveBeenCalled();
  expect(args.client.mutate).toHaveBeenCalledTimes(2);
});
it('commit failure does not pretend funds migrated', async () => {
  const wallet = candidate();
  recover.mockResolvedValueOnce(wallet);
  const args = fixture('apple');
  const implementation = args.client.mutate.getMockImplementation()!;
  args.client.mutate.mockImplementation(call => 'wallets' in call.variables
    ? Promise.reject(new Error('network')) : implementation(call));
  await expect(reconcileSignInWallet(args)).rejects.toThrow('network');
  expect(args.authData.user.algorandAddress).toBe('old-algo');
  expect(wallet.publish).not.toHaveBeenCalled();
});
it('new users retain the existing signup path', async () => {
  const args = fixture(); args.authData.isNewUser = true;
  expect(await reconcileSignInWallet(args)).toBe(false);
  expect(recover).not.toHaveBeenCalled();
});

it('Apple with a missing V2 Keychain fails without Google or generation', async () => {
  recover.mockResolvedValueOnce(null);
  const args = fixture('apple');
  await expect(reconcileSignInWallet(args)).rejects.toThrow('RECOVERY-APPLE-KEYCHAIN');
  expect(args.getGoogleDriveToken).not.toHaveBeenCalled();
  expect(args.client.mutate).toHaveBeenCalledTimes(1);
});

it('restores a Drive wallet matching the server without changing registration', async () => {
  const wallet = candidate();
  const args = fixture();
  args.authData.user = { algorandAddress: 'new-algo', bscAddress: '0xnew' };
  recover.mockResolvedValueOnce(null).mockResolvedValueOnce(wallet);
  expect(await reconcileSignInWallet(args)).toBe(false);
  expect(wallet.persist).toHaveBeenCalledTimes(1);
  expect(args.client.mutate).toHaveBeenCalledTimes(1);
});

it('genuinely absent V1 backup preserves the existing legacy recovery path', async () => {
  recover.mockResolvedValueOnce(null).mockRejectedValueOnce(new WalletRecoveryError('missing'))
    .mockRejectedValueOnce(new WalletRecoveryError('missing'));
  const args = fixture();
  args.authData.isKeylessMigrated = false;
  args.authData.user.bscAddress = null as any;
  expect(await reconcileSignInWallet(args)).toBe(false);
  expect(args.client.mutate).toHaveBeenCalledTimes(1);
});

it('authorization rejection never changes Keychain', async () => {
  const wallet = candidate(); recover.mockResolvedValueOnce(wallet);
  const args = fixture('apple');
  args.client.mutate.mockReset().mockResolvedValueOnce({ data: { prepareWalletReconciliation: { success: false } } });
  await expect(reconcileSignInWallet(args)).rejects.toThrow('RECONCILE-AUTH');
  expect(wallet.persist).not.toHaveBeenCalled();
});

it('acknowledges the recovered backup inside sign-in without routing to setup', async () => {
  const args = fixture('apple');
  (args.authData as any).requiresBackupCompletion = true;
  recover.mockResolvedValueOnce(candidate());
  expect(await reconcileSignInWallet(args)).toBe(true);
  expect(reportBackupStatus).toHaveBeenCalledWith('icloud', 'session');
  expect((args.authData as any).requiresBackupCompletion).toBe(false);
});

it('failed backup acknowledgement is retried even after registration committed', async () => {
  const args = fixture('apple');
  (args.authData as any).requiresBackupCompletion = true;
  recover.mockResolvedValue(candidate());
  (reportBackupStatus as jest.Mock).mockResolvedValueOnce(false);
  await expect(reconcileSignInWallet(args)).rejects.toThrow('RECONCILE-BACKUP-REPORT');
  // The server already committed; matching local key retries only the report.
  expect(await reconcileSignInWallet(args)).toBe(false);
  expect(args.client.mutate).toHaveBeenCalledTimes(4);
});

it('Google retries a durable verified-backup receipt after a committed replacement', async () => {
  const args = fixture();
  (args.authData as any).requiresBackupCompletion = true;
  const wallet = candidate();
  recover.mockResolvedValue(wallet);
  (reportBackupStatus as jest.Mock).mockResolvedValueOnce(false);
  await expect(reconcileSignInWallet(args)).rejects.toThrow('RECONCILE-BACKUP-REPORT');
  expect(wallet.clearPendingBackupReport).not.toHaveBeenCalled();
  wallet.hasPendingBackupReport.mockResolvedValueOnce(true);
  args.getGoogleDriveToken.mockClear();
  expect(await reconcileSignInWallet(args)).toBe(false);
  expect(args.getGoogleDriveToken).not.toHaveBeenCalled();
  expect(args.client.mutate).toHaveBeenCalledTimes(4);
  expect(wallet.clearPendingBackupReport).toHaveBeenCalledTimes(1);
  expect((args.authData as any).requiresBackupCompletion).toBe(false);
});
