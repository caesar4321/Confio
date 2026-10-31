const mockNative = { accountStatus: jest.fn(), userHash: jest.fn(), insert: jest.fn(), fetch: jest.fn() };
const mockMutate = jest.fn();
const mockMarkers = new Map<string, string>();
const mockMaterial = jest.fn();

const mockAlert = jest.fn();

jest.mock('react-native', () => ({
  Alert: { alert: (...args: any[]) => mockAlert(...args) },
  Platform: { OS: 'ios' },
  NativeModules: { get ConfioCloudBackup() { return mockNative; } },
}));
jest.mock('react-native-keychain', () => ({
  getGenericPassword: jest.fn(async ({ service }) => (mockMarkers.has(service) ? { password: mockMarkers.get(service) } : false)),
  setGenericPassword: jest.fn(async (_u, password, { service }) => { mockMarkers.set(service, password); return true; }),
}));
jest.mock('jwt-decode', () => ({ jwtDecode: () => ({ user_id: 7 }) }));
jest.mock('../../apollo/queries', () => ({ REPORT_CLOUDKIT_BACKUP: 'REPORT' }));
jest.mock('../../apollo/client', () => ({ apolloClient: { mutate: (...args: any[]) => mockMutate(...args) } }));
jest.mock('../oauthStorageService', () => ({ oauthStorage: { getOAuthSubject: async () => ({ subject: 'sub' }) } }));
jest.mock('../authService', () => ({ AuthService: { getInstance: () => ({ getToken: async () => 'jwt' }) } }));
jest.mock('../secureDeterministicWallet', () => ({ getCloudKitBackupMaterial: (...args: any[]) => mockMaterial(...args) }));

import { ensureCloudKitBackup, findCloudKitBackups, cloudKitAddressHash, retryFullCloudKitBackup } from '../cloudKitBackup';

const material = {
  bscAddress: '0xABC', algorandAddress: 'ALGO', payload: 'body',
  holdsThisSecret: (body: string) => body === 'body',
};
const reports = () => mockMutate.mock.calls.map(([call]) => call.variables.state);

beforeEach(() => {
  jest.clearAllMocks();
  mockMarkers.clear();
  mockMaterial.mockResolvedValue(material);
  mockNative.accountStatus.mockResolvedValue('available');
  mockNative.userHash.mockResolvedValue('icloud-a');
  mockNative.insert.mockResolvedValue('inserted');
  mockNative.fetch.mockResolvedValue('body');
  mockMutate.mockResolvedValue({ data: { reportCloudkitBackup: { success: true } } });
});

it('reports proof only after reading both records back, pinned to the session', async () => {
  await ensureCloudKitBackup();
  expect(mockNative.insert).toHaveBeenCalledTimes(2);
  expect(mockNative.fetch).toHaveBeenCalledTimes(2);
  expect(mockMutate).toHaveBeenCalledWith(expect.objectContaining({
    variables: { state: 'proven', walletHashes: [cloudKitAddressHash('0xabc'), cloudKitAddressHash('ALGO')] },
    context: { pinnedAuthToken: 'jwt', skipProactiveRefresh: true },
  }));
});

it('does nothing more once proven and acknowledged', async () => {
  await ensureCloudKitBackup();
  jest.clearAllMocks();
  await ensureCloudKitBackup();
  expect(mockNative.insert).not.toHaveBeenCalled();
  expect(mockMutate).not.toHaveBeenCalled();
});

it('never reports proof when the server copy holds something else', async () => {
  mockNative.insert.mockResolvedValue('exists');
  mockNative.fetch.mockResolvedValue('another wallet');
  await ensureCloudKitBackup();
  expect(reports()).toEqual(['failed']);
  expect(mockMarkers.size).toBe(0);
});

describe('a full iCloud', () => {
  const quotaError = Object.assign(new Error('CloudKit error 25'), { code: 'CK_25' });
  const dismissNotice = () => mockAlert.mock.calls[mockAlert.mock.calls.length - 1][2][0].onPress();

  it('warns of the risk at every open until a retry stores the backup', async () => {
    mockNative.insert.mockRejectedValue(quotaError);
    await ensureCloudKitBackup();
    expect(reports()).toEqual(['icloud_full']);
    expect(mockAlert).toHaveBeenCalledTimes(1);
    expect(mockAlert.mock.calls[0][1]).toContain('podrías perder tu dinero');
    expect(mockAlert.mock.calls[0][1]).toContain('Libera espacio en iCloud');
    dismissNotice();

    await ensureCloudKitBackup();
    expect(mockAlert).toHaveBeenCalledTimes(2);
    dismissNotice();

    await retryFullCloudKitBackup();
    expect(mockAlert).toHaveBeenCalledTimes(3);
    dismissNotice();

    mockNative.insert.mockResolvedValue('inserted');
    await retryFullCloudKitBackup();
    expect(mockAlert).toHaveBeenCalledTimes(3);
    expect(reports()).toContain('proven');

    jest.clearAllMocks();
    await retryFullCloudKitBackup();
    expect(mockNative.accountStatus).not.toHaveBeenCalled();
  });

  it('keeps warning through a failure that says nothing about the space', async () => {
    mockNative.insert.mockRejectedValue(quotaError);
    await ensureCloudKitBackup();
    dismissNotice();
    mockNative.insert.mockRejectedValue(new Error('CLOUDKIT-TIMEOUT'));
    await retryFullCloudKitBackup();
    expect(mockAlert).toHaveBeenCalledTimes(2);
    dismissNotice();
    await retryFullCloudKitBackup();
    expect(mockAlert).toHaveBeenCalledTimes(3);
    dismissNotice();
    mockNative.insert.mockResolvedValue('inserted');
    await ensureCloudKitBackup();
  });

  it('never stacks a second notice over one still open', async () => {
    mockNative.insert.mockRejectedValue(quotaError);
    await ensureCloudKitBackup();
    await ensureCloudKitBackup();
    expect(mockAlert).toHaveBeenCalledTimes(1);
    dismissNotice();
    mockNative.insert.mockResolvedValue('inserted');
    await ensureCloudKitBackup();
  });

  it('still warns when the report cannot reach the server', async () => {
    mockNative.insert.mockRejectedValue(quotaError);
    mockMutate.mockRejectedValueOnce(new Error('network'));
    await ensureCloudKitBackup();
    expect(mockAlert).toHaveBeenCalledTimes(1);
    dismissNotice();
    mockNative.insert.mockResolvedValue('inserted');
    await ensureCloudKitBackup();
  });
});

it('reports any other failure with its code and no notice', async () => {
  mockNative.insert.mockRejectedValue(Object.assign(new Error('CloudKit error 12'), { code: 'CK_12' }));
  await ensureCloudKitBackup();
  expect(mockMutate.mock.calls[0][0].variables).toMatchObject({ state: 'failed', errorCode: 'CK_12' });
  expect(mockAlert).not.toHaveBeenCalled();
});

it('never reports proof when the read-back finds nothing', async () => {
  mockNative.fetch.mockResolvedValue(null);
  await ensureCloudKitBackup();
  expect(reports()).toEqual(['failed']);
});

it('retries a lost report without uploading again', async () => {
  mockMutate.mockRejectedValueOnce(new Error('network'));
  await ensureCloudKitBackup();
  mockNative.insert.mockClear();
  await ensureCloudKitBackup();
  expect(mockNative.insert).not.toHaveBeenCalled();
  expect(reports()).toEqual(['proven', 'proven']);
});

it('keeps retrying while the server refuses the proof', async () => {
  mockMutate.mockResolvedValueOnce({ data: { reportCloudkitBackup: { success: false } } });
  await ensureCloudKitBackup();
  await ensureCloudKitBackup();
  expect(reports()).toEqual(['proven', 'proven']);
});

it('backs up again after the iCloud account changes', async () => {
  await ensureCloudKitBackup();
  mockNative.insert.mockClear();
  mockNative.userHash.mockResolvedValue('icloud-b');
  await ensureCloudKitBackup();
  expect(mockNative.insert).toHaveBeenCalledTimes(2);
});

it('tells the server when there is no iCloud account', async () => {
  mockNative.accountStatus.mockResolvedValue('noAccount');
  await ensureCloudKitBackup();
  expect(reports()).toEqual(['no_icloud_account']);
  expect(mockNative.insert).not.toHaveBeenCalled();
});

it('sends proof again when iCloud comes back', async () => {
  await ensureCloudKitBackup();
  mockNative.accountStatus.mockResolvedValueOnce('noAccount');
  await ensureCloudKitBackup();
  mockNative.insert.mockClear();
  await ensureCloudKitBackup();
  expect(mockNative.insert).not.toHaveBeenCalled();
  expect(reports()).toEqual(['proven', 'no_icloud_account', 'proven']);
});

it('claims nothing while iCloud cannot say', async () => {
  mockNative.accountStatus.mockResolvedValue('unknown');
  await ensureCloudKitBackup();
  expect(mockMutate).not.toHaveBeenCalled();
});

it('uploads nothing without a local secret', async () => {
  mockMaterial.mockResolvedValue(null);
  await ensureCloudKitBackup();
  expect(mockNative.insert).not.toHaveBeenCalled();
});

describe('findCloudKitBackups', () => {
  it('skips empty addresses and returns what it finds', async () => {
    expect(await findCloudKitBackups(['0xabc', null])).toEqual({ payloads: ['body'], unknown: false });
    expect(mockNative.fetch).toHaveBeenCalledTimes(1);
  });

  it('never reads a refused iCloud as an empty one', async () => {
    mockNative.fetch.mockRejectedValue({ code: 'CK_9' });
    expect(await findCloudKitBackups(['0xabc'])).toEqual({ payloads: [], unknown: true });
  });

  it('has nothing to look at without an iCloud account', async () => {
    mockNative.accountStatus.mockResolvedValue('noAccount');
    expect(await findCloudKitBackups(['0xabc'])).toEqual({ payloads: [], unknown: false });
  });

  it('never turns a read failure into "no backup"', async () => {
    mockNative.fetch.mockRejectedValue({ code: 'CK_3' });
    expect(await findCloudKitBackups(['0xabc'])).toEqual({ payloads: [], unknown: true });
  });

  it('never turns a failed status check into "no backup"', async () => {
    mockNative.accountStatus.mockRejectedValue(new Error('boom'));
    expect(await findCloudKitBackups(['0xabc'])).toEqual({ payloads: [], unknown: true });
  });

  it('keeps a found backup when another address could not be read', async () => {
    mockNative.fetch.mockResolvedValueOnce('body').mockRejectedValueOnce({ code: 'CK_3' });
    expect(await findCloudKitBackups(['0xabc', 'ALGO'])).toEqual({ payloads: ['body'], unknown: true });
  });
});
