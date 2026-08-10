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

jest.mock('../../apollo/client', () => ({ apolloClient: { query: mockQuery, mutate: mockMutate } }));
jest.mock('../bscServerRpc', () => ({ installBscServerTransport: jest.fn() }));
jest.mock('../evmWallet', () => ({ encodeCall: jest.fn(() => '0xapprove') }));
jest.mock('../ondoStocksAbi', () => ({
  encodeBuyStockCall: jest.fn(() => '0xbuy'),
  encodeSellStockCall: jest.fn(() => '0xsell'),
}));
jest.mock('../secureDeterministicWallet', () => ({
  getActiveEvmWallet: jest.fn(async () => ({ address: mockUserAddress })),
}));
jest.mock('../sponsored7702', () => ({
  fetchSponsored7702Params: jest.fn(async () => ({ enabled: true, delegateAddress: mockDelegateAddress })),
  executeSponsoredBatch: (...args: unknown[]) => mockExecuteSponsoredBatch(...args),
}));
jest.mock('../cusdPlusVault', () => ({
  getErc20Allowance: jest.fn(async () => (1n << 256n) - 1n),
  getErc20BalanceWei: (...args: unknown[]) => mockGetErc20BalanceWei(...args),
  getVaultPrices: jest.fn(async () => ({ pPlusWad: 10n ** 18n, oraclePriceWad: 10n ** 18n })),
  getVaultShares: jest.fn(),
  predictRedeemUsdtOut: jest.fn(),
  predictSubscribeSharesOut: jest.fn((amount: bigint) => amount),
  sharesForUsdtOut: jest.fn(),
}));

import { sellStockToSavings } from '../ondoStocks';

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
      },
    });
    mockGetErc20BalanceWei.mockResolvedValue(100n * WAD);
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
    expect(mockMutate.mock.calls[1][0].variables.notionalValue).toBe('200');
    expect(result.tokenAmountWei).toBe(100n * WAD);
    expect(mockExecuteSponsoredBatch).toHaveBeenCalledTimes(1);
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
