import { deriveIntentId } from '../evmWallet';
import { encodeBuyStockCall, encodeSellStockCall, GmRouterQuote } from '../ondoStocksAbi';

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
  });
});
