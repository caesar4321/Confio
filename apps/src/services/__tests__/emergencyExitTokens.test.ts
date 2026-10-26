// Emergency Exit beyond Ondo's compiled list: the crypto & metals list
// (Bitcoin, gold…) and the tokens this device saw the member hold.

export {};

const word = (value: bigint | number) => BigInt(value).toString(16).padStart(64, '0');
const multicallBalances = (balances: bigint[], successes = balances.map(() => true)): string => {
  const headsBytes = balances.length * 32;
  const offsets = balances.map((_, index) => word(headsBytes + index * 128)).join('');
  const tuples = balances.map((balance, index) =>
    word(successes[index] ? 1 : 0) + word(64) + word(32) + word(balance),
  ).join('');
  return '0x' + word(32) + word(balances.length) + offsets + tuples;
};

const STOCK = '0x' + 'aa'.repeat(20);
const BTCB = '0x' + 'b7'.repeat(20);
const NEW_STOCK = '0x' + 'cc'.repeat(20);
const USDT = '0x55d398326f99059fF775485246999027B3197955';
const WALLET = '0x' + '11'.repeat(20);
const LATER_CRYPTO = '0x' + 'b8'.repeat(20);

const memStore = () => {
  const map = new Map<string, string>();
  return {
    map,
    get: async (key: string) => map.get(key) ?? null,
    set: async (key: string, value: string) => { map.set(key, value); },
    del: async (key: string) => { map.delete(key); },
  };
};

const ONDO_BEACON = '0xc046b05a920e4b412815934dd8e58904dda73315';
const OTHER = '0x' + 'dd'.repeat(20);
// A stand-in for Ondo's proxy runtime code, and the hash the exit expects.
const ONDO_PROXY_CODE = '0x6080604052' + 'ab'.repeat(40);
const codeHash = (code: string) => {
  const { keccak_256 } = jest.requireActual('@noble/hashes/sha3');
  const { bytesToHex, hexToBytes } = jest.requireActual('@noble/hashes/utils');
  return '0x' + bytesToHex(keccak_256(hexToBytes(code.slice(2))));
};

const load = (opts: {
  balances?: (tokens: string[]) => { values: bigint[]; ok?: boolean[] };
  beacons?: Record<string, string>;
  codes?: Record<string, string>;
  single?: (token: string) => string;
} = {}) => {
  jest.resetModules();
  jest.doMock('../../config/ondoBeacons', () => ({
    ONDO_GM_BEACONS: [ONDO_BEACON],
    ONDO_GM_PROXY_CODE_HASHES: [codeHash(ONDO_PROXY_CODE)],
  }));
  jest.doMock('../../config/ondoStockTokens.generated', () => ({
    BUNDLED_ONDO_STOCK_TOKENS: [{ symbol: 'AAAon', address: STOCK }],
  }));
  jest.doMock('../../config/cryptoTokens.generated', () => ({
    BUNDLED_CRYPTO_TOKENS: [{ symbol: 'BTCB', address: BTCB }],
  }));
  const multicall = '0xca11bde05977b3631167028862be2a173976ca11';
  jest.doMock('../evmWallet', () => ({
    bscEthCall: async (to: string, data: string) => {
      if (to.toLowerCase() !== multicall) {
        if (opts.single) return opts.single(to.toLowerCase());
        return '0x' + word(4);
      }
      const tokens = [STOCK, BTCB, NEW_STOCK, OTHER].filter((t) => data.includes(t.slice(2)));
      const read = opts.balances ?? ((t: string[]): { values: bigint[]; ok?: boolean[] } => ({ values: t.map(() => 3n) }));
      const { values, ok } = read(tokens);
      return multicallBalances(values, ok);
    },
    bscGetCode: async (address: string) => opts.codes?.[address.toLowerCase()] ?? ONDO_PROXY_CODE,
    bscGetStorageAt: async (address: string) =>
      '0x' + (opts.beacons?.[address.toLowerCase()] ?? ONDO_BEACON).slice(2).padStart(64, '0'),
    selector: (signature: string) =>
      signature === 'tryAggregate(bool,(address,bytes)[])' ? '0xbce38bd7' : '0x70a08231',
    encodeAddress: (address: string) => address.slice(2).padStart(64, '0'),
    isOutcomeUnknown: () => false,
  }));
  return { mod: require('../emergencyExit/bscExit') };
};

describe('Emergency Exit token universe', () => {
  it('covers gold & Bitcoin and remembered stocks, never the dollars it handles itself', () => {
    const { mod } = load();
    const universe = mod.exitTokenUniverse([
      { symbol: 'NEWon', address: NEW_STOCK.toUpperCase().replace('0X', '0x'), kind: 'ondo' },
      { symbol: 'AAAon', address: STOCK, kind: 'ondo' }, // already compiled in
      { symbol: 'USDT', address: USDT, kind: 'ondo' }, // the exit's own leg
      { symbol: 'NEWC', address: OTHER, kind: 'crypto' }, // crypto is compiled in full only
    ], '', '0x' + '3c'.repeat(20));
    expect(universe).toEqual([
      { symbol: 'AAAon', address: STOCK, kind: 'ondo' },
      { symbol: 'BTCB', address: BTCB, kind: 'crypto' },
      { symbol: 'NEWon', address: NEW_STOCK, kind: 'ondo', remembered: true },
    ]);
  });

  it('reads them all, tagging each kind; a remembered stock on Ondo\'s beacon is admitted', async () => {
    const { mod } = load();
    const held = await mod.readBundledOndoStockHoldings(WALLET, mod.exitTokenUniverse([
      { symbol: 'NEWon', address: NEW_STOCK, kind: 'ondo' },
    ]));
    expect(held).toEqual([
      { symbol: 'AAAon', address: STOCK, kind: 'ondo', balanceWei: 3n },
      { symbol: 'BTCB', address: BTCB, kind: 'crypto', balanceWei: 3n },
      { symbol: 'NEWon', address: NEW_STOCK, kind: 'ondo', balanceWei: 4n, remembered: true },
    ]);
  });

  it('a remembered address that is not an Ondo token, or does not answer, is skipped; never the exit', async () => {
    const remembered = [
      { symbol: 'FAKEon', address: NEW_STOCK, kind: 'ondo' as const },
      { symbol: 'BADon', address: OTHER, kind: 'ondo' as const },
    ];
    const { mod } = load({
      beacons: { [NEW_STOCK]: '0x' + 'ee'.repeat(20) }, // not Ondo's code
      single: (token) => { if (token === OTHER) throw new Error('reverted'); return '0x' + word(9); },
    });
    const held = await mod.readBundledOndoStockHoldings(WALLET, mod.exitTokenUniverse(remembered));
    expect(held.map((h: any) => h.symbol)).toEqual(['AAAon', 'BTCB']);
  });

  it('arbitrary code that writes Ondo\'s beacon into its slot is not admitted', async () => {
    const { mod } = load({ codes: { [NEW_STOCK]: '0x6080604052' + 'cd'.repeat(40) } });
    const held = await mod.readBundledOndoStockHoldings(WALLET, mod.exitTokenUniverse([
      { symbol: 'FAKEon', address: NEW_STOCK, kind: 'ondo' },
    ]));
    expect(held.map((h: any) => h.symbol)).toEqual(['AAAon', 'BTCB']);
  });

  it('a compiled token that does not answer still fails the read (never counted as zero)', async () => {
    const { mod } = load({ balances: (tokens) => ({ values: tokens.map(() => 2n), ok: tokens.map((t) => t !== BTCB) }) });
    await expect(mod.readBundledOndoStockHoldings(WALLET, mod.exitTokenUniverse()))
      .rejects.toThrow('Ondo balance call failed');
  });
});

describe('held-token memory', () => {
  it('adds new tokens once, ignores malformed ones, and survives a bad stored value', async () => {
    jest.resetModules();
    const { rememberHeldTokens, loadHeldTokens } = require('../emergencyExit/heldTokens');
    const store = memStore();
    await rememberHeldTokens(store, [
      { symbol: 'NEWon', address: NEW_STOCK.toUpperCase().replace('0X', '0x'), kind: 'ondo' },
      { symbol: 'NEWC', address: LATER_CRYPTO, kind: 'crypto' },
      { symbol: 'bad symbol!', address: STOCK, kind: 'ondo' },
      { symbol: 'X', address: '0x123', kind: 'ondo' },
      { symbol: 'Y', address: STOCK, kind: 'other' },
    ]);
    // Already compiled into the exit: never stored.
    const { BUNDLED_ONDO_STOCK_TOKENS } = require('../../config/ondoStockTokens.generated');
    await rememberHeldTokens(store, [{ symbol: 'AALon', address: BUNDLED_ONDO_STOCK_TOKENS[0].address, kind: 'ondo' }]);
    const writes = store.map.size;
    await rememberHeldTokens(store, [{ symbol: 'NEWon', address: NEW_STOCK, kind: 'ondo' }]);
    expect(store.map.size).toBe(writes);
    expect(await loadHeldTokens(store)).toEqual([
      { symbol: 'NEWon', address: NEW_STOCK, kind: 'ondo' },
      { symbol: 'NEWC', address: LATER_CRYPTO, kind: 'crypto' },
    ]);
    store.map.set('confio_emergency_held_tokens_v1', 'not json');
    expect(await loadHeldTokens(store)).toEqual([]);
  });

  it('two reports at once keep both tokens', async () => {
    jest.resetModules();
    const { rememberHeldTokens, loadHeldTokens } = require('../emergencyExit/heldTokens');
    const store = memStore();
    await Promise.all([
      rememberHeldTokens(store, [{ symbol: 'NEWon', address: NEW_STOCK, kind: 'ondo' }]),
      rememberHeldTokens(store, [{ symbol: 'NEWC', address: LATER_CRYPTO, kind: 'crypto' }]),
    ]);
    expect((await loadHeldTokens(store)).map((t: any) => t.symbol).sort()).toEqual(['NEWC', 'NEWon']);
  });

  it('keeps the newest hundred', async () => {
    jest.resetModules();
    const { rememberHeldTokens, loadHeldTokens } = require('../emergencyExit/heldTokens');
    const store = memStore();
    const many = Array.from({ length: 105 }, (_, i) => ({
      symbol: `T${i}on`, address: '0x' + i.toString(16).padStart(40, 'f'), kind: 'ondo',
    }));
    await rememberHeldTokens(store, many);
    const kept = await loadHeldTokens(store);
    expect(kept).toHaveLength(100);
    expect(kept[0].symbol).toBe('T5on');
    expect(kept[99].symbol).toBe('T104on');
  });
});
