const WAD = 10n ** 18n;
const VAULT = `0x${'11'.repeat(20)}`;
const CUSD = `0x${'12'.repeat(20)}`;
const ROUTER = `0x${'22'.repeat(20)}`;
const TOKEN = `0x${'33'.repeat(20)}`;
const mockUser = `0x${'44'.repeat(20)}`;
const mockDelegate = `0x${'55'.repeat(20)}`;
const ROUTE = '0x' + 'ab'.repeat(32);

const mockQuery = jest.fn();
const mockExecute = jest.fn();
const mockBalance = jest.fn();
const mockAllowance = jest.fn();
const mockPrices = jest.fn();
const mockShares = jest.fn();
const mockCurrentOracle = jest.fn();
const mockBuyEncode = jest.fn((..._args: any[]) => '0xbuy');
const mockSellEncode = jest.fn((..._args: any[]) => '0xsell');

jest.mock('../../apollo/client', () => ({ apolloClient: { query: (...a: any[]) => mockQuery(...a) } }));
jest.mock('../bscServerRpc', () => ({ installBscServerTransport: jest.fn() }));
jest.mock('../evmWallet', () => ({ encodeCall: jest.fn(() => '0xapprove') }));
jest.mock('../cryptoSwapAbi', () => ({
  encodeCryptoBuyCall: (...a: any[]) => mockBuyEncode(...a),
  encodeCryptoSellCall: (...a: any[]) => mockSellEncode(...a),
}));
jest.mock('../secureDeterministicWallet', () => ({ getActiveEvmWallet: jest.fn(async () => ({ address: mockUser })) }));
jest.mock('../sponsored7702', () => ({
  createSponsoredRequestId: jest.fn(() => 'gm_req'),
  fetchSponsored7702Params: jest.fn(async () => ({ enabled: true, delegateAddress: mockDelegate })),
  executeSponsoredBatch: (...a: any[]) => mockExecute(...a),
}));
jest.mock('../cusdPlusVault', () => ({
  getErc20Allowance: (...a: any[]) => mockAllowance(...a),
  getErc20BalanceWei: (...a: any[]) => mockBalance(...a),
  getVaultPrices: (...a: any[]) => mockPrices(...a),
  getCurrentOraclePrice: (...a: any[]) => mockCurrentOracle(...a),
  getVaultShares: (...a: any[]) => mockShares(...a),
  sharesForUsdtOut: (usdt: bigint, pps: bigint) => (usdt * WAD + pps - 1n) / pps + 2n,
}));

import {
  buyCrypto,
  CRYPTO_FEE_CHANGED_MESSAGE,
  cryptoErrorCode,
  cryptoTradeError,
  isCryptoAckRequired,
  sellCrypto,
  unitsForUsd,
  usdToWei,
} from '../cryptoTrading';

const caps = (over: Record<string, unknown> = {}) => ({
  enabled: true, tradingEnabled: true, buyEnabled: true, ackRequired: false, ackVersion: 1,
  disclosureTitle: 't', disclosurePoints: ['p'], fundingDollar: 'cusd', feeBps: 90, maxSlippageBps: 100,
  routerAddress: ROUTER, blockedMessage: null, ...over,
});

const answer = (capabilities: any, quote: any) => (opts: any) => {
  const name = opts.query.definitions[0].name.value;
  if (name === 'CryptoCapabilities') return Promise.resolve({ data: { cryptoCapabilities: capabilities } });
  if (name === 'CryptoDollarAddresses') {
    return Promise.resolve({ data: { cusdPlusConvertParams: { vaultAddress: VAULT, cusdAddress: CUSD } } });
  }
  if (name === 'CryptoQuote') return Promise.resolve({ data: { cryptoQuote: quote(opts.variables) } });
  throw new Error(`unexpected ${name}`);
};

const okQuote = (out: bigint) => (v: any) => ({
  success: true, amountIn: v.amountIn, expectedOut: out.toString(), route: ROUTE, poolFeeBps: 5, priceImpactBps: 8,
});

const ASSET = { symbol: 'BTCB', address: TOKEN, maxOrderUsd: null };

beforeEach(() => {
  jest.clearAllMocks();
  mockAllowance.mockResolvedValue(0n);
  mockBalance.mockResolvedValue(100n * WAD);
  mockPrices.mockResolvedValue({ pPlusWad: WAD, oraclePriceWad: WAD });
  mockShares.mockResolvedValue(100n * WAD);
  mockCurrentOracle.mockResolvedValue(WAD);
  mockExecute.mockResolvedValue({ txHash: '0xtx' });
});

describe('buyCrypto', () => {
  it('pays with cUSD: exact net exit floor, quote floor, approve + router call', async () => {
    mockQuery.mockImplementation(answer(caps(), okQuote(1_000_000n)));
    const result = await buyCrypto({ asset: ASSET, grossAmountUsd: 10, expectedFeeBps: 90, expectedFunding: 'cusd' });
    const args = mockBuyEncode.mock.calls[0][0];
    expect(args).toMatchObject({
      dollar: 1, amountIn: 10n * WAD, minUsdtOut: 9_910_000_000_000_000_000n,
      route: ROUTE, tokenOut: TOKEN, minTokenOut: 990_000n, maxFeeBps: 90n,
    });
    // Quoted on the NET after the fee, as the relay requotes it.
    const quoteCall = mockQuery.mock.calls.find((c) => c[0].variables?.amountIn);
    expect(quoteCall[0].variables).toMatchObject({ symbol: 'BTCB', side: 'buy', amountIn: '9910000000000000000' });
    const batch = mockExecute.mock.calls[0][0];
    expect(batch.calls.map((c: any) => c.to)).toEqual([CUSD, ROUTER]);
    expect(batch.delegateAddress).toBe(mockDelegate);
    expect(result).toMatchObject({ txHash: '0xtx', tokenOutUnits: 1_000_000n, netWei: 9_910_000_000_000_000_000n });
  });

  it('pays with cUSD+ shares and skips the approve when already allowed', async () => {
    mockQuery.mockImplementation(answer(caps({ fundingDollar: 'cusd_plus' }), okQuote(5n)));
    mockAllowance.mockResolvedValue((1n << 256n) - 1n);
    await buyCrypto({ asset: ASSET, grossAmountUsd: 10, expectedFeeBps: 90, expectedFunding: 'cusd_plus' });
    const args = mockBuyEncode.mock.calls[0][0];
    expect(args.dollar).toBe(0);
    expect(args.amountIn).toBe(10n * WAD + 2n);
    // gross = shares at pps 1 (double floor), net = gross − ceil fee.
    const gross = 10n * WAD + 2n;
    expect(args.minUsdtOut).toBe(gross - (gross * 90n + 9_999n) / 10_000n);
    expect(mockExecute.mock.calls[0][0].calls).toHaveLength(1);
  });

  it('refuses to sign when the fee changed since it was displayed', async () => {
    mockQuery.mockImplementation(answer(caps({ feeBps: 120 }), okQuote(5n)));
    await expect(buyCrypto({ asset: ASSET, grossAmountUsd: 10, expectedFeeBps: 90, expectedFunding: 'cusd' }))
      .rejects.toThrow(CRYPTO_FEE_CHANGED_MESSAGE);
    expect(mockExecute).not.toHaveBeenCalled();
  });

  it('refuses when the funding dollar changed', async () => {
    mockQuery.mockImplementation(answer(caps({ fundingDollar: 'cusd_plus' }), okQuote(5n)));
    await expect(buyCrypto({ asset: ASSET, grossAmountUsd: 10, expectedFeeBps: 90, expectedFunding: 'cusd' }))
      .rejects.toMatchObject({ code: 'FUNDING_CHANGED' });
  });

  it('caps the buy at maxOrderUsd', async () => {
    mockQuery.mockImplementation(answer(caps(), okQuote(5n)));
    await expect(buyCrypto({
      asset: { ...ASSET, maxOrderUsd: 5 }, grossAmountUsd: 10, expectedFeeBps: 90, expectedFunding: 'cusd',
    })).rejects.toMatchObject({ code: 'crypto_order_too_large' });
  });

  it('stops when the fresh quote fell below the preview by more than the slippage', async () => {
    mockQuery.mockImplementation(answer(caps(), okQuote(980_000n)));
    await expect(buyCrypto({
      asset: ASSET, grossAmountUsd: 10, expectedFeeBps: 90, expectedFunding: 'cusd', previewTokenOut: 1_000_000n,
    })).rejects.toMatchObject({ code: 'PRICE_MOVED' });
  });

  it('maps a failed quote to its Spanish copy', async () => {
    mockQuery.mockImplementation(answer(caps(), () => ({ success: false, errorCode: 'NOT_LISTED' })));
    await expect(buyCrypto({ asset: ASSET, grossAmountUsd: 10, expectedFeeBps: 90, expectedFunding: 'cusd' }))
      .rejects.toThrow('Este activo ya no está disponible para comprar.');
  });
});

describe('sellCrypto', () => {
  it('sells the exact balance on MAX into cUSD with the relay floors', async () => {
    mockQuery.mockImplementation(answer(caps(), okQuote(98_765_432_109_876_543_210n)));
    mockBalance.mockResolvedValue(777n);
    const result = await sellCrypto({
      asset: ASSET, units: 1n, sellAll: true, expectedFeeBps: 90, expectedFunding: 'cusd',
    });
    expect(mockSellEncode.mock.calls[0][0]).toMatchObject({
      dollar: 1, tokenIn: TOKEN, amountIn: 777n, route: ROUTE,
      minUsdtOut: 97_777_777_788_777_777_777n, minDestOut: 96_897_777_788_678_777_777n, maxFeeBps: 90n,
    });
    expect(mockExecute.mock.calls[0][0].calls.map((c: any) => c.to)).toEqual([TOKEN, ROUTER]);
    expect(result.unitsSold).toBe(777n);
  });

  it('refuses a cUSD+ sale under the mint floor but allows it into cUSD', async () => {
    mockQuery.mockImplementation(answer(caps({ fundingDollar: 'cusd_plus' }), okQuote(1_010_000_000_000_000_000n)));
    await expect(sellCrypto({ asset: ASSET, units: 5n, expectedFeeBps: 90, expectedFunding: 'cusd_plus' }))
      .rejects.toMatchObject({ code: 'savings_mint_too_small' });
    const into = await sellCrypto({
      asset: ASSET, units: 5n, expectedFeeBps: 90, expectedFunding: 'cusd_plus', intoCusd: true,
    });
    expect(into.dollar).toBe(1);
    expect(mockSellEncode.mock.calls[0][0].dollar).toBe(1);
  });

  it('never sells more than is held', async () => {
    mockQuery.mockImplementation(answer(caps(), okQuote(10n)));
    mockBalance.mockResolvedValue(4n);
    await expect(sellCrypto({ asset: ASSET, units: 5n, expectedFeeBps: 90, expectedFunding: 'cusd' }))
      .rejects.toThrow('No tienes suficiente');
  });
});

describe('relay refusal copy', () => {
  const relay = (code: string) => new Error(`sponsored batch rejected: ${code}`);
  it.each([
    'crypto_ack_required', 'trade_not_available', 'savings_not_available', 'savings_mint_too_small',
    'crypto_order_too_large', 'bad_crypto_floor', 'crypto_quote_unavailable', 'crypto_trading_disabled',
    'token_not_listed',
  ])('maps %s to Spanish copy', (code) => {
    expect(cryptoErrorCode(relay(code))).toBe(code);
    const copy = cryptoTradeError(relay(code), 'buy');
    expect(copy).not.toMatch(/sponsored|_/);
    expect(copy.length).toBeGreaterThan(10);
  });

  it('recognises the risk-confirmation refusal', () => {
    expect(isCryptoAckRequired(relay('crypto_ack_required'))).toBe(true);
    expect(isCryptoAckRequired(relay('bad_crypto_floor'))).toBe(false);
  });
});

describe('unitsForUsd', () => {
  it('maps a dollar amount to units, never above the position', () => {
    expect(unitsForUsd(1_000_000n, 100, 25)).toBe(250_000n);
    expect(unitsForUsd(1_000_000n, 100, 150)).toBe(1_000_000n);
    expect(unitsForUsd(1_000_000n, 0, 10)).toBe(0n);
  });
});

describe('Codex follow-ups', () => {
  it('P1: a buy signs the floor of the DISPLAYED quote when the fresh one is within slippage', async () => {
    mockQuery.mockImplementation(answer(caps(), okQuote(991_000n)));
    await buyCrypto({
      asset: ASSET, grossAmountUsd: 10, expectedFeeBps: 90, expectedFunding: 'cusd', previewTokenOut: 1_000_000n,
    });
    expect(mockBuyEncode.mock.calls[0][0].minTokenOut).toBe(990_000n); // not 981_090
  });

  it('P1: a sale signs the displayed USDT floor, and refuses when the fresh quote is under it', async () => {
    mockQuery.mockImplementation(answer(caps(), okQuote(991n * 10n ** 16n)));
    await sellCrypto({
      asset: ASSET, units: 5n, expectedFeeBps: 90, expectedFunding: 'cusd', previewUsdtOut: 10n * WAD,
    });
    expect(mockSellEncode.mock.calls[0][0].minUsdtOut).toBe(99n * 10n ** 17n);

    mockQuery.mockImplementation(answer(caps(), okQuote(98n * 10n ** 17n)));
    await expect(sellCrypto({
      asset: ASSET, units: 5n, expectedFeeBps: 90, expectedFunding: 'cusd', previewUsdtOut: 10n * WAD,
    })).rejects.toMatchObject({ code: 'PRICE_MOVED' });
    expect(mockSellEncode).toHaveBeenCalledTimes(1);
  });

  it('P1: a sale needs only the holding (address + symbol), no market', async () => {
    mockQuery.mockImplementation(answer(caps({ enabled: false, buyEnabled: false }), okQuote(10n * WAD)));
    const holding = { symbol: 'ETH', address: `0x${'99'.repeat(20)}` };
    await sellCrypto({ asset: holding, units: 5n, expectedFeeBps: 90, expectedFunding: 'cusd' });
    expect(mockSellEncode.mock.calls[0][0].tokenIn).toBe(holding.address);
    const quoteCall = mockQuery.mock.calls.find((c) => c[0].variables?.side === 'sell');
    expect(quoteCall[0].variables.symbol).toBe('ETH');
  });

  it('P2: cUSD+ sale floors mint at the current oracle, not lastOraclePrice', async () => {
    mockQuery.mockImplementation(answer(caps({ fundingDollar: 'cusd_plus' }), okQuote(13n * WAD)));
    const pps = 1_010_000_000_000_000_000n;
    const current = 1_120_100_000_000_000_000n;
    mockPrices.mockResolvedValue({ pPlusWad: pps, oraclePriceWad: 1_120_000_000_000_000_000n });
    mockCurrentOracle.mockResolvedValue(current);
    await sellCrypto({ asset: ASSET, units: 5n, expectedFeeBps: 90, expectedFunding: 'cusd_plus' });
    expect(mockCurrentOracle).toHaveBeenCalledWith(VAULT);
    const { minUsdtOut, minDestOut } = mockSellEncode.mock.calls[0][0];
    const entry = minUsdtOut - (minUsdtOut * 90n + 9_999n) / 10_000n;
    const shares = ((entry * WAD) / current) * current / pps;
    expect(minDestOut).toBe((shares * 9_999n) / 10_000n);
  });

  it('P2: dollars convert to wei without binary-float error', async () => {
    expect(usdToWei(1.1)).toBe(1_100_000_000_000_000_000n);
    expect(usdToWei('1.1')).toBe(1_100_000_000_000_000_000n);
    expect(usdToWei(0.07)).toBe(70_000_000_000_000_000n);
    expect(usdToWei(123456.78)).toBe(123_456_780_000_000_000_000_000n);
    expect(usdToWei(-1)).toBe(0n);
    mockQuery.mockImplementation(answer(caps(), okQuote(5n)));
    await buyCrypto({ asset: ASSET, grossAmountUsd: 1.1, expectedFeeBps: 90, expectedFunding: 'cusd' });
    expect(mockBuyEncode.mock.calls[0][0].amountIn).toBe(1_100_000_000_000_000_000n);
  });

  it('returns the signed fee rate for a frozen receipt', async () => {
    mockQuery.mockImplementation(answer(caps(), okQuote(10n * WAD)));
    const sold = await sellCrypto({ asset: ASSET, units: 5n, expectedFeeBps: 90, expectedFunding: 'cusd' });
    expect(sold).toMatchObject({ feeBps: 90, feeWei: 9n * 10n ** 16n });
  });
});
