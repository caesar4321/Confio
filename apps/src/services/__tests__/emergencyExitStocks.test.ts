const word = (value: bigint | number) => BigInt(value).toString(16).padStart(64, '0');

/** ABI result for Multicall3.tryAggregate: (bool,bytes)[] */
const multicallBalances = (balances: bigint[], successes = balances.map(() => true)): string => {
  const headsBytes = balances.length * 32;
  const offsets = balances.map((_, index) => word(headsBytes + index * 128)).join('');
  const tuples = balances.map((balance, index) =>
    word(successes[index] ? 1 : 0) + word(64) + word(32) + word(balance),
  ).join('');
  return '0x' + word(32) + word(balances.length) + offsets + tuples;
};

describe('Ondo balance Multicall ABI', () => {
  it('uses the canonical tryAggregate selector and decodes tuple results', () => {
    jest.resetModules();
    const mod = require('../emergencyExit/bscExit');
    const encoded = mod.encodeStockBalanceMulticall('0x' + '11'.repeat(20), [
      { address: '0x' + 'aa'.repeat(20) },
      { address: '0x' + 'bb'.repeat(20) },
    ]);
    expect(encoded.startsWith('0xbce38bd7')).toBe(true);
    expect(mod.decodeStockBalanceMulticall(multicallBalances([7n, 0n]), 2)).toEqual([7n, 0n]);
  });

  it('fails closed when any official token balance call fails', () => {
    jest.resetModules();
    const mod = require('../emergencyExit/bscExit');
    expect(() => mod.decodeStockBalanceMulticall(
      multicallBalances([7n, 0n], [true, false]),
      2,
    )).toThrow('Ondo balance call failed');
  });

  it('reads the 442-token release registry in exactly two chunks', async () => {
    jest.resetModules();
    jest.dontMock('../../config/ondoStockTokens.generated');
    let calls = 0;
    jest.doMock('../evmWallet', () => ({
      bscEthCall: async () => multicallBalances(Array(calls++ === 0 ? 250 : 192).fill(0n)),
      selector: (signature: string) =>
        signature === 'tryAggregate(bool,(address,bytes)[])' ? '0xbce38bd7' : '0x70a08231',
      encodeAddress: (address: string) => address.slice(2).padStart(64, '0'),
      isOutcomeUnknown: (error: any) => Boolean(error?.broadcast),
    }));
    const mod = require('../emergencyExit/bscExit');
    await expect(mod.readBundledOndoStockHoldings('0x' + '11'.repeat(20))).resolves.toEqual([]);
    expect(calls).toBe(2);
  });
});

describe('Emergency Exit Ondo Stocks', () => {
  const WALLET = { address: '0x' + '11'.repeat(20), privKeyHex: '00' } as any;
  const DEST = '0x' + '22'.repeat(20);
  const VAULT = '0x' + '33'.repeat(20);
  const STOCK_A = '0x' + 'aa'.repeat(20);
  const STOCK_B = '0x' + 'bb'.repeat(20);

  const memStore = () => {
    const map = new Map<string, string>();
    return {
      map,
      get: async (key: string) => map.get(key) ?? null,
      set: async (key: string, value: string) => { map.set(key, value); },
      del: async (key: string) => { map.delete(key); },
    };
  };

  const load = (sendCall: jest.Mock = jest.fn(async () => ({
    status: '0x1', transactionHash: '0x' + 'ab'.repeat(32), blockNumber: '0x1', logs: [],
  })), stockBalances: bigint[] = [5n, 0n], getReceipt: () => any = () => null) => {
    jest.resetModules();
    jest.doMock('../../config/ondoStockTokens.generated', () => ({
      BUNDLED_ONDO_STOCK_TOKENS: [
        { symbol: 'AAAon', address: STOCK_A },
        { symbol: 'BBBon', address: STOCK_B },
      ],
    }));
    jest.doMock('../evmWallet', () => ({
      bscBnbBalance: async () => 0n,
      bscGasPrice: async () => 100_000_000n,
      bscGetTransactionReceipt: async () => getReceipt(),
      bscEthCall: async (to: string) =>
        to.toLowerCase() === '0xca11bde05977b3631167028862be2a173976ca11'.toLowerCase()
          ? multicallBalances(stockBalances)
          : '0x' + '0'.repeat(64),
      sendCall,
      selector: (signature: string) => signature === 'transfer(address,uint256)' ? '0xa9059cbb' : '0x70a08231',
      encodeUint: (value: bigint) => value.toString(16).padStart(64, '0'),
      encodeAddress: (address: string) => address.slice(2).padStart(64, '0'),
      isOutcomeUnknown: (error: any) => Boolean(error?.broadcast),
      setBscTransport: () => {},
    }));
    return { mod: require('../emergencyExit/bscExit'), sendCall };
  };

  it('budgets redeem fallback and compliance-aware stock gas', async () => {
    const { mod } = load();
    const plan = {
      cusdPlusShares: 1n,
      usdtWei: 1n,
      confioWei: 1n,
      bnbWei: 0n,
      ondoStocks: [
        { symbol: 'AAAon', address: STOCK_A, balanceWei: 1n },
        { symbol: 'BBBon', address: STOCK_B, balanceWei: 1n },
      ],
      steps: ['redeemCusdPlus', 'transferUsdt', 'transferConfio', 'transferOndoStocks'],
    };
    // 1.38m gas units × 0.12 gwei (floor plus 20% headroom).
    await expect(mod.estimateBscExitGasWei(plan)).resolves.toBe(165_600_000_000_000n);
  });

  it('discovers only positive balances from the bundled allowlist', async () => {
    const { mod } = load();
    await expect(mod.readBundledOndoStockHoldings(WALLET.address)).resolves.toEqual([
      { symbol: 'AAAon', address: STOCK_A, balanceWei: 5n },
    ]);
  });

  it('transfers an official stock directly and checkpoints its address', async () => {
    const { mod, sendCall } = load();
    const result = await mod.executeBscExit({
      wallet: WALLET,
      dest: DEST,
      vaultAddress: VAULT,
      minUsdtOutWei: 0n,
      accountKey: 'personal__0',
      store: memStore(),
    });

    expect(sendCall).toHaveBeenCalledTimes(1);
    expect(sendCall.mock.calls[0][0]).toMatchObject({ to: STOCK_A });
    expect(sendCall.mock.calls[0][0].gasLimit).toBeUndefined();
    expect(sendCall.mock.calls[0][0].data).toContain(word(5n));
    expect(result.sentNow).toEqual([`ondoStock:AAAon:${STOCK_A}`]);
  });

  it('stops after a broadcast stock timeout instead of advancing to another nonce', async () => {
    const timeout = Object.assign(new Error('bsc tx timeout: 0x1234'), {
      broadcast: true,
      txHash: '0x1234',
    });
    const send = jest.fn(async () => { throw timeout; });
    let mined: any = null;
    const balances = [5n, 6n];
    const { mod } = load(send, balances, () => mined);
    const store = memStore();

    await expect(mod.executeBscExit({
      wallet: WALLET,
      dest: DEST,
      vaultAddress: VAULT,
      minUsdtOutWei: 0n,
      accountKey: 'personal__0',
      store,
    })).rejects.toBe(timeout);
    expect(send).toHaveBeenCalledTimes(1);

    // Reopening the flow cannot bypass an unresolved broadcast checkpoint.
    await expect(mod.executeBscExit({
      wallet: WALLET,
      dest: DEST,
      vaultAddress: VAULT,
      minUsdtOutWei: 0n,
      accountKey: 'personal__0',
      store,
    })).rejects.toMatchObject({ broadcast: true, txHash: '0x1234' });
    expect(send).toHaveBeenCalledTimes(1);

    // Once mined, reconciliation records the original hash and proceeds
    // without broadcasting the same stock transfer again.
    mined = { status: '0x1', transactionHash: '0x1234', blockNumber: '0x1', logs: [] };
    balances[0] = 0n;
    balances[1] = 0n;
    const reconciled = await mod.executeBscExit({
      wallet: WALLET,
      dest: DEST,
      vaultAddress: VAULT,
      minUsdtOutWei: 0n,
      accountKey: 'personal__0',
      store,
    });
    expect(send).toHaveBeenCalledTimes(1);
    expect(reconciled.txids[`ondoStock:AAAon:${STOCK_A}`]).toBe('0x1234');
  });

  it('restores the normal transport when checkpoint storage cannot be read', async () => {
    jest.resetModules();
    jest.doMock('../../config/ondoStockTokens.generated', () => ({ BUNDLED_ONDO_STOCK_TOKENS: [] }));
    const setTransport = jest.fn();
    jest.doMock('../evmWallet', () => ({
      sendCall: jest.fn(),
      selector: () => '0x70a08231',
      encodeUint: (value: bigint) => value.toString(16).padStart(64, '0'),
      encodeAddress: (address: string) => address.slice(2).padStart(64, '0'),
      isOutcomeUnknown: (error: any) => Boolean(error?.broadcast),
      setBscTransport: setTransport,
    }));
    const mod = require('../emergencyExit/bscExit');
    const storageError = new Error('storage unavailable');

    await expect(mod.executeBscExit({
      wallet: WALLET,
      dest: DEST,
      vaultAddress: VAULT,
      minUsdtOutWei: 0n,
      accountKey: 'personal__0',
      store: { get: async () => { throw storageError; }, set: async () => {}, del: async () => {} },
    })).rejects.toBe(storageError);
    expect(setTransport).toHaveBeenLastCalledWith(null);
  });
});
