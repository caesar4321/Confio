jest.mock('../secureDeterministicWallet', () => ({
  getSignInWalletCandidate: jest.fn(),
  clearReconciledLegacyWallets: jest.fn(),
  reportBackupStatus: jest.fn(),
}));
import { getSignInWalletCandidate, clearReconciledLegacyWallets, reportBackupStatus } from '../secureDeterministicWallet';
import { reconcileSignInWallet, walletAccountChallenge } from '../signInWalletReconciliation';
import { WalletRecoveryError } from '../walletRecoveryErrors';

const key = (row: any) => `${row.accountType}:${row.accountIndex}:${row.businessId || ''}`;
function candidate() {
  const wallets = new Map([
    ['personal:0:', { algorandAddress: 'algo-primary', bscAddress: '0xprimary' }],
    ['personal:1:', { algorandAddress: 'algo-secondary', bscAddress: '0xsecondary' }],
    ['business:2:42', { algorandAddress: 'algo-business', bscAddress: '0xbusiness' }],
  ].map(([context, addresses]) => [context, {
    ...(addresses as object),
    sign: jest.fn((message: string) => `signature:${context}:${message}`),
    publish: jest.fn().mockResolvedValue(undefined),
  }])) as Map<string, any>;
  let pending = false;
  return {
    ...wallets.get('personal:0:'), wallets,
    forAccount: jest.fn((row: any) => wallets.get(key(row))),
    persist: jest.fn(async () => { pending = true; }),
    hasPendingBackupReport: jest.fn(async () => pending),
    clearPendingBackupReport: jest.fn(async () => { pending = false; }),
  };
}
type TestRegistration = {
  accountId: string; accountType: string; accountIndex: number; businessId: string | null;
  algorandAddress: string | null; bscAddress: string | null; isKeylessMigrated: boolean;
};
const inventory = (): TestRegistration[] => [
  { accountId: '1', accountType: 'personal', accountIndex: 0, businessId: null,
    algorandAddress: null, bscAddress: '0xprimary', isKeylessMigrated: true },
  { accountId: '2', accountType: 'personal', accountIndex: 1, businessId: null,
    algorandAddress: null, bscAddress: '0xsecondary', isKeylessMigrated: true },
  { accountId: '3', accountType: 'business', accountIndex: 2, businessId: '42',
    algorandAddress: 'old-business-algo', bscAddress: '0xoldbusiness', isKeylessMigrated: false },
];
function fixture(provider: 'google' | 'apple' = 'google') {
  const wallet = candidate();
  const state = { accounts: inventory(), loseCommitResponse: false,
    transformCompletion: (rows: any[]) => rows };
  const args = {
    provider, subject: 'subject', firebaseToken: 'identity',
    authData: { user: { algorandAddress: null, bscAddress: '0xprimary' },
      accessToken: 'session', isNewUser: false, isKeylessMigrated: true, requiresBackupCompletion: false },
    client: { mutate: jest.fn() },
    beforeWalletChange: jest.fn().mockResolvedValue(undefined),
    getGoogleDriveToken: jest.fn().mockResolvedValue('drive'),
  };
  args.client.mutate.mockImplementation(async ({ variables }) => {
    if ('firebaseIdToken' in variables) {
      return { data: { prepareWalletReconciliation: { success: true, grant: 'grant', challenge: 'challenge',
        accounts: state.accounts.map(row => ({ ...row })) } } };
    }
    state.accounts = state.accounts.map(row => ({ ...row, algorandAddress: null,
      bscAddress: wallet.forAccount(row).bscAddress, isKeylessMigrated: true }));
    if (state.loseCommitResponse) throw new Error('Lost completion response');
    return { data: { completeWalletReconciliation: { success: true, bscAddress: wallet.bscAddress,
      accounts: state.transformCompletion(state.accounts.map(row => ({ ...row }))) } } };
  });
  (getSignInWalletCandidate as jest.Mock).mockResolvedValue(wallet);
  return { args, wallet, state };
}
beforeEach(() => {
  jest.resetAllMocks();
  (reportBackupStatus as jest.Mock).mockResolvedValue(true);
  (clearReconciledLegacyWallets as jest.Mock).mockResolvedValue(undefined);
});

it('detects a business-only mismatch even when primary and secondary personal already match', async () => {
  const { args, wallet } = fixture();
  expect(await reconcileSignInWallet(args)).toBe(true);
  expect(args.client.mutate).toHaveBeenCalledTimes(3);
  expect(args.getGoogleDriveToken).toHaveBeenCalledTimes(1);
  const proof = args.client.mutate.mock.calls[2][0].variables;
  expect(proof.wallets.map((row: any) => row.bscAddress)).toEqual(['0xprimary', '0xsecondary', '0xbusiness']);
  expect(proof.wallets[2].signature).toBe(`signature:business:2:42:${walletAccountChallenge('challenge', '3', '0xbusiness')}`);
  expect(wallet.wallets.get('business:2:42').publish).toHaveBeenCalledTimes(1);
  expect(wallet.wallets.get('personal:1:').publish).toHaveBeenCalledTimes(1);
  expect(wallet.publish.mock.invocationCallOrder[0]).toBeGreaterThan(wallet.wallets.get('business:2:42').publish.mock.invocationCallOrder[0]);
  expect(clearReconciledLegacyWallets).toHaveBeenCalledTimes(1);
});

it('keeps Apple sibling reconciliation inside Keychain with no Drive authorization', async () => {
  const { args } = fixture('apple');
  expect(await reconcileSignInWallet(args)).toBe(true);
  expect(args.getGoogleDriveToken).not.toHaveBeenCalled();
});

it('does not treat a blank primary as a new user when a sibling has a conflicting wallet', async () => {
  const { args, state } = fixture();
  state.accounts[0].bscAddress = null as any;
  args.authData.user.bscAddress = null as any;
  expect(await reconcileSignInWallet(args)).toBe(true);
  expect(args.authData.user.bscAddress).toBe('0xprimary');
  expect(args.client.mutate.mock.calls[2][0].variables.wallets).toHaveLength(3);
});

it('registers a blank primary atomically even when every known sibling already matches', async () => {
  const { args, state } = fixture();
  state.accounts[0].bscAddress = null as any;
  args.authData.user.bscAddress = null as any;
  state.accounts[2].algorandAddress = null as any;
  state.accounts[2].bscAddress = '0xbusiness';
  state.accounts[2].isKeylessMigrated = true;
  expect(await reconcileSignInWallet(args)).toBe(true);
  expect(args.authData.user.bscAddress).toBe('0xprimary');
  expect(args.client.mutate.mock.calls[2][0].variables.wallets).toHaveLength(3);
});

it.each(['missing', 'wrong-address', 'wrong-context', 'still-algorand'])('rejects an incomplete commit response (%s) before publishing any account', async failure => {
  const { args, wallet, state } = fixture();
  state.transformCompletion = rows => {
    if (failure === 'missing') return rows.slice(0, 2);
    if (failure === 'wrong-address') rows[2].bscAddress = '0xother';
    if (failure === 'wrong-context') rows[2].accountIndex = 1;
    if (failure === 'still-algorand') rows[2].algorandAddress = 'old-business-algo';
    return rows;
  };
  await expect(reconcileSignInWallet(args)).rejects.toThrow('RECONCILE-COMMIT');
  for (const context of wallet.wallets.values()) expect(context.publish).not.toHaveBeenCalled();
  expect(clearReconciledLegacyWallets).not.toHaveBeenCalled();
});

it('retries a lost commit response using current inventory and a matching backup receipt', async () => {
  const { args, wallet, state } = fixture();
  args.authData.requiresBackupCompletion = true;
  state.loseCommitResponse = true;
  await expect(reconcileSignInWallet(args)).rejects.toThrow('Lost completion response');
  expect(wallet.publish).not.toHaveBeenCalled();
  args.getGoogleDriveToken.mockClear();
  state.loseCommitResponse = false;
  expect(await reconcileSignInWallet(args)).toBe(false);
  expect(args.getGoogleDriveToken).not.toHaveBeenCalled();
  expect(args.client.mutate).toHaveBeenCalledTimes(4);
  expect(args.authData.requiresBackupCompletion).toBe(false);
  expect(clearReconciledLegacyWallets).toHaveBeenCalledTimes(1);
  expect(wallet.persist).toHaveBeenCalledTimes(1);
});

it('publishes no stale legacy cleanup until every returned account is migrated', async () => {
  const { args, state } = fixture();
  state.accounts[2].algorandAddress = 'algo-business';
  state.accounts[2].bscAddress = '0xbusiness';
  expect(await reconcileSignInWallet(args)).toBe(false);
  expect(clearReconciledLegacyWallets).not.toHaveBeenCalled();
  expect(args.beforeWalletChange).not.toHaveBeenCalled();
});

it('refreshes a stale login primary from the newer verified inventory on a lost-response retry', async () => {
  const { args, state } = fixture();
  state.accounts[0].bscAddress = '0xoldprimary';
  args.authData.user.bscAddress = '0xoldprimary';
  state.loseCommitResponse = true;
  await expect(reconcileSignInWallet(args)).rejects.toThrow('Lost completion response');
  state.loseCommitResponse = false;
  await reconcileSignInWallet(args);
  expect(args.authData.user.bscAddress).toBe('0xprimary');
});

it('checks every owned V1 anchor before Drive authorization and preserves matching legacy login', async () => {
  const { args, state } = fixture();
  (args.authData as any).walletReenrollmentAllowed = true;
  state.accounts = state.accounts.map(row => ({ ...row, bscAddress: null as any,
    algorandAddress: `legacy-${row.accountId}`, isKeylessMigrated: false }));
  (getSignInWalletCandidate as jest.Mock).mockResolvedValueOnce(null);
  const getLegacyV1Address = jest.fn(async (row: any) => `legacy-${row.accountId}`);
  expect(await reconcileSignInWallet({ ...args, getLegacyV1Address })).toBe(false);
  expect(getLegacyV1Address).toHaveBeenCalledTimes(3);
  expect(getLegacyV1Address.mock.calls.map(([row]) => row.accountId)).toEqual(['1', '2', '3']);
  expect(args.getGoogleDriveToken).not.toHaveBeenCalled();
  expect(args.beforeWalletChange).not.toHaveBeenCalled();
  expect(args.authData.user.algorandAddress).toBe('legacy-1');
  expect((args.authData as any).walletReenrollmentAllowed).toBe(false);
});

it('revokes primary-only reenrollment even when every owned wallet is empty', async () => {
  const { args, state } = fixture();
  (args.authData as any).walletReenrollmentAllowed = true;
  state.accounts = state.accounts.map(row => ({ ...row, bscAddress: null as any, algorandAddress: null }));
  expect(await reconcileSignInWallet(args)).toBe(false);
  expect((args.authData as any).walletReenrollmentAllowed).toBe(false);
  expect(args.getGoogleDriveToken).not.toHaveBeenCalled();
});

it('continues to canonical Drive recovery when one owned V1 account fails the anchor probe', async () => {
  const { args, state } = fixture();
  state.accounts = state.accounts.map(row => ({ ...row, bscAddress: null as any,
    algorandAddress: `legacy-${row.accountId}`, isKeylessMigrated: false }));
  (getSignInWalletCandidate as jest.Mock).mockResolvedValueOnce(null);
  const getLegacyV1Address = jest.fn(async (row: any) => row.accountId === '3' ? 'wrong' : `legacy-${row.accountId}`);
  expect(await reconcileSignInWallet({ ...args, getLegacyV1Address })).toBe(true);
  expect(args.getGoogleDriveToken).toHaveBeenCalledTimes(1);
});

it('allows matching V1 login with an unregistered unmigrated sibling without Drive', async () => {
  const { args, state } = fixture();
  state.accounts = state.accounts.map(row => ({ ...row, bscAddress: null as any,
    algorandAddress: row.accountId === '1' ? 'legacy-primary' : null, isKeylessMigrated: false }));
  (args.authData as any).walletReenrollmentAllowed = true;
  (getSignInWalletCandidate as jest.Mock).mockResolvedValueOnce(null);
  const getLegacyV1Address = jest.fn(async () => 'legacy-primary');
  expect(await reconcileSignInWallet({ ...args, getLegacyV1Address })).toBe(false);
  expect(getLegacyV1Address).toHaveBeenCalledTimes(1);
  expect(getLegacyV1Address).toHaveBeenCalledWith(expect.objectContaining({ accountId: '1' }));
  expect(args.getGoogleDriveToken).not.toHaveBeenCalled();
  expect((args.authData as any).walletReenrollmentAllowed).toBe(false);
});

it('does not treat an empty migrated sibling as an unregistered V1 context', async () => {
  const { args, state } = fixture();
  state.accounts = state.accounts.map(row => ({ ...row, bscAddress: null as any,
    algorandAddress: row.accountId === '1' ? 'legacy-primary' : null,
    isKeylessMigrated: row.accountId === '3' }));
  (getSignInWalletCandidate as jest.Mock).mockResolvedValueOnce(null);
  const getLegacyV1Address = jest.fn(async () => 'legacy-primary');
  expect(await reconcileSignInWallet({ ...args, getLegacyV1Address })).toBe(true);
  expect(getLegacyV1Address).not.toHaveBeenCalled();
  expect(args.getGoogleDriveToken).toHaveBeenCalledTimes(1);
});

it('does not use the V1 shortcut for corrupt local V2 storage', async () => {
  const { args, state } = fixture();
  state.accounts = state.accounts.map(row => ({ ...row, bscAddress: null as any,
    algorandAddress: `legacy-${row.accountId}`, isKeylessMigrated: false }));
  (getSignInWalletCandidate as jest.Mock).mockRejectedValueOnce(Object.assign(new Error('corrupt'), { name: 'CorruptMasterSecretError' }));
  const getLegacyV1Address = jest.fn();
  expect(await reconcileSignInWallet({ ...args, getLegacyV1Address })).toBe(true);
  expect(getLegacyV1Address).not.toHaveBeenCalled();
  expect(args.getGoogleDriveToken).toHaveBeenCalledTimes(1);
});

it('never falls back to V1 when corrupt local V2 material has no canonical or legacy backup', async () => {
  const { args, state, wallet } = fixture();
  state.accounts = state.accounts.map(row => ({ ...row, bscAddress: null as any,
    algorandAddress: `legacy-${row.accountId}`, isKeylessMigrated: false }));
  (getSignInWalletCandidate as jest.Mock)
    .mockRejectedValueOnce(Object.assign(new Error('corrupt'), { name: 'CorruptMasterSecretError' }))
    .mockRejectedValueOnce(new WalletRecoveryError('missing'))
    .mockRejectedValueOnce(new WalletRecoveryError('missing'));
  const getLegacyV1Address = jest.fn();
  await expect(reconcileSignInWallet({ ...args, getLegacyV1Address })).rejects.toMatchObject({ code: 'missing' });
  expect(getLegacyV1Address).not.toHaveBeenCalled();
  expect(wallet.persist).not.toHaveBeenCalled();
  expect(args.beforeWalletChange).not.toHaveBeenCalled();
  expect(args.client.mutate).toHaveBeenCalledTimes(1);
});

it('restores matching legacy-format backup only after canonical absence without reconciling', async () => {
  const { args, state, wallet } = fixture();
  state.accounts = state.accounts.map(row => ({ ...row, algorandAddress: null,
    bscAddress: wallet.forAccount(row).bscAddress, isKeylessMigrated: true }));
  (getSignInWalletCandidate as jest.Mock).mockResolvedValueOnce(null)
    .mockRejectedValueOnce(new WalletRecoveryError('missing')).mockResolvedValueOnce(wallet);
  expect(await reconcileSignInWallet(args)).toBe(false);
  expect(getSignInWalletCandidate).toHaveBeenLastCalledWith('subject', 'drive', { legacyRegistrations: state.accounts });
  expect(wallet.persist).toHaveBeenCalledTimes(1);
  expect(args.beforeWalletChange).not.toHaveBeenCalled();
  expect(args.client.mutate).toHaveBeenCalledTimes(1);
});

it('never reconciles a mismatching legacy-format backup', async () => {
  const { args, wallet } = fixture();
  (getSignInWalletCandidate as jest.Mock).mockResolvedValueOnce(null)
    .mockRejectedValueOnce(new WalletRecoveryError('missing')).mockRejectedValueOnce(new WalletRecoveryError('mismatch'));
  await expect(reconcileSignInWallet(args)).rejects.toMatchObject({ code: 'mismatch' });
  expect(wallet.persist).not.toHaveBeenCalled();
  expect(args.beforeWalletChange).not.toHaveBeenCalled();
  expect(args.client.mutate).toHaveBeenCalledTimes(1);
});
