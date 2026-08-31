const WAD = 10n ** 18n;
const VAULT = `0x${'11'.repeat(20)}`;
const CUSD = `0x${'22'.repeat(20)}`;
const mockUser = `0x${'33'.repeat(20)}`;
const ORACLE = `0x${'44'.repeat(20)}`;
const mockDelegate = `0x${'55'.repeat(20)}`;

const mockEthCall = jest.fn();
const mockExecuteSponsoredBatch = jest.fn();
const mockQuery = jest.fn();

jest.mock('../bscServerRpc', () => ({ installBscServerTransport: jest.fn() }));
jest.mock('../../apollo/client', () => ({ apolloClient: { query: mockQuery, mutate: jest.fn() } }));
jest.mock('../secureDeterministicWallet', () => ({
  getActiveEvmWallet: jest.fn(async () => ({ address: mockUser, privKeyHex: '66'.repeat(32) })),
}));
jest.mock('../sponsored7702', () => ({
  fetchSponsored7702Params: jest.fn(async () => ({ enabled: true, delegateAddress: mockDelegate })),
  executeSponsoredBatch: (...args: unknown[]) => mockExecuteSponsoredBatch(...args),
}));
jest.mock('../evmWallet', () => ({
  bscEthCall: (...args: unknown[]) => mockEthCall(...args),
  encodeCall: (signature: string, args: Array<{ value: unknown }>) =>
    `0x${signature}|${args.map(arg => String(arg.value)).join('|')}`,
  encodeAddress: (address: string) => address.slice(2).padStart(64, '0'),
  selector: (signature: string) => `0x${signature}`,
  sendCall: jest.fn(),
  isOutcomeUnknown: jest.fn(() => false),
}));

import { unwrapAllSavingsToCusd, wrapAllCusdToSavings } from '../cusdPlusVault';
import { resumeSavingsMints } from '../savingsLegC';

describe('eligibility rail normalization', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockExecuteSponsoredBatch.mockResolvedValue({ txHash: `0x${'77'.repeat(32)}` });
  });

  it('wraps the whole cUSD balance into cUSD+ with no perimeter redemption', async () => {
    mockEthCall.mockImplementation(async (to: string, data: string) => {
      if (to === CUSD && data.startsWith('0xbalanceOf')) return `0x${(10n * WAD).toString(16)}`;
      if (to === CUSD && data.startsWith('0xallowance')) return '0x0';
      if (to === VAULT && data === '0xORACLE()') {
        return `0x${ORACLE.slice(2).padStart(64, '0')}`;
      }
      if (to === ORACLE && data === '0xgetPrice()') return `0x${WAD.toString(16)}`;
      throw new Error(`unexpected call ${to} ${data}`);
    });

    const result = await wrapAllCusdToSavings({ vaultAddress: VAULT, cusdAddress: CUSD });

    expect(result?.txHash).toBe(`0x${'77'.repeat(32)}`);
    const [{ calls }] = mockExecuteSponsoredBatch.mock.calls[0];
    expect(calls).toHaveLength(2);
    expect(calls[0].to).toBe(CUSD);
    expect(calls[0].data).toContain('approve(address,uint256)');
    expect(calls[1].to).toBe(VAULT);
    expect(calls[1].data).toContain('wrapCusd(uint256,uint256,address)');
    expect(calls[1].data).not.toContain('redeemWithFee');
  });

  it('unwraps the whole cUSD+ position into cUSD without crossing USDT', async () => {
    mockEthCall.mockImplementation(async (to: string, data: string) => {
      if (to === VAULT && data.startsWith('0xbalanceOf')) return `0x${(10n * WAD).toString(16)}`;
      if (to === VAULT && data === '0xpPlus()') return `0x${WAD.toString(16)}`;
      if (to === VAULT && data === '0xlastOraclePrice()') return `0x${WAD.toString(16)}`;
      throw new Error(`unexpected call ${to} ${data}`);
    });

    const result = await unwrapAllSavingsToCusd({ vaultAddress: VAULT, cusdAddress: CUSD });

    expect(result?.txHash).toBe(`0x${'77'.repeat(32)}`);
    const [{ calls }] = mockExecuteSponsoredBatch.mock.calls[0];
    expect(calls).toHaveLength(1);
    expect(calls[0].to).toBe(VAULT);
    expect(calls[0].data).toContain('unwrapToCusd(uint256,uint256,address)');
    expect(calls[0].data).not.toContain('redeemToUsdt');
  });

  it('leaves an exact-dollar cUSD balance untouched until it clears flooring', async () => {
    mockEthCall.mockResolvedValue(`0x${WAD.toString(16)}`);

    await expect(
      wrapAllCusdToSavings({ vaultAddress: VAULT, cusdAddress: CUSD }),
    ).resolves.toBeNull();
    expect(mockExecuteSponsoredBatch).not.toHaveBeenCalled();
  });
});

describe('foreground eligibility reconciliation', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockExecuteSponsoredBatch.mockResolvedValue({ txHash: `0x${'77'.repeat(32)}` });
  });

  it('selects cUSD -> cUSD+ after the authoritative eligibility answer changes', async () => {
    mockQuery
      .mockResolvedValueOnce({ data: { cusdPlusSummary: {
        savingsEnabled: true,
        sweepableUsdtWei: '0',
        balanceUsd: 0,
        cusdBalanceWei: (10n * WAD).toString(),
      } } })
      .mockResolvedValueOnce({ data: { cusdPlusConversionsInFlight: [] } });
    mockEthCall.mockImplementation(async (to: string, data: string) => {
      if (to === CUSD && data.startsWith('0xbalanceOf')) return `0x${(10n * WAD).toString(16)}`;
      if (to === CUSD && data.startsWith('0xallowance')) return `0x${((1n << 256n) - 1n).toString(16)}`;
      if (to === VAULT && data === '0xORACLE()') return `0x${ORACLE.slice(2).padStart(64, '0')}`;
      if (to === ORACLE && data === '0xgetPrice()') return `0x${WAD.toString(16)}`;
      throw new Error(`unexpected call ${to} ${data}`);
    });

    await resumeSavingsMints(VAULT, CUSD);

    const [{ calls }] = mockExecuteSponsoredBatch.mock.calls[0];
    expect(calls).toHaveLength(1);
    expect(calls[0].data).toContain('wrapCusd(uint256,uint256,address)');
  });

  it('selects cUSD+ -> cUSD after the authoritative eligibility answer changes', async () => {
    mockQuery
      .mockResolvedValueOnce({ data: { cusdPlusSummary: {
        savingsEnabled: false,
        sweepableUsdtWei: '0',
        balanceUsd: 10,
        cusdBalanceWei: '0',
      } } })
      .mockResolvedValueOnce({ data: { cusdPlusConversionsInFlight: [] } });
    mockEthCall.mockImplementation(async (to: string, data: string) => {
      if (to === VAULT && data.startsWith('0xbalanceOf')) return `0x${(10n * WAD).toString(16)}`;
      if (to === VAULT && data === '0xpPlus()') return `0x${WAD.toString(16)}`;
      if (to === VAULT && data === '0xlastOraclePrice()') return `0x${WAD.toString(16)}`;
      throw new Error(`unexpected call ${to} ${data}`);
    });

    await resumeSavingsMints(VAULT, CUSD);

    const [{ calls }] = mockExecuteSponsoredBatch.mock.calls[0];
    expect(calls).toHaveLength(1);
    expect(calls[0].data).toContain('unwrapToCusd(uint256,uint256,address)');
  });
});
