/**
 * Regression tests for the Drive backup sync contract of getOrCreateMasterSecret.
 *
 * Incident (user 10090, 2026-07-02): enableDriveBackup() called
 * getOrCreateMasterSecret with requireCloudSync: true, but the verified-local
 * fast path returned before Section 4 (CLOUD SYNC), so no file was ever
 * uploaded to Drive while the server was told "backup verified". When the
 * device Keystore was wiped (first-time screen-lock enrollment on MIUI), the
 * user was permanently locked out: existing account + no local secret + empty
 * Drive.
 */
import { sha256 } from '@noble/hashes/sha256';
import { utf8ToBytes, bytesToHex } from '@noble/hashes/utils';

const mockMemoryStore = new Map<string, Uint8Array>();

jest.mock('react-native-keychain', () => ({
  setGenericPassword: jest.fn(),
  getGenericPassword: jest.fn().mockResolvedValue(false),
  resetGenericPassword: jest.fn(),
  getInternetCredentials: jest.fn().mockResolvedValue(false),
  setInternetCredentials: jest.fn(),
  ACCESSIBLE: { AFTER_FIRST_UNLOCK: 'AfterFirstUnlock' },
}));

jest.mock('react-native-device-info', () => ({
  getDeviceName: jest.fn().mockResolvedValue('Test Device'),
}));

jest.mock('../../apollo/client', () => ({
  apolloClient: {
    mutate: jest.fn().mockResolvedValue({ data: {} }),
    query: jest.fn().mockResolvedValue({ data: {} }),
  },
  AUTH_KEYCHAIN_SERVICE: 'test_auth_service',
  AUTH_KEYCHAIN_USERNAME: 'test_auth_user',
}));

jest.mock('../../apollo/queries', () => ({
  REPORT_BACKUP_STATUS: {},
}));

jest.mock('../analyticsService', () => ({
  AnalyticsService: {
    logBackupAttempt: jest.fn(),
    logBackupFailed: jest.fn(),
  },
}));

jest.mock('../../utils/keychainInternetCredentials', () => ({
  softClearInternetCredentials: jest.fn(),
}));

jest.mock('../credentialStorage', () => ({
  credentialStorage: {
    storeSecret: jest.fn(async (key: string, secret: Uint8Array) => {
      mockMemoryStore.set(key, secret);
    }),
    retrieveSecret: jest.fn(async (key: string) => mockMemoryStore.get(key) ?? null),
    deleteSecret: jest.fn(async (key: string) => {
      mockMemoryStore.delete(key);
    }),
  },
}));

jest.mock('../googleDriveStorage', () => ({
  googleDriveStorage: {
    listFiles: jest.fn().mockResolvedValue([]),
    listRevisions: jest.fn().mockResolvedValue([]),
    downloadFile: jest.fn().mockRejectedValue(new Error('no files in test Drive')),
    createFile: jest.fn().mockResolvedValue({ id: 'new-file-id' }),
    updateFile: jest.fn().mockResolvedValue({ id: 'updated-file-id' }),
  },
}));

import { getOrCreateMasterSecret, deriveWalletV2 } from '../secureDeterministicWallet';
import { googleDriveStorage } from '../googleDriveStorage';

const USER_SUB = '111222333444555666777';
const MASTER_SECRET = new Uint8Array(32).fill(7);

const subjectAlias = () =>
  `confio_master_secret_v2_${bytesToHex(sha256(utf8ToBytes(USER_SUB)))}`;
const walletIdAlias = () =>
  `confio_wallet_id_v2_${bytesToHex(sha256(utf8ToBytes(USER_SUB)))}`;

const expectedAddress = deriveWalletV2(MASTER_SECRET, {
  accountType: 'personal',
  accountIndex: 0,
}).address;

const seedLocalVerifiedSecret = () => {
  mockMemoryStore.set(subjectAlias(), MASTER_SECRET);
  mockMemoryStore.set(
    walletIdAlias(),
    new TextEncoder().encode('11111111-2222-4333-8444-555555555555')
  );
};

const encBackupUploads = () =>
  (googleDriveStorage.createFile as jest.Mock).mock.calls.filter(([, name]) =>
    /^confio_wallet_v2_.+\.enc$/.test(name)
  );

describe('getOrCreateMasterSecret Drive backup sync contract', () => {
  beforeEach(() => {
    mockMemoryStore.clear();
    jest.clearAllMocks();
  });

  it('uploads the backup when requireCloudSync is set, even if the local secret already matches the server address', async () => {
    seedLocalVerifiedSecret();
    const onCloudSyncResult = jest.fn();

    const secret = await getOrCreateMasterSecret(USER_SUB, 'drive-token', {
      provider: 'google',
      requireCloudSync: true,
      expectedAddress,
      onCloudSyncResult,
    });

    expect(secret).toEqual(MASTER_SECRET);
    // The whole incident: this upload never happened while the server was
    // told the backup was verified.
    expect(encBackupUploads()).toHaveLength(1);
    expect(onCloudSyncResult).toHaveBeenCalledWith(true);
  });

  it('keeps the login fast path (no Drive calls) when cloud sync is not required', async () => {
    seedLocalVerifiedSecret();
    const onCloudSyncResult = jest.fn();

    const secret = await getOrCreateMasterSecret(USER_SUB, 'drive-token', {
      provider: 'google',
      expectedAddress,
      onCloudSyncResult,
    });

    expect(secret).toEqual(MASTER_SECRET);
    expect(googleDriveStorage.listFiles).not.toHaveBeenCalled();
    expect(googleDriveStorage.createFile).not.toHaveBeenCalled();
    // No sync happened, so no sync result may be reported.
    expect(onCloudSyncResult).not.toHaveBeenCalled();
  });

  it('reports onCloudSyncResult(false) when the sign-up backup upload fails silently', async () => {
    (googleDriveStorage.createFile as jest.Mock).mockRejectedValue(
      new Error('Drive write failed')
    );
    const onCloudSyncResult = jest.fn();

    // New-user sign-up shape: nothing stored locally, generation allowed,
    // sync failures tolerated (requireCloudSync unset).
    const secret = await getOrCreateMasterSecret(USER_SUB, 'drive-token', {
      provider: 'google',
      allowGenerate: true,
      onCloudSyncResult,
    });

    expect(secret).toBeInstanceOf(Uint8Array);
    expect(onCloudSyncResult).toHaveBeenCalledWith(false);
    expect(onCloudSyncResult).not.toHaveBeenCalledWith(true);
  });
});
