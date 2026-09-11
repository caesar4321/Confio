/**
 * Regression tests for the stranded-legacy-wallet migration loop.
 *
 * Incident (user 1120, 2026-09-10): the account self-healed to V2 in Dec 2025,
 * but its V1 wallet kept zero-balance opt-ins. checkNeedsMigration counted
 * those as "must migrate", PrepareAtomicMigration refused (it only sweeps the
 * registered, unmigrated V1), and a full-screen modal showed "Actualización
 * Fallida" forever. On a cold start it failed even earlier: no in-memory Drive
 * token.
 */
const mockAccountInformation = jest.fn();
const mockQuery = jest.fn();

jest.mock('algosdk', () => ({
  __esModule: true,
  default: {
    Algodv2: jest.fn().mockImplementation(() => ({
      accountInformation: (address: string) => ({ do: () => mockAccountInformation(address) }),
    })),
  },
}));

jest.mock('../../apollo/client', () => ({
  apolloClient: {
    query: (...args: any[]) => mockQuery(...args),
    mutate: jest.fn().mockResolvedValue({ data: {} }),
  },
}));

jest.mock('../../apollo/mutations', () => ({ SUBMIT_SPONSORED_GROUP: {} }));
jest.mock('../../apollo/queries', () => ({ GET_MY_MIGRATION_STATUS: {} }));

jest.mock('../oauthStorageService', () => ({
  oauthStorage: { getOAuthSubject: jest.fn() },
}));

jest.mock('../secureDeterministicWallet', () => ({
  secureDeterministicWallet: {
    restoreLegacyV1Wallet: jest.fn().mockResolvedValue({ address: 'V1ADDR', privSeedHex: '00'.repeat(32) }),
  },
  getOrCreateMasterSecret: jest.fn().mockResolvedValue(new Uint8Array(32)),
  deriveWalletV2: jest.fn().mockReturnValue({ address: 'V2ADDR', privSeedHex: '11'.repeat(32) }),
  retrieveClientSecret: jest.fn(),
  storeClientSecret: jest.fn(),
}));

jest.mock('../authService', () => ({
  __esModule: true,
  default: {
    getCachedDriveAccessToken: jest.fn().mockReturnValue(null),
    forceUpdateLocalAlgorandAddress: jest.fn(),
  },
  registerAlgorandAddressChecked: jest.fn().mockResolvedValue({ success: true }),
  redactAddress: (address: string) => address,
}));

jest.mock('../../config/env', () => ({
  API_URL: 'https://confio.lat/graphql',
  CONFIO_ASSET_ID: '3351104258',
  CUSD_ASSET_ID: '3198259450',
  USDC_ASSET_ID: '31566704',
  GOOGLE_CLIENT_IDS: { production: { web: 'web' }, development: { web: 'web-dev' } },
}));

import { migrationService, DriveAuthorizationRequiredError } from '../migrationService';

const ISS = 'https://accounts.google.com';
const check = () => migrationService.checkNeedsMigration(ISS, 'sub', 'web', 'google', 0);

// The shape of user 1120's V1 on mainnet: sponsor MBR only, empty opt-ins.
const strandedV1 = {
  amount: 300000,
  'min-balance': 300000,
  assets: [
    { 'asset-id': 3198259450, amount: 0 },
    { 'asset-id': 3198568509, amount: 0 },
  ],
};

// The shape of user 2501's V1: real USDC left behind.
const fundedV1 = {
  ...strandedV1,
  assets: [{ 'asset-id': 31566704, amount: 12218160 }],
};

const registered = (algorandAddress: string | null, isKeylessMigrated: boolean) => ({
  data: { userAccounts: [{ accountType: 'PERSONAL', accountIndex: 0, algorandAddress, isKeylessMigrated }] },
});

beforeEach(() => {
  mockAccountInformation.mockReset();
  mockQuery.mockReset();
});

describe('checkNeedsMigration only asks for sweeps the server will sponsor', () => {
  it('does not ask to migrate an empty V1 once the account is registered elsewhere', async () => {
    mockAccountInformation.mockResolvedValue(strandedV1);
    mockQuery.mockResolvedValue(registered('V2ADDR', true));

    const state = await check();

    expect(state.needsMigration).toBe(false);
    expect(state.statusUnknown).toBeUndefined();
  });

  it('does not trap a migrated account whose old V1 still holds funds', async () => {
    mockAccountInformation.mockResolvedValue(fundedV1);
    mockQuery.mockResolvedValue(registered('V2ADDR', true));

    const state = await check();

    expect(state.needsMigration).toBe(false);
    expect(state.statusUnknown).toBeUndefined();
  });

  it('does not ask to sweep a registered V1 the server already marked migrated', async () => {
    mockAccountInformation.mockResolvedValue(strandedV1);
    mockQuery.mockResolvedValue(registered('V1ADDR', true));

    const state = await check();

    expect(state.needsMigration).toBe(false);
  });

  it('still migrates the registered, unmigrated V1 even when its opt-ins are empty', async () => {
    mockAccountInformation.mockResolvedValue(strandedV1);
    mockQuery.mockResolvedValue(registered('V1ADDR', false));

    const state = await check();

    expect(state.needsMigration).toBe(true);
  });

  it('still migrates a registered, unmigrated V1 that holds funds', async () => {
    mockAccountInformation.mockResolvedValue(fundedV1);
    mockQuery.mockResolvedValue(registered('V1ADDR', false));

    const state = await check();

    expect(state.needsMigration).toBe(true);
  });

  it('reports unknown when another row, possibly one the user only works for, registers this V1', async () => {
    // userAccounts carries no ownership and includes employee views of other
    // owners' businesses, while the server sweeps only rows the caller owns.
    mockAccountInformation.mockResolvedValue(fundedV1);
    mockQuery.mockResolvedValue({ data: { userAccounts: [
      { accountType: 'PERSONAL', accountIndex: 0, algorandAddress: 'V2ADDR', isKeylessMigrated: true },
      { accountType: 'BUSINESS', accountIndex: 0, algorandAddress: 'V1ADDR', isKeylessMigrated: false, business: { id: 'other' } },
    ] } });

    const state = await check();

    expect(state).toEqual({ needsMigration: false, statusUnknown: true });
  });

  it('applies the same rule to a business context', async () => {
    mockAccountInformation.mockResolvedValue(fundedV1);
    const rows = (algorandAddress: string, isKeylessMigrated: boolean) => ({ data: { userAccounts: [
      { accountType: 'PERSONAL', accountIndex: 0, algorandAddress: 'P2ADDR', isKeylessMigrated: true },
      { accountType: 'BUSINESS', accountIndex: 0, algorandAddress, isKeylessMigrated, business: { id: 'biz1' } },
    ] } });
    const checkBusiness = () => migrationService.checkNeedsMigration(ISS, 'sub', 'web', 'google', 0, 'biz1');

    mockQuery.mockResolvedValue(rows('V1ADDR', false));
    expect((await checkBusiness()).needsMigration).toBe(true);

    mockQuery.mockResolvedValue(rows('B2ADDR', true));
    const cleared = await checkBusiness();
    expect(cleared.needsMigration).toBe(false);
    expect(cleared.statusUnknown).toBeUndefined();
  });

  it('reports unknown, not "nothing to migrate", when the registration lookup fails', async () => {
    mockAccountInformation.mockResolvedValue(fundedV1);
    mockQuery.mockRejectedValue(new Error('network down'));

    const state = await check();

    expect(state).toEqual({ needsMigration: false, statusUnknown: true });
  });
});

describe('checkNeedsMigration with an unusable account list', () => {
  it('reports unknown when the server returns no matching account (e.g. an anonymous request)', async () => {
    mockAccountInformation.mockResolvedValue(fundedV1);
    mockQuery.mockResolvedValue({ data: { userAccounts: [] } });

    const state = await check();

    expect(state).toEqual({ needsMigration: false, statusUnknown: true });
  });
});

describe('performMigration without a Drive token', () => {
  it('raises a typed error the modal can turn into a reconnect prompt', async () => {
    await expect(
      migrationService.performMigration(ISS, 'sub', 'web', 'google', 0),
    ).rejects.toBeInstanceOf(DriveAuthorizationRequiredError);
  });
});
