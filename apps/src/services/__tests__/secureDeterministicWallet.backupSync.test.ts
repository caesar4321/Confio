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
import * as Keychain from 'react-native-keychain';

const mockMemoryStore = new Map<string, Uint8Array>();

jest.mock('react-native-keychain', () => ({
  setGenericPassword: jest.fn().mockResolvedValue(true),
  getGenericPassword: jest.fn().mockResolvedValue(false),
  resetGenericPassword: jest.fn().mockResolvedValue(true),
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
    logBackupSuccess: jest.fn(),
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
    // Mirrors the real contract: absent -> null, present -> bytes. The strict
    // variant differs only in how it reports read failure and malformed
    // encoding, neither of which this byte-level mock can produce.
    retrieveSecretStrict: jest.fn(async (key: string) => mockMemoryStore.get(key) ?? null),
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

import {
  getOrCreateMasterSecret,
  deriveV2AddressPure,
  deriveWalletV2,
  getDerivedEvmWallet,
  getDerivedSolanaWallet,
  getEvmAddressForDisplay,
  getSolanaAddressForDisplay,
  secureDeterministicWallet,
} from '../secureDeterministicWallet';
import { deriveEvmKeyFromMasterSecret } from '../evmWallet';
import { deriveSolanaKeyFromMasterSecret } from '../solanaWallet';
import { googleDriveStorage } from '../googleDriveStorage';

const USER_SUB = '111222333444555666777';
const MASTER_SECRET = new Uint8Array(32).fill(7);

const subjectAlias = () =>
  `confio_master_secret_v2_${bytesToHex(sha256(utf8ToBytes(USER_SUB)))}`;
const walletIdAlias = () =>
  `confio_wallet_id_v2_${bytesToHex(sha256(utf8ToBytes(USER_SUB)))}`;

const expectedAddress = deriveV2AddressPure(MASTER_SECRET, {
  accountType: 'personal',
  accountIndex: 0,
});
const expectedSolanaAddress = deriveSolanaKeyFromMasterSecret(MASTER_SECRET, {
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
    (Keychain.setGenericPassword as jest.Mock).mockResolvedValue(true);
    (Keychain.getGenericPassword as jest.Mock).mockResolvedValue(false);
    (Keychain.resetGenericPassword as jest.Mock).mockResolvedValue(true);
  });

  it('clears sibling signer and address caches on sign-out', async () => {
    deriveWalletV2(
      MASTER_SECRET,
      { accountType: 'personal', accountIndex: 0 },
      {},
    );
    expect(getDerivedEvmWallet()).not.toBeNull();
    expect(getDerivedSolanaWallet()).not.toBeNull();

    await secureDeterministicWallet.clearWallet();

    expect(getDerivedEvmWallet()).toBeNull();
    expect(getDerivedSolanaWallet()).toBeNull();
    await expect(getEvmAddressForDisplay('personal_0')).resolves.toBeNull();
    await expect(getSolanaAddressForDisplay('personal_0')).resolves.toBeNull();
  });

  it('clears address services restored from the persistent registry after restart', async () => {
    const coldStartService = 'confio_solana_address_v1_business_987_0';
    (Keychain.getGenericPassword as jest.Mock).mockImplementation(async ({ service }) =>
      service === 'confio_wallet_address_service_registry_v1'
        ? { username: 'address_services', password: JSON.stringify([coldStartService]) }
        : false,
    );

    await secureDeterministicWallet.clearWallet();

    expect(Keychain.resetGenericPassword).toHaveBeenCalledWith({ service: coldStartService });
    expect(Keychain.resetGenericPassword).toHaveBeenCalledWith({
      service: 'confio_wallet_address_service_registry_v1',
    });
  });

  it('prevents a stale persistence operation from recreating caches during sign-out', async () => {
    let releaseRegistryRead!: (value: false) => void;
    const blockedRegistryRead = new Promise<false>(resolve => {
      releaseRegistryRead = resolve;
    });
    let registryReads = 0;
    (Keychain.getGenericPassword as jest.Mock).mockImplementation(async ({ service }) => {
      if (
        service === 'confio_wallet_address_service_registry_v1' &&
        registryReads++ === 0
      ) {
        return blockedRegistryRead;
      }
      return false;
    });

    deriveWalletV2(
      MASTER_SECRET,
      { accountType: 'personal', accountIndex: 0 },
      {},
    );
    await Promise.resolve();
    const clearing = secureDeterministicWallet.clearWallet();
    deriveWalletV2(
      MASTER_SECRET,
      { accountType: 'personal', accountIndex: 0 },
      {},
    );

    expect(getDerivedEvmWallet()).toBeNull();
    expect(getDerivedSolanaWallet()).toBeNull();
    releaseRegistryRead(false);
    await clearing;

    expect(getDerivedEvmWallet()).toBeNull();
    expect(getDerivedSolanaWallet()).toBeNull();
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

  // A corrupted local secret is NOT an absent one. If it were treated as
  // absent, generation would mint a replacement and overwrite the alias —
  // trading a weak-key bug for permanent loss of a funded wallet. Corruption
  // still lets the Drive scan run (that is the only thing that can repair the
  // alias); it is generation that must be refused when the scan finds nothing.
  it('refuses to generate a replacement when the stored secret is corrupted', async () => {
    mockMemoryStore.set(subjectAlias(), new Uint8Array([1, 2, 3, 4]));

    await expect(
      getOrCreateMasterSecret(USER_SUB, 'drive-token', {
        provider: 'google',
        allowGenerate: true,
      })
    ).rejects.toThrow(/dañados/i);

    // The damaged value must still be there: no silent overwrite.
    expect(mockMemoryStore.get(subjectAlias())).toEqual(new Uint8Array([1, 2, 3, 4]));
    expect(encBackupUploads()).toHaveLength(0);
  });

  // The repair path: same corrupt local alias, but Drive holds a valid backup
  // that derives to the server's address. Corruption must not block this.
  it('repairs a corrupted local secret from an address-anchored Drive backup', async () => {
    mockMemoryStore.set(subjectAlias(), new Uint8Array([1, 2, 3, 4]));

    const AES = require('crypto-js/aes');
    const Utf8 = require('crypto-js/enc-utf8');
    const payload = AES.encrypt(
      Buffer.from(MASTER_SECRET).toString('base64'),
      'ConfioWallet_Backup_Key_v1_DoNotShare'
    ).toString();

    (googleDriveStorage.listFiles as jest.Mock).mockResolvedValue([
      { id: 'backup-1', name: `confio_wallet_v2_${'a'.repeat(8)}.enc`, createdTime: '2026-01-01T00:00:00Z' },
    ]);
    (googleDriveStorage.downloadFile as jest.Mock).mockResolvedValue(payload);

    const secret = await getOrCreateMasterSecret(USER_SUB, 'drive-token', {
      provider: 'google',
      allowGenerate: true,
      expectedAddress,
    });

    expect(secret).toEqual(MASTER_SECRET);
    // The corrupt alias was rewritten with the recovered secret.
    expect(mockMemoryStore.get(subjectAlias())).toEqual(MASTER_SECRET);
  });

  // The mismatch branch warns, tries the address-bound alias, then falls
  // through to Drive. When that alias is absent AND Drive is empty, the
  // mismatching secret used to survive to the end and be synced back as the
  // user's wallet — there was an EVM-anchor final guard but no Algorand one.
  it('refuses a local secret that does not derive to the expected address when Drive is empty', async () => {
    const wrongSecret = new Uint8Array(32).fill(3);
    mockMemoryStore.set(subjectAlias(), wrongSecret);
    // clearAllMocks resets calls but NOT implementations, so an earlier test's
    // Drive contents would otherwise leak in and satisfy the anchor.
    (googleDriveStorage.listFiles as jest.Mock).mockResolvedValue([]);
    (googleDriveStorage.downloadFile as jest.Mock).mockRejectedValue(
      new Error('no files in test Drive')
    );

    await expect(
      getOrCreateMasterSecret(USER_SUB, 'drive-token', {
        provider: 'google',
        allowGenerate: true,
        expectedAddress,
      })
    ).rejects.toThrow(/respaldo correcto/i);

    // It must not have been uploaded as if it were the real wallet.
    expect(encBackupUploads()).toHaveLength(0);
  });

  // Both addresses derive from the SAME master secret, so matching the Algorand
  // anchor already proves the secret. A disagreeing BSC anchor therefore means
  // the server row is stale, not that the wallet is wrong — and rejecting it
  // would lock the user out of the wallet their authoritative anchor points to.
  // Accept, and log the inconsistency for reconciliation.
  it('accepts a secret matching one anchor when the other anchor is stale', async () => {
    seedLocalVerifiedSecret();
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
    (googleDriveStorage.listFiles as jest.Mock).mockResolvedValue([]);
    (googleDriveStorage.downloadFile as jest.Mock).mockRejectedValue(
      new Error('no files in test Drive')
    );

    const secret = await getOrCreateMasterSecret(USER_SUB, 'drive-token', {
      provider: 'google',
      allowGenerate: true,
      expectedAddress,
      expectedEvmAddress: '0x000000000000000000000000000000000000dead',
    });

    expect(secret).toEqual(MASTER_SECRET);
    expect(consoleError).toHaveBeenCalledWith(
      expect.stringContaining('STALE SERVER RECORD')
    );
    consoleError.mockRestore();
  });

  it('accepts a Solana-only recovery anchor', async () => {
    seedLocalVerifiedSecret();
    (googleDriveStorage.listFiles as jest.Mock).mockResolvedValue([]);

    const secret = await getOrCreateMasterSecret(USER_SUB, 'drive-token', {
      provider: 'google',
      allowGenerate: false,
      expectedSolanaAddress,
    });

    expect(secret).toEqual(MASTER_SECRET);
  });

  // But a secret contradicting EVERY supplied anchor is simply the wrong
  // wallet, and must never be adopted or uploaded.
  it('rejects a secret that contradicts every supplied anchor', async () => {
    mockMemoryStore.set(subjectAlias(), new Uint8Array(32).fill(9));
    (googleDriveStorage.listFiles as jest.Mock).mockResolvedValue([]);
    (googleDriveStorage.downloadFile as jest.Mock).mockRejectedValue(
      new Error('no files in test Drive')
    );

    await expect(
      getOrCreateMasterSecret(USER_SUB, 'drive-token', {
        provider: 'google',
        allowGenerate: true,
        expectedAddress,
        expectedEvmAddress: '0x000000000000000000000000000000000000dead',
      })
    ).rejects.toThrow(/respaldo/i);

    expect(encBackupUploads()).toHaveLength(0);
  });

  // An anchor means the server already knows this account's wallet, so a fresh
  // random secret can never be right. enableDriveBackup passes an anchor
  // WITHOUT allowGenerate:false, so this path used to mint a replacement,
  // persist it and upload it as the user's backup.
  it('refuses to generate when an anchor is set and nothing can be recovered', async () => {
    (googleDriveStorage.listFiles as jest.Mock).mockResolvedValue([]);
    (googleDriveStorage.downloadFile as jest.Mock).mockRejectedValue(
      new Error('no files in test Drive')
    );

    await expect(
      getOrCreateMasterSecret(USER_SUB, 'drive-token', {
        provider: 'google',
        allowGenerate: true,
        requireCloudSync: true,
        expectedAddress,
      })
    ).rejects.toThrow(/respaldo/i);

    expect(mockMemoryStore.get(subjectAlias())).toBeUndefined();
    expect(encBackupUploads()).toHaveLength(0);
  });

  // A legacy-global secret is adopted by tombstoning and deleting the original,
  // which is irreversible — so it must clear the anchor BEFORE that happens.
  it('refuses a legacy global secret that does not derive to the expected address', async () => {
    const legacyAlias = 'confio_master_secret';
    const wrongLegacy = new Uint8Array(32).fill(5);
    mockMemoryStore.set(legacyAlias, wrongLegacy);
    (googleDriveStorage.listFiles as jest.Mock).mockResolvedValue([]);
    (googleDriveStorage.downloadFile as jest.Mock).mockRejectedValue(
      new Error('no files in test Drive')
    );

    await expect(
      getOrCreateMasterSecret(USER_SUB, 'drive-token', {
        provider: 'google',
        allowGenerate: true,
        expectedAddress,
      })
    ).rejects.toThrow(/respaldo/i);

    // The legacy secret must survive intact: not tombstoned, not deleted.
    expect(mockMemoryStore.get(legacyAlias)).toEqual(wrongLegacy);
    expect(mockMemoryStore.get(subjectAlias())).toBeUndefined();
    expect(encBackupUploads()).toHaveLength(0);
  });

  // Without an anchor the Drive scan accepts the oldest decryptable backup, so
  // repairing corruption unanchored could adopt somebody else's wallet.
  it('refuses to repair a corrupt secret when no identity anchor is available', async () => {
    mockMemoryStore.set(subjectAlias(), new Uint8Array([1, 2, 3, 4]));

    await expect(
      getOrCreateMasterSecret(USER_SUB, 'drive-token', {
        provider: 'google',
        allowGenerate: true,
        // no expectedAddress, no expectedEvmAddress
      })
    ).rejects.toThrow(/dañados/i);

    expect(googleDriveStorage.listFiles).not.toHaveBeenCalled();
  });
});

describe('Drive backup format v2', () => {
  const nacl = require('tweetnacl');
  const { sha256 } = require('@noble/hashes/sha256');
  const { utf8ToBytes, bytesToHex } = require('@noble/hashes/utils');
  const APP_BACKUP_KEY = 'ConfioWallet_Backup_Key_v1_DoNotShare';

  const sealV2 = (secret: Uint8Array, overrides: Record<string, unknown> = {}) => {
    const nonce = new Uint8Array(24).fill(9);
    const inner = JSON.stringify({
      v: 2,
      secret: Buffer.from(secret).toString('base64'),
      // BOTH commitments are required — the reader checks each against what the
      // secret actually derives to, so omitting one is itself a rejection case.
      algo: deriveV2AddressPure(secret, { accountType: 'personal', accountIndex: 0 }),
      evm: deriveEvmKeyFromMasterSecret(secret, { accountType: 'personal', accountIndex: 0 })
        .address.toLowerCase(),
      solana: deriveSolanaKeyFromMasterSecret(secret, { accountType: 'personal', accountIndex: 0 })
        .address,
      ...overrides,
    });
    const ct = nacl.secretbox(utf8ToBytes(inner), nonce, sha256(utf8ToBytes(APP_BACKUP_KEY)));
    return JSON.stringify({ v: 2, alg: 'xsalsa20poly1305', nonce: bytesToHex(nonce), ct: bytesToHex(ct) });
  };

  // The manifest and the backup are different files; return content per id so
  // the manifest parser is never handed a v2 envelope (which IS valid JSON).
  const putOnDrive = (content: string) => {
    (googleDriveStorage.listFiles as jest.Mock).mockImplementation(async (_t: string, name: string) =>
      name === 'confio_wallet_manifest_v2.json'
        ? []
        : [{ id: 'f1', name: `confio_wallet_v2_${'a'.repeat(8)}.enc`, createdTime: '2026-01-01T00:00:00Z' }]
    );
    (googleDriveStorage.downloadFile as jest.Mock).mockImplementation(async (_t: string, id: string) => {
      if (id === 'f1') return content;
      throw new Error('unexpected file');
    });
  };

  beforeEach(() => {
    mockMemoryStore.clear();
    jest.clearAllMocks();
  });

  it('restores from a v2 authenticated backup', async () => {
    putOnDrive(sealV2(MASTER_SECRET));

    const secret = await getOrCreateMasterSecret(USER_SUB, 'drive-token', {
      provider: 'google',
      allowGenerate: false,
      expectedAddress,
    });

    expect(secret).toEqual(MASTER_SECRET);
  });

  it('restores a pre-Solana v2 backup without a Solana commitment', async () => {
    putOnDrive(sealV2(MASTER_SECRET, { solana: undefined }));

    const secret = await getOrCreateMasterSecret(USER_SUB, 'drive-token', {
      provider: 'google',
      allowGenerate: false,
      expectedSolanaAddress,
    });

    expect(secret).toEqual(MASTER_SECRET);
  });

  // The whole point of moving off unauthenticated CBC: a flipped byte must be
  // detected, not decrypted into garbage that then passes a length check.
  it('rejects a tampered v2 backup instead of decrypting it to garbage', async () => {
    const sealed = JSON.parse(sealV2(MASTER_SECRET));
    sealed.ct = sealed.ct.slice(0, -2) + (sealed.ct.endsWith('00') ? 'ff' : '00');
    putOnDrive(JSON.stringify(sealed));

    await expect(
      getOrCreateMasterSecret(USER_SUB, 'drive-token', {
        provider: 'google',
        allowGenerate: false,
        expectedAddress,
      })
    ).rejects.toThrow();
  });

  // A blob whose committed identity disagrees with its own payload is not
  // usable, even though it authenticates correctly.
  it('rejects a v2 backup whose identity commitment does not match its secret', async () => {
    putOnDrive(sealV2(MASTER_SECRET, { algo: 'WRONGADDRESS' }));

    await expect(
      getOrCreateMasterSecret(USER_SUB, 'drive-token', {
        provider: 'google',
        allowGenerate: false,
        expectedAddress,
      })
    ).rejects.toThrow();
  });

  // Validating a candidate must not persist anything derived from it.
  // deriveWalletV2 also caches the EVM sibling into the Keychain, so using it
  // to check a commitment wrote a REJECTED candidate's EVM address into the
  // cache that getEvmAddressForDisplay later trusts.
  it('does not cache an EVM address while validating a candidate it rejects', async () => {
    const Keychain = require('react-native-keychain');
    putOnDrive(sealV2(MASTER_SECRET, { algo: 'WRONGADDRESS' }));
    // Count only what the call under test writes, not what the helpers did.
    (Keychain.setGenericPassword as jest.Mock).mockClear();

    await expect(
      getOrCreateMasterSecret(USER_SUB, 'drive-token', {
        provider: 'google',
        allowGenerate: false,
        expectedAddress,
      })
    ).rejects.toThrow();

    const evmWrites = (Keychain.setGenericPassword as jest.Mock).mock.calls.filter(
      ([username]) => username === 'evm_address'
    );
    expect(evmWrites).toHaveLength(0);
  });
});
