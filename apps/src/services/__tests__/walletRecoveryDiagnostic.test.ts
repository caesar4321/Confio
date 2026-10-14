/**
 * The wallet-recovery diagnostic's core signal.
 *
 * A locked-out user (2785, 2026-10-14) produced no server-side evidence at
 * all: recovery runs on the device, so support could not tell a wrong key
 * from a corrupt file from an empty one. These tests pin the classification
 * that now travels to the server, and pin that it carries no content.
 */
import nacl from 'tweetnacl';
import { sha256 } from '@noble/hashes/sha256';
import { utf8ToBytes, bytesToHex } from '@noble/hashes/utils';
import { bytesToBase64 } from '../../utils/encoding';

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
  getVersion: jest.fn().mockReturnValue('5.2.1'),
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
  REPORT_WALLET_RECOVERY_DIAGNOSTIC: {},
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
    storeSecret: jest.fn(),
    retrieveSecret: jest.fn().mockResolvedValue(null),
    removeSecret: jest.fn(),
  },
}));
jest.mock('../googleDriveStorage', () => ({
  GoogleDriveStorageError: class extends Error {},
  googleDriveStorage: {
    listFiles: jest.fn().mockResolvedValue([]),
    downloadFile: jest.fn(),
    createFile: jest.fn(),
    updateFile: jest.fn(),
    listRevisions: jest.fn().mockResolvedValue([]),
    generateRecoveryFileIds: jest.fn().mockResolvedValue([]),
  },
}));

import { classifyBackupBody, decryptBackupDetailed } from '../secureDeterministicWallet';

const AES = require('crypto-js/aes');
const Utf8 = require('crypto-js/enc-utf8');
const KEY = 'ConfioWallet_Backup_Key_v1_DoNotShare';
const HEADER = 'ADVERTENCIA DE SEGURIDAD: NUNCA COMPARTAS ESTA CLAVE CON NADIE.';

const keyBytes = () => sha256(utf8ToBytes(KEY));
const envelope = (inner: object, key = keyBytes()) => {
  const nonce = new Uint8Array(24).fill(7);
  const ct = nacl.secretbox(utf8ToBytes(JSON.stringify(inner)), nonce, key);
  return JSON.stringify({ v: 2, alg: 'xsalsa20poly1305', nonce: bytesToHex(nonce), ct: bytesToHex(ct) });
};

describe('classifyBackupBody', () => {
  it('names the shape of each body without reading its contents', () => {
    expect(classifyBackupBody('')).toBe('empty');
    expect(classifyBackupBody(`${HEADER}\n`)).toBe('header_only');
    expect(classifyBackupBody(`${HEADER}\nU2FsdGVkX1+abc`)).toBe('legacy_aes');
    expect(classifyBackupBody(`${HEADER}\n${envelope({ v: 2 })}`)).toBe('v2_envelope');
    expect(classifyBackupBody('{"hello":"world"}')).toBe('json');
    // saveManifest writes pretty-printed JSON: judge the document, not its
    // closing brace, or every healthy manifest reads as 'unknown'.
    expect(classifyBackupBody(JSON.stringify({ wallets: [{ id: 'abc' }] }, null, 2))).toBe('json');
    expect(classifyBackupBody(`${HEADER}\n${JSON.stringify(
      { v: 2, alg: 'xsalsa20poly1305', nonce: 'aa', ct: 'bb' }, null, 2)}`)).toBe('v2_envelope');
    expect(classifyBackupBody('not a backup at all')).toBe('unknown');
  });
});

describe('decryptBackupDetailed', () => {
  it('tells a wrong key from a stale identity commitment', () => {
    // Opens, but claims addresses the secret does not derive to.
    const wrongCommitment = envelope({
      v: 2,
      secret: bytesToBase64(new Uint8Array(32).fill(3)),
      algo: 'SOMEONEELSEADDRESS',
      evm: '0xdeadbeef',
    });
    expect(decryptBackupDetailed(`${HEADER}\n${wrongCommitment}`, AES, KEY, Utf8))
      .toEqual({ secret: null, reason: 'bad_commitment' });

    // Same shape, encrypted under a different key: cannot even open.
    const foreign = envelope({ v: 2, secret: 'x' }, sha256(utf8ToBytes('another key')));
    expect(decryptBackupDetailed(`${HEADER}\n${foreign}`, AES, KEY, Utf8))
      .toEqual({ secret: null, reason: 'auth_failed' });
  });

  it('reports an empty or truncated file as such, not as a bad key', () => {
    expect(decryptBackupDetailed('', AES, KEY, Utf8)).toEqual({ secret: null, reason: 'empty' });
    expect(decryptBackupDetailed(`${HEADER}\n`, AES, KEY, Utf8)).toEqual({ secret: null, reason: 'empty' });
  });

  it('still reads a well-formed legacy v1 backup', () => {
    const secret = new Uint8Array(32).fill(9);
    const body = AES.encrypt(bytesToBase64(secret), KEY).toString();
    const read = decryptBackupDetailed(`${HEADER}\n${body}`, AES, KEY, Utf8);
    expect(read.reason).toBe('decrypted');
    expect(read.secret && Array.from(read.secret)).toEqual(Array.from(secret));
  });

  it('rejects junk without claiming it decrypted', () => {
    expect(decryptBackupDetailed('wat', AES, KEY, Utf8).secret).toBeNull();
  });
});

describe('decryption never logs what it failed on', () => {
  // Decoders quote their input. hexToBytes names the two characters it
  // choked on ('non-hex character "ZQ" at index 2'), and here the input is
  // ciphertext, so two characters of it are two too many.
  const SENTINEL = 'ZQ';
  let warn: jest.SpyInstance;
  beforeEach(() => { warn = jest.spyOn(console, 'warn').mockImplementation(() => {}); });
  afterEach(() => { warn.mockRestore(); });

  // JSON.stringify(new Error('secret')) is "{}", so a helper that reaches
  // for it first would report every Error as clean.
  const loggedText = () => warn.mock.calls.flat().map(arg => {
    if (typeof arg === 'string') return arg;
    if (arg instanceof Error) return `${arg.name}: ${arg.message} ${arg.stack || ''}`;
    try { return JSON.stringify(arg) ?? String(arg); } catch { return String(arg); }
  }).join(' ');

  it('keeps a malformed nonce out of the log', () => {
    const body = JSON.stringify({
      v: 2, alg: 'xsalsa20poly1305', nonce: `00${SENTINEL}1111`, ct: '00',
    });

    const read = decryptBackupDetailed(body, AES, KEY, Utf8);

    expect(read.secret).toBeNull();
    expect(loggedText()).not.toContain(SENTINEL);
  });

  it('keeps a malformed decrypted payload out of the log', () => {
    // Opens correctly, then fails on the plaintext: whatever the parser
    // says about it, it is saying it about decrypted backup contents.
    const body = envelope({ secret: 'not-base64-at-all', algo: 'A', evm: '0x1' } as any);

    const read = decryptBackupDetailed(body, AES, KEY, Utf8);

    expect(read.secret).toBeNull();
    expect(loggedText()).toMatch(/^\[MasterSecret\][^\n]*(Error|TypeError|SyntaxError|RangeError)\s*$/);
  });
});

describe('sign-in recovery reporting', () => {
  const { apolloClient } = require('../../apollo/client');
  const { googleDriveStorage } = require('../googleDriveStorage');
  const {
    getSignInWalletCandidate, reportTerminalRecoveryFailure,
  } = require('../secureDeterministicWallet');

  // What sign-in does: every attempt attaches what it saw, and only what
  // escapes the whole sequence is reported. Mirrored here so these tests
  // exercise the same two halves the real flow does.
  const recover = async (...args: any[]) => {
    const evidenceSink: { current?: unknown } = {};
    const options = { ...(args[2] || {}), evidenceSink };
    try {
      return await (getSignInWalletCandidate as any)(args[0], args[1], options);
    } catch (error) {
      await reportTerminalRecoveryFailure(error, options.reportAuthToken, evidenceSink);
      throw error;
    }
  };

  // Reporting is throttled to one per minute app-wide, so each case starts
  // well past the previous one's window instead of reaching into the module.
  let clock = Date.now();
  beforeEach(() => {
    clock += 10 * 60_000;
    jest.spyOn(Date, 'now').mockImplementation(() => clock);
    apolloClient.mutate.mockClear();
    googleDriveStorage.listFiles.mockReset();
    googleDriveStorage.downloadFile.mockReset();
    googleDriveStorage.listRevisions.mockResolvedValue([]);
  });
  afterEach(() => {
    (Date.now as jest.Mock).mockRestore?.();
  });

  it('reports the first failure of a minute and stays quiet after it', async () => {
    googleDriveStorage.listFiles.mockResolvedValue([]);

    // Three accounts, one broken Drive: the old code charged the user a
    // four second report deadline for each of them before sign-in failed.
    for (let i = 0; i < 3; i += 1) {
      await expect(recover('sub', 'drive-token', { reportAuthToken: 'jwt' }))
        .rejects.toMatchObject({ code: 'missing' });
    }
    expect(apolloClient.mutate).toHaveBeenCalledTimes(1);

    clock += 60_001;
    await expect(recover('sub', 'drive-token', { reportAuthToken: 'jwt' }))
      .rejects.toMatchObject({ code: 'missing' });
    expect(apolloClient.mutate).toHaveBeenCalledTimes(2);
  });

  it('says nothing at all when it cannot say whose failure it is', async () => {
    // Falling back to the stored JWT would file this against whoever was
    // signed in before - during a sign-in, that is exactly the wrong user.
    googleDriveStorage.listFiles.mockResolvedValue([]);

    await expect(recover('sub', 'drive-token'))
      .rejects.toMatchObject({ code: 'missing' });

    expect(apolloClient.mutate).not.toHaveBeenCalled();
  });

  it('does not make a stalled telemetry endpoint part of sign-in', async () => {
    // Never settles, and never rejects: the old awaited deadline turned
    // this into four seconds of waiting per failure, in front of the error
    // the user is actually waiting for.
    apolloClient.mutate.mockImplementationOnce(() => new Promise(() => {}));
    googleDriveStorage.listFiles.mockResolvedValue([]);

    // Fake timers make the point sharp: nothing may depend on the abort
    // deadline firing. Awaiting the report would hang here instead.
    jest.useFakeTimers();
    try {
      await expect(recover('sub', 'drive-token', { reportAuthToken: 'jwt' }))
        .rejects.toMatchObject({ code: 'missing' });
    } finally {
      jest.runOnlyPendingTimers();
      jest.useRealTimers();
    }
    expect(apolloClient.mutate).toHaveBeenCalledTimes(1);
  });

  it('still reports a different failure inside the same minute', async () => {
    // The real sequence: canonical discovery finds nothing, then the legacy
    // path finds a file it cannot read. The second one is the diagnosis.
    googleDriveStorage.listFiles.mockResolvedValue([]);
    await expect(recover('sub', 'drive-token', { reportAuthToken: 'jwt' }))
      .rejects.toMatchObject({ code: 'missing' });

    googleDriveStorage.listFiles.mockImplementation(async (_t: string, name?: string) =>
      name && name.endsWith('.json') && !name.startsWith('confio_wallet_manifest')
        ? [{ id: 'legacy-1', name }, { id: 'legacy-2', name }]
        : []);
    // Twins are now read rather than refused on sight; these two do not
    // decrypt, so the outcome is still 'unreadable'.
    googleDriveStorage.downloadFile.mockResolvedValue('not an encrypted backup');
    await expect(recover('sub', 'drive-token', {
      reportAuthToken: 'jwt',
      legacyRegistrations: [{ accountType: 'personal', accountIndex: 0, algorandAddress: 'ADDR' }],
    })).rejects.toMatchObject({ code: 'unreadable' });

    expect(apolloClient.mutate).toHaveBeenCalledTimes(2);
    expect(apolloClient.mutate.mock.calls[1][0].variables.code).toBe('unreadable');
  });

  it('still reports when a different session hits the same failure', async () => {
    googleDriveStorage.listFiles.mockResolvedValue([]);
    await expect(recover('sub-a', 'drive-token', { reportAuthToken: 'jwt-a' }))
      .rejects.toMatchObject({ code: 'missing' });
    await expect(recover('sub-b', 'drive-token', { reportAuthToken: 'jwt-b' }))
      .rejects.toMatchObject({ code: 'missing' });

    expect(apolloClient.mutate).toHaveBeenCalledTimes(2);
  });

  it('reports what Drive held when sign-in recovery fails, shapes only', async () => {
    // One manifest, one payload, and the payload cannot be decrypted: user
    // 2785's exact shape on 2026-10-14.
    googleDriveStorage.listFiles.mockImplementation(async (_t: string, name?: string) =>
      name && name.endsWith('.enc') ? [{ id: 'payload-1', name }] : [{ id: 'manifest-1', name }]);
    googleDriveStorage.downloadFile.mockImplementation(async (_t: string, id: string) =>
      id === 'manifest-1'
        ? JSON.stringify({ wallets: [{ id: 'abc', deviceHint: 'HONOR adan (android)' }] })
        : `${HEADER}\nU2FsdGVkX1+thisWillNotDecrypt`);

    await expect(recover('sub', 'drive-token', { reportAuthToken: 'jwt' }))
      .rejects.toMatchObject({ code: 'unreadable' });

    expect(apolloClient.mutate).toHaveBeenCalledTimes(1);
    const { variables } = apolloClient.mutate.mock.calls[0][0];
    expect(variables.code).toBe('unreadable');
    expect(variables.foundAny).toBe(true);
    expect(variables.foundDecryptable).toBe(false);
    // No client-controlled free text travels at all.
    expect(variables.deviceName).toBeUndefined();
    expect(variables.appVersion).toBeUndefined();

    const inventory = JSON.parse(variables.inventory);
    // One manifest and one payload: the file we read is the file we listed,
    // described in place rather than counted twice.
    expect(inventory.map((e: any) => e.shape)).toEqual(['manifest', 'payload']);
    expect(inventory[0]).toMatchObject({ shape: 'manifest', format: 'json', outcome: 'parsed' });
    expect(inventory[1]).toMatchObject({ shape: 'payload', format: 'legacy_aes', outcome: 'bad_secret' });
    // Nothing from the files themselves may travel: no ciphertext, no names,
    // no device hint.
    const wire = JSON.stringify(variables);
    expect(wire).not.toContain('U2FsdGVkX1');
    expect(wire).not.toContain('HONOR');
    expect(wire).not.toContain('confio_wallet_v2_');
  });

  it('reports a Drive outage too, and rethrows it untouched', async () => {
    // Not a WalletRecoveryError, but it locks the user out just the same.
    const outage = Object.assign(new Error('drive unavailable'), { name: 'GoogleDriveStorageError' });
    googleDriveStorage.listFiles.mockRejectedValue(outage);

    await expect(recover('sub', 'drive-token', { reportAuthToken: 'jwt' }))
      .rejects.toBe(outage);

    expect(apolloClient.mutate).toHaveBeenCalledTimes(1);
    expect(apolloClient.mutate.mock.calls[0][0].variables.code).toBe('drive_access');
  });

  it('says when the manifest itself is the broken part', async () => {
    googleDriveStorage.listFiles.mockResolvedValue([{ id: 'manifest-1', name: 'confio_wallet_manifest_v2.json' }]);
    googleDriveStorage.downloadFile.mockResolvedValue('{ not json at all');

    await expect(recover('sub', 'drive-token', { reportAuthToken: 'jwt' }))
      .rejects.toMatchObject({ code: 'unreadable' });

    const inventory = JSON.parse(apolloClient.mutate.mock.calls[0][0].variables.inventory);
    expect(inventory[0]).toMatchObject({ shape: 'manifest', outcome: 'malformed' });
  });

  it('records a download failure against the file it could not read', async () => {
    googleDriveStorage.listFiles.mockResolvedValue([{ id: 'manifest-1', name: 'confio_wallet_manifest_v2.json' }]);
    const outage = Object.assign(new Error('download failed'), { name: 'GoogleDriveStorageError' });
    googleDriveStorage.downloadFile.mockRejectedValue(outage);

    await expect(recover('sub', 'drive-token', { reportAuthToken: 'jwt' }))
      .rejects.toBe(outage);

    const { variables } = apolloClient.mutate.mock.calls[0][0];
    expect(variables.code).toBe('drive_access');
    expect(JSON.parse(variables.inventory)[0]).toMatchObject({ outcome: 'download_failed' });
  });

  it('says nothing by itself: an answered attempt is not a lockout', async () => {
    // Canonical discovery returning 'missing' is answered by the legacy
    // read and then by provisioning. Reporting it here would file a
    // failure that never happened and spend the hourly allowance a real
    // lockout needs, so discovery only ATTACHES what it saw.
    googleDriveStorage.listFiles.mockResolvedValue([]);

    await expect(getSignInWalletCandidate('sub', 'drive-token', { reportAuthToken: 'jwt' }))
      .rejects.toMatchObject({ code: 'missing' });

    expect(apolloClient.mutate).not.toHaveBeenCalled();
  });

  it('does not let one attempt be reported with another attempt\'s evidence', async () => {
    // Two attempts can reject with the SAME error object - a cached or
    // shared rejection, or a frozen one that cannot carry anything at all.
    // Evidence belongs to the attempt, not to what it threw.
    const shared = Object.freeze(
      Object.assign(new Error('drive down'), { name: 'GoogleDriveStorageError' }),
    );
    googleDriveStorage.listFiles.mockImplementation(async (_t: string, name?: string) =>
      name === 'confio_wallet_manifest_v2.json' ? [{ id: 'manifest-1', name }] : []);
    googleDriveStorage.downloadFile.mockResolvedValue('{"wallets":[]}');

    const first: { current?: any } = {};
    await expect(getSignInWalletCandidate('sub', 'drive-token', {
      reportAuthToken: 'jwt', evidenceSink: first,
    })).rejects.toBeDefined();
    expect(first.current.inventory.length).toBeGreaterThan(0);

    // A second attempt that sees nothing must not inherit the first's files.
    googleDriveStorage.listFiles.mockRejectedValue(shared);
    const second: { current?: any } = {};
    await expect(getSignInWalletCandidate('sub', 'drive-token', {
      reportAuthToken: 'jwt', evidenceSink: second,
    })).rejects.toBe(shared);

    expect(second.current.inventory).toHaveLength(0);
    expect(second.current.foundAny).toBe(false);
    // And the error itself was never written to.
    expect((shared as any).evidence).toBeUndefined();
  });

  it('reports an escape it cannot even name, rather than nothing', async () => {
    // A cancelled reauthorization, a reservation error, a native storage
    // failure: the user is locked out whether or not this module has a
    // name for what happened.
    const unnameable = new Error('reauthorization cancelled');

    await reportTerminalRecoveryFailure(unnameable, 'jwt');

    expect(apolloClient.mutate).toHaveBeenCalledTimes(1);
    expect(apolloClient.mutate.mock.calls[0][0].variables.code).toBe('unexpected');
  });

  it('still reports when the failure is a missing backup', async () => {
    googleDriveStorage.listFiles.mockResolvedValue([]);
    await expect(recover('sub', 'drive-token', { reportAuthToken: 'jwt' }))
      .rejects.toMatchObject({ code: 'missing' });
    expect(apolloClient.mutate).toHaveBeenCalledTimes(1);
    expect(apolloClient.mutate.mock.calls[0][0].variables.foundAny).toBe(false);
  });
});
