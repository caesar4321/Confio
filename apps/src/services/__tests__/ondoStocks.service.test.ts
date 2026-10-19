const WAD = 10n ** 18n;
const VAULT = `0x${'11'.repeat(20)}`;
const ROUTER = `0x${'22'.repeat(20)}`;
const STOCK = `0x${'33'.repeat(20)}`;
const mockUserAddress = `0x${'44'.repeat(20)}`;
const mockDelegateAddress = `0x${'55'.repeat(20)}`;

const mockQuery = jest.fn();
const mockMutate = jest.fn();
const mockExecuteSponsoredBatch = jest.fn();
const mockGetErc20BalanceWei = jest.fn();
const mockGetVaultPrices = jest.fn();

jest.mock('../../apollo/client', () => ({ apolloClient: { query: mockQuery, mutate: mockMutate } }));
jest.mock('../bscServerRpc', () => ({ installBscServerTransport: jest.fn() }));
jest.mock('../evmWallet', () => ({
  encodeCall: jest.fn(() => '0xapprove'),
}));
jest.mock('../ondoStocksAbi', () => ({
  encodeBuyStockCall: jest.fn(() => '0xbuy'),
  encodeSellStockCall: jest.fn(() => '0xsell'),
}));
jest.mock('../secureDeterministicWallet', () => ({
  getActiveEvmWallet: jest.fn(async () => ({ address: mockUserAddress })),
}));
jest.mock('../sponsored7702', () => ({
  createSponsoredRequestId: jest.fn(() => 'gm_0123456789abcdef0123456789abcdef'),
  fetchSponsored7702Params: jest.fn(async () => ({ enabled: true, delegateAddress: mockDelegateAddress })),
  executeSponsoredBatch: (...args: unknown[]) => mockExecuteSponsoredBatch(...args),
}));
jest.mock('../cusdPlusVault', () => ({
  getErc20Allowance: jest.fn(async () => (1n << 256n) - 1n),
  getErc20BalanceWei: (...args: unknown[]) => mockGetErc20BalanceWei(...args),
  getVaultPrices: (...args: unknown[]) => mockGetVaultPrices(...args),
  getVaultShares: jest.fn(),
  predictRedeemUsdtOut: jest.fn(),
  predictSubscribeSharesOut: jest.fn((amount: bigint) => amount),
  sharesForUsdtOut: jest.fn(),
}));

import { buyStockWithSavings, friendlyTradeError, sellStockToSavings } from '../ondoStocks';

const quote = (tokenAmount: bigint) => ({
  success: true,
  attestationId: '1',
  userId: `0x${'66'.repeat(32)}`,
  chainId: '56',
  symbol: 'TSLAon',
  ticker: 'TSLA',
  assetAddress: STOCK,
  side: '1',
  tokenAmount: tokenAmount.toString(),
  price: (2n * WAD).toString(),
  expiration: Date.now() / 1000 + 300,
  signatureHex: `0x${'77'.repeat(65)}`,
  additionalDataHex: `0x${'00'.repeat(32)}`,
  notionalWei: (202n * WAD).toString(),
});

describe('Ondo Stocks sell orchestration', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockQuery.mockResolvedValue({
      data: {
        cusdPlusSummary: { stocksTradingEnabled: true },
        cusdPlusConvertParams: {
          vaultAddress: VAULT,
          stockRouterAddress: ROUTER,
          gmTradeFeeBps: 30,
        },
        stockFeePolicy: { feeBps: 30, mode: 'router' },
      },
    });
    mockGetErc20BalanceWei.mockResolvedValue(100n * WAD);
    mockGetVaultPrices.mockResolvedValue({ pPlusWad: WAD, oraclePriceWad: WAD });
    mockExecuteSponsoredBatch.mockResolvedValue({ txHash: `0x${'88'.repeat(32)}` });
  });

  it('requotes MAX from the exact on-chain balance instead of failing on display rounding', async () => {
    mockMutate
      .mockResolvedValueOnce({ data: { prepareGmTrade: { quote: quote(101n * WAD) } } })
      .mockResolvedValueOnce({ data: { prepareGmTrade: { quote: quote(100n * WAD) } } });

    const result = await sellStockToSavings({
      symbol: 'TSLAon',
      grossAmountUsd: 202,
      sellAll: true,
    });

    expect(mockMutate).toHaveBeenCalledTimes(2);
    expect(mockMutate.mock.calls[0][0].variables.requestId).toBe(
      'gm_0123456789abcdef0123456789abcdef_q0');
    expect(mockMutate.mock.calls[1][0].variables.requestId).toBe(
      'gm_0123456789abcdef0123456789abcdef_q1');
    expect(mockMutate.mock.calls[1][0].variables.notionalValue).toBe('200');
    expect(result.tokenAmountWei).toBe(100n * WAD);
    expect(mockExecuteSponsoredBatch).toHaveBeenCalledTimes(1);
    expect(mockExecuteSponsoredBatch.mock.calls[0][0].requestId).toBe(
      'gm_0123456789abcdef0123456789abcdef');
  });

  it('does not silently clamp a user-entered partial sell', async () => {
    mockMutate.mockResolvedValueOnce({ data: { prepareGmTrade: { quote: quote(101n * WAD) } } });

    await expect(sellStockToSavings({
      symbol: 'TSLAon',
      grossAmountUsd: 202,
      sellAll: false,
    })).rejects.toThrow('No tienes suficientes unidades');

    expect(mockMutate).toHaveBeenCalledTimes(1);
    expect(mockExecuteSponsoredBatch).not.toHaveBeenCalled();
  });

  it('requotes an underfill and requires MAX to converge to the exact balance', async () => {
    mockMutate
      .mockResolvedValueOnce({ data: { prepareGmTrade: { quote: quote(99n * WAD) } } })
      .mockResolvedValueOnce({ data: { prepareGmTrade: { quote: quote(100n * WAD) } } });

    const result = await sellStockToSavings({
      symbol: 'TSLAon',
      grossAmountUsd: 198,
      sellAll: true,
    });

    expect(result.tokenAmountWei).toBe(100n * WAD);
    expect(mockExecuteSponsoredBatch).toHaveBeenCalledTimes(1);
  });

  it('fails honestly when MAX cannot converge instead of reporting a partial exit', async () => {
    mockMutate.mockResolvedValue({
      data: { prepareGmTrade: { quote: quote(99n * WAD) } },
    });

    await expect(sellStockToSavings({
      symbol: 'TSLAon',
      grossAmountUsd: 198,
      sellAll: true,
    })).rejects.toThrow('calculábamos MAX');

    expect(mockMutate).toHaveBeenCalledTimes(3);
    expect(mockExecuteSponsoredBatch).not.toHaveBeenCalled();
  });
});

describe('Ondo Stocks sell minimum', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockQuery.mockResolvedValue({
      data: {
        cusdPlusSummary: { stocksTradingEnabled: true },
        cusdPlusConvertParams: { vaultAddress: VAULT, stockRouterAddress: ROUTER, gmTradeFeeBps: 30 },
        stockFeePolicy: { feeBps: 30, mode: 'router' },
      },
    });
    mockGetErc20BalanceWei.mockResolvedValue(100n * WAD);
    mockGetVaultPrices.mockResolvedValue({ pPlusWad: WAD, oraclePriceWad: WAD });
  });

  it('never sends a sale whose net lands under Ondo\'s US$1 deposit minimum', async () => {
    // 0.5 units at US$2 = US$1.00 gross, US$0.997 net: under the minimum.
    mockMutate.mockResolvedValueOnce({ data: { prepareGmTrade: { quote: quote(WAD / 2n) } } });
    await expect(sellStockToSavings({ symbol: 'TSLAon', grossAmountUsd: 1, sellAll: false }))
      .rejects.toThrow('al menos US$1.00');
    expect(mockExecuteSponsoredBatch).not.toHaveBeenCalled();
  });

  it('maps network refusals to copy a person can act on', () => {
    expect(friendlyTradeError(new Error('sponsored batch rejected: simulation_reverted'), 'sell'))
      .toContain('no se cobró nada');
    expect(friendlyTradeError(new Error('execution reverted: 0x67627d07'), 'sell')).toContain('US$1.00');
    expect(friendlyTradeError(new Error('Tu ahorro disponible no alcanza'), 'buy')).toBe('Tu ahorro disponible no alcanza');
  });
});

describe('Ondo Stocks fee policy (fee unification)', () => {
  const abi = jest.requireMock('../ondoStocksAbi');
  const vault = jest.requireMock('../cusdPlusVault');
  const configData = (policy: unknown) => ({
    data: {
      cusdPlusSummary: { stocksTradingEnabled: true },
      cusdPlusConvertParams: { vaultAddress: VAULT, stockRouterAddress: ROUTER, gmTradeFeeBps: 30 },
      stockFeePolicy: policy,
    },
  });
  const buyQuote = (notional: bigint) => ({ ...quote(1n * WAD), notionalWei: notional.toString() });

  beforeEach(() => {
    jest.clearAllMocks();
    mockGetVaultPrices.mockResolvedValue({ pPlusWad: WAD, oraclePriceWad: WAD });
    vault.getVaultShares.mockResolvedValue(1_000n * WAD);
    vault.sharesForUsdtOut.mockImplementation((usdt: bigint) => usdt);
    vault.predictRedeemUsdtOut.mockImplementation((shares: bigint) => shares);
    mockExecuteSponsoredBatch.mockResolvedValue({ txHash: `0x${'88'.repeat(32)}` });
  });

  it('v2 buy signs the live 0.9% cap with a net floor equal to the spend', async () => {
    mockQuery.mockResolvedValue(configData({ feeBps: 90, mode: 'perimeter' }));
    const spend = 99_100_000_000_000_000_000n;
    mockMutate.mockResolvedValueOnce({ data: { prepareGmTrade: { quote: buyQuote(spend) } } });

    const result = await buyStockWithSavings({ symbol: 'TSLAon', grossAmountUsd: 100 });

    // The binding request is for $100 minus the 0.9% exit fee.
    expect(mockMutate.mock.calls[0][0].variables.notionalValue).toBe('99.1');
    const [, shares, signedSpend, minUsdt, maxFee] = abi.encodeBuyStockCall.mock.calls[0];
    expect(maxFee).toBe(90n);
    expect(signedSpend).toBe(spend);
    expect(minUsdt).toBe(spend);
    expect(shares).toBe(100n * WAD); // redeems the full $100 gross
    expect(result.feeWei).toBe(9n * 10n ** 17n);
  });

  it('an older server without stockFeePolicy falls back to the legacy 30 bps router math', async () => {
    mockQuery.mockImplementation(async ({ query }: { query: any }) => {
      if (query.definitions[0].name.value === 'StockFeePolicy') throw new Error('Cannot query field');
      return configData(undefined);
    });
    const spend = 600n * WAD;
    mockMutate.mockResolvedValueOnce({ data: { prepareGmTrade: { quote: buyQuote(spend) } } });

    await buyStockWithSavings({ symbol: 'TSLAon', grossAmountUsd: 601.8 });

    const [, , , minUsdt, maxFee] = abi.encodeBuyStockCall.mock.calls[0];
    expect(maxFee).toBe(30n);
    expect(minUsdt).toBe(spend + (spend * 30n + 9969n) / 9970n);
  });

  it('screen fee lookup on an older server falls back to the legacy 30 bps field', async () => {
    mockQuery.mockImplementation(async ({ query }: { query: any }) => {
      if (query.definitions[0].name.value === 'StockFeePolicy') throw new Error('Cannot query field');
      return { data: { cusdPlusConvertParams: { gmTradeFeeBps: 30 } } };
    });
    // Fresh module: earlier trades in this file primed the 60 s policy cache.
    jest.resetModules();
    const fresh = jest.requireActual('../ondoStocks');
    await expect(fresh.getStockFeePolicy()).resolves.toEqual({ feeBps: 30n, mode: 'router' });
  });

  it('refuses to sign a fee other than the one the screen displayed', async () => {
    mockQuery.mockResolvedValue(configData({ feeBps: 90, mode: 'perimeter' }));
    await expect(buyStockWithSavings({ symbol: 'TSLAon', grossAmountUsd: 100, expectedFeeBps: 30n }))
      .rejects.toMatchObject({ code: 'FEE_CHANGED' });
    await expect(sellStockToSavings({ symbol: 'TSLAon', grossAmountUsd: 100, expectedFeeBps: 30n }))
      .rejects.toMatchObject({ code: 'FEE_CHANGED' });
    expect(mockMutate).not.toHaveBeenCalled();
    expect(mockExecuteSponsoredBatch).not.toHaveBeenCalled();
  });

  it('refuses to trade when the server reports no usable fee policy', async () => {
    mockQuery.mockResolvedValue(configData(null));
    await expect(buyStockWithSavings({ symbol: 'TSLAon', grossAmountUsd: 100 }))
      .rejects.toThrow('aún no está habilitada');
    expect(mockExecuteSponsoredBatch).not.toHaveBeenCalled();
  });
});
