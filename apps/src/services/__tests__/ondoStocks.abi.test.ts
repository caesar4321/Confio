import { deriveIntentId, selector } from '../evmWallet';
import {
  encodeBuyStockCall,
  encodeSellStockCall,
  GmRouterQuote,
} from '../ondoStocksAbi';

const quote: GmRouterQuote = {
  attestationId: '123',
  userId: '0x' + '44'.repeat(32),
  chainId: '56',
  assetAddress: '0x' + '55'.repeat(20),
  side: '0',
  tokenAmount: String(2n * 10n ** 18n),
  price: String(300n * 10n ** 18n),
  expiration: 2_000_000_000,
  signatureHex: '0x' + '66'.repeat(65),
  additionalDataHex: '0x' + '00'.repeat(32),
};

const wordAt = (calldata: string, word: number): bigint => {
  const body = calldata.slice(10);
  return BigInt('0x' + body.slice(word * 64, (word + 1) * 64));
};

describe('Ondo stock router ABI', () => {
  it('encodes the buy dynamic signature at the canonical 14-word offset', () => {
    const data = encodeBuyStockCall(
      quote, 602n * 10n ** 18n, 600n * 10n ** 18n, 601n * 10n ** 18n, 30n,
    );
    expect(wordAt(data, 9)).toBe(14n * 32n);
    expect(wordAt(data, 14)).toBe(65n);
    expect(data.slice(10 + (15 * 64), 10 + (15 * 64) + 130)).toBe('66'.repeat(65));
    expect(deriveIntentId([{ to: '0x' + '11'.repeat(20), valueWei: 0n, data }])).toBe(
      '0x0463ba002179f7ceb9a82a89e9a8ea5433c907f27c11647519fab24160388014',
    );
  });

  it('encodes sell at the canonical 13-word offset and derives sell intent', () => {
    const sellQuote = { ...quote, side: '1' };
    const data = encodeSellStockCall(sellQuote, 590n * 10n ** 18n, 588n * 10n ** 18n, 30n);
    expect(wordAt(data, 9)).toBe(13n * 32n);
    expect(wordAt(data, 13)).toBe(65n);
    expect(deriveIntentId([{ to: '0x' + '11'.repeat(20), valueWei: 0n, data }])).toBe(
      '0x036789f1bf207cc331303995ee763597e87d887895b66f220a3f8cf0f0fe69de',
    );
    const requestBound = deriveIntentId(
      [{ to: '0x' + '11'.repeat(20), valueWei: 0n, data }],
      'gm_0123456789abcdef0123456789abcdef_a0',
    );
    expect(requestBound).not.toBe(
      deriveIntentId([{ to: '0x' + '11'.repeat(20), valueWei: 0n, data }]),
    );
    expect(requestBound).toBe(deriveIntentId(
      [{ to: '0x' + '11'.repeat(20), valueWei: 0n, data }],
      'gm_0123456789abcdef0123456789abcdef_a0',
    ));
  });
});

describe('cUSD rail intent parity', () => {
  const intentFor = (signature: string): string => deriveIntentId([{
    to: '0x' + '11'.repeat(20),
    valueWei: 0n,
    data: selector(signature),
  }]);

  it('matches the server kinds for fee-free internal conversions', () => {
    expect(intentFor('wrapCusd(uint256,uint256,address)')).toBe(
      '0xe20ab42d131e776a4be1d3cf2b15431b4f9903bfa3742c9808d71b821b04f08f',
    );
    expect(intentFor('unwrapToCusd(uint256,uint256,address)')).toBe(
      '0x0fd51316f246a59f873be2bdd5b5d7e625d5011b21e58b1e4acbba9f648894c8',
    );
  });

  it('matches the server kinds for fee-bearing cUSD mint and redeem', () => {
    expect(intentFor('mintWithFee(uint256,uint256,address)')).toBe(
      '0x7c1868ae2dd041e6c12c7c97c5aed2860e230e29b354f49450c5d1a4a97103fb',
    );
    expect(intentFor('redeemWithFee(uint256,uint256,address)')).toBe(
      '0x7b542b59c64007e300b1b692521eba93c6010468a5c3618075414a094322aea6',
    );
  });
});
