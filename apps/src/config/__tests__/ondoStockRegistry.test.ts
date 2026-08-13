import {
  BUNDLED_ONDO_STOCK_COUNT,
  BUNDLED_ONDO_STOCK_SOURCE_SHA256,
  BUNDLED_ONDO_STOCK_TOKENS,
} from '../ondoStockTokens.generated';

declare const __dirname: string;
const { createHash } = require('crypto');
const { readFileSync } = require('fs');
const { resolve } = require('path');

describe('bundled Ondo Stocks registry', () => {
  it('contains the reviewed canonical BSC snapshot', () => {
    expect(BUNDLED_ONDO_STOCK_COUNT).toBe(442);
    expect(BUNDLED_ONDO_STOCK_TOKENS).toHaveLength(BUNDLED_ONDO_STOCK_COUNT);
    expect(BUNDLED_ONDO_STOCK_SOURCE_SHA256).toMatch(/^[0-9a-f]{64}$/);
  });

  it('is current with, and contains every address in, the backend snapshot', () => {
    const source = readFileSync(resolve(__dirname, '../../../../cusd_plus/gm_tokens.json'), 'utf8');
    expect(BUNDLED_ONDO_STOCK_SOURCE_SHA256).toBe(
      createHash('sha256').update(source).digest('hex'),
    );
    const current = Object.values(JSON.parse(source) as Record<string, { address: string }>);
    const bundled = new Set(BUNDLED_ONDO_STOCK_TOKENS.map((token) => token.address));
    for (const token of current) expect(bundled.has(token.address.toLowerCase())).toBe(true);
  });

  it('contains only safe labels and unique contract addresses', () => {
    const symbols = BUNDLED_ONDO_STOCK_TOKENS.map((token) => token.symbol);
    const addresses = BUNDLED_ONDO_STOCK_TOKENS.map((token) => token.address);
    expect(new Set(addresses).size).toBe(addresses.length);
    for (const symbol of symbols) expect(symbol).toMatch(/^[A-Za-z0-9._-]{1,32}$/);
    for (const address of addresses) expect(address).toMatch(/^0x[0-9a-f]{40}$/);
  });

  it('includes representative high-volume assets', () => {
    const symbols = new Set(BUNDLED_ONDO_STOCK_TOKENS.map((token) => token.symbol));
    for (const symbol of ['AAPLon', 'AMZNon', 'GOOGLon', 'METAon', 'MSFTon', 'NVDAon', 'TSLAon']) {
      expect(symbols.has(symbol)).toBe(true);
    }
  });
});
