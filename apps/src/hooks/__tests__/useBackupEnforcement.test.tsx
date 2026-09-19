import React from 'react';
import renderer, { act } from 'react-test-renderer';
import { Alert, Platform } from 'react-native';
import { useBackupEnforcement } from '../useBackupEnforcement';
import { BackupConsentModal } from '../../components/BackupConsentModal';

const mockQuery = jest.fn();
const mockContext = jest.fn();
const mockEvmWallet = jest.fn();
const mockAlgoWallet = jest.fn();
const mockMigration = jest.fn();
const mockEnableBackup = jest.fn();
const mockOAuth = jest.fn();
let mockProfile: any;

jest.mock('@apollo/client', () => ({
  gql: jest.requireActual('@apollo/client').gql,
  useApolloClient: () => ({ query: mockQuery }),
  useQuery: () => ({ data: {} }),
}));
jest.mock('../../apollo/queries', () => ({ GET_MY_BALANCES: 'balances', GET_MY_MIGRATION_STATUS: 'migration' }));
jest.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ userProfile: mockProfile, refreshProfile: jest.fn() }) }));
jest.mock('../../services/authService', () => ({
  __esModule: true,
  default: { getActiveAccountContext: (...args: any[]) => mockContext(...args) },
  AuthService: { getInstance: () => ({ enableDriveBackup: mockEnableBackup }) },
}));
jest.mock('../../services/secureDeterministicWallet', () => ({
  getActiveEvmWallet: (...args: any[]) => mockEvmWallet(...args),
  secureDeterministicWallet: { createOrRestoreWallet: (...args: any[]) => mockAlgoWallet(...args) },
}));
jest.mock('../../services/migrationService', () => ({ migrationService: { checkNeedsMigration: (...args: any[]) => mockMigration(...args) } }));
jest.mock('../../services/oauthStorageService', () => ({ oauthStorage: { getOAuthSubject: (...args: any[]) => mockOAuth(...args) } }));
jest.mock('../../services/analyticsService', () => ({ AnalyticsService: { logBackupAttempt: jest.fn() } }));
jest.mock('../../config/env', () => ({ GOOGLE_CLIENT_IDS: { development: { web: 'web' }, production: { web: 'web' } } }));
jest.mock('../../components/BackupConsentModal', () => ({ BackupConsentModal: () => null }));
jest.mock('../../components/DriveStorageFullModal', () => ({ DriveStorageFullModal: () => null }));

const ADDRESS = '0x' + 'ab'.repeat(20);
const PERSONAL = { type: 'personal', index: 0 };
let tree: renderer.ReactTestRenderer;
const mount = () => {
  let api!: ReturnType<typeof useBackupEnforcement>;
  const Probe = () => {
    api = useBackupEnforcement();
    return <api.BackupEnforcementModal />;
  };
  act(() => { tree = renderer.create(<Probe />); });
  return () => api;
};

beforeEach(() => {
  jest.resetAllMocks();
  jest.useFakeTimers();
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'android' });
  jest.spyOn(Alert, 'alert').mockImplementation(() => {});
  jest.spyOn(console, 'error').mockImplementation(() => {});
  mockProfile = { backupProvider: 'google_drive' };
  mockContext.mockResolvedValue(PERSONAL);
  mockOAuth.mockResolvedValue({ subject: 'subject', provider: 'google' });
  mockEvmWallet.mockResolvedValue({ address: ADDRESS });
  mockQuery.mockResolvedValue({ data: { stockWalletAddress: ADDRESS.toUpperCase().replace('0X', '0x') } });
  mockMigration.mockResolvedValue({ needsMigration: false });
  mockEnableBackup.mockResolvedValue({ success: true });
});
afterEach(() => {
  act(() => { tree?.unmount(); jest.runOnlyPendingTimers(); });
  jest.useRealTimers();
  jest.restoreAllMocks();
});

it('allows BSC deposits with a matching key and no active Algorand registration', async () => {
  const api = mount();
  await expect(api().checkBackupEnforcement('bsc_deposit')).resolves.toBe(true);
  expect(mockEvmWallet).toHaveBeenCalledWith(PERSONAL);
  expect(mockMigration).not.toHaveBeenCalled();
  expect(mockAlgoWallet).not.toHaveBeenCalled();
  expect(mockQuery).toHaveBeenCalledWith(expect.objectContaining({ fetchPolicy: 'no-cache', errorPolicy: 'none' }));
  expect(Alert.alert).not.toHaveBeenCalled();
});

it('verifies BSC ownership on iOS too', async () => {
  Object.defineProperty(Platform, 'OS', { configurable: true, value: 'ios' });
  mockProfile = {};
  const api = mount();
  await expect(api().checkBackupEnforcement('bsc_deposit')).resolves.toBe(true);
  expect(mockEvmWallet).toHaveBeenCalled();
});

it('blocks a mismatched BSC signing wallet', async () => {
  mockEvmWallet.mockResolvedValue({ address: '0x' + 'cd'.repeat(20) });
  const api = mount();
  await expect(api().checkBackupEnforcement('bsc_deposit')).resolves.toBe(false);
  expect(Alert.alert).toHaveBeenCalledWith('Billetera no sincronizada', expect.any(String));
});

it.each([null, undefined, '', 'invalid', '0x' + '0'.repeat(40)])('blocks an unavailable or invalid BSC registration: %s', async address => {
  mockQuery.mockResolvedValue({ data: { stockWalletAddress: address } });
  const api = mount();
  await expect(api().checkBackupEnforcement('bsc_deposit')).resolves.toBe(false);
  expect(Alert.alert).toHaveBeenCalledWith('No pudimos verificar tu billetera', expect.any(String));
});

it('blocks a failed server query', async () => {
  mockQuery.mockRejectedValue(new Error('Unavailable'));
  const api = mount();
  await expect(api().checkBackupEnforcement('bsc_deposit')).resolves.toBe(false);
});

it('blocks a missing or unreadable local signing secret', async () => {
  mockEvmWallet.mockRejectedValue(new Error('No secret'));
  const api = mount();
  await expect(api().checkBackupEnforcement('bsc_deposit')).resolves.toBe(false);
  expect(mockQuery).not.toHaveBeenCalled();
});

it('blocks an account switch during verification', async () => {
  mockContext.mockResolvedValueOnce(PERSONAL).mockResolvedValue({ type: 'business', index: 0, businessId: '1' });
  const api = mount();
  await expect(api().checkBackupEnforcement('bsc_deposit')).resolves.toBe(false);
});

it('derives the captured business context instead of using the personal wallet', async () => {
  const business = { type: 'business', index: 0, businessId: '2' };
  mockContext.mockResolvedValue(business);
  const api = mount();
  await expect(api().checkBackupEnforcement('bsc_deposit')).resolves.toBe(true);
  expect(mockEvmWallet).toHaveBeenCalledWith(business);
});

it('requires Android backup completion before verifying and allowing BSC funds', async () => {
  mockProfile = {};
  const api = mount();
  let pending!: Promise<boolean>;
  act(() => { pending = api().checkBackupEnforcement('bsc_deposit'); });
  expect(mockEvmWallet).not.toHaveBeenCalled();
  expect(tree.root.findByType(BackupConsentModal).props.visible).toBe(true);
  await act(async () => { await tree.root.findByType(BackupConsentModal).props.onContinue(); });
  await expect(pending).resolves.toBe(true);
  expect(mockEnableBackup).toHaveBeenCalled();
  expect(mockEvmWallet).toHaveBeenCalled();
});

it('does not allow a deposit when backup fails', async () => {
  mockProfile = {};
  mockEnableBackup.mockResolvedValue({ success: false });
  const api = mount();
  let pending!: Promise<boolean>;
  act(() => { pending = api().checkBackupEnforcement('bsc_deposit'); });
  await act(async () => { await tree.root.findByType(BackupConsentModal).props.onContinue(); });
  await expect(pending).resolves.toBe(false);
  expect(mockEvmWallet).not.toHaveBeenCalled();
});

it.each(['deposit', 'presale'] as const)('preserves Algorand wallet verification for %s', async action => {
  mockQuery.mockResolvedValue({ data: { userAccounts: [{ accountType: 'personal', accountIndex: 0, algorandAddress: 'ALGO' }] } });
  mockAlgoWallet.mockResolvedValue({ address: 'ALGO' });
  const api = mount();
  let result: boolean | undefined;
  await act(async () => { result = await api().checkBackupEnforcement(action); });
  expect(result).toBe(true);
  expect(mockMigration).toHaveBeenCalled();
  expect(mockAlgoWallet).toHaveBeenCalled();
  expect(mockEvmWallet).not.toHaveBeenCalled();
});

// Both users have personal/0: account shape alone cannot identify a session.
it('rejects a previous user wallet response after the signed-in identity changes', async () => {
  mockQuery.mockImplementation(async () => {
    mockOAuth.mockResolvedValue({ subject: 'other-user', provider: 'google' });
    return { data: { stockWalletAddress: ADDRESS } };
  });
  const api = mount();
  await expect(api().checkBackupEnforcement('bsc_deposit')).resolves.toBe(false);
});

it('rejects a wallet response after sign-out clears the identity', async () => {
  mockQuery.mockImplementation(async () => {
    mockOAuth.mockResolvedValue(null);
    return { data: { stockWalletAddress: ADDRESS } };
  });
  const api = mount();
  await expect(api().checkBackupEnforcement('bsc_deposit')).resolves.toBe(false);
});

it('does not approve a delayed response after the screen unmounts', async () => {
  mockQuery.mockImplementation(async () => {
    act(() => { tree.unmount(); });
    return { data: { stockWalletAddress: ADDRESS } };
  });
  const api = mount();
  await expect(api().checkBackupEnforcement('bsc_deposit')).resolves.toBe(false);
});

it('explains a missing signing identity without querying a wallet', async () => {
  mockOAuth.mockResolvedValue(null);
  const api = mount();
  await expect(api().checkBackupEnforcement('bsc_deposit')).resolves.toBe(false);
  expect(mockEvmWallet).not.toHaveBeenCalled();
  expect(mockQuery).not.toHaveBeenCalled();
  expect(Alert.alert).toHaveBeenCalledWith('No pudimos verificar tu billetera', expect.any(String));
});

it('does not show an old request failure after the screen unmounts', async () => {
  mockQuery.mockImplementation(async () => {
    act(() => { tree.unmount(); });
    throw new Error('Offline');
  });
  const api = mount();
  await expect(api().checkBackupEnforcement('bsc_deposit')).resolves.toBe(false);
  expect(Alert.alert).not.toHaveBeenCalled();
});
