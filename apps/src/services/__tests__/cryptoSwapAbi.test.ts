import { deriveIntentId, selector } from '../evmWallet';
import { encodeCryptoBuyCall, encodeCryptoSellCall } from '../cryptoSwapAbi';
import { keccak_256 } from '@noble/hashes/sha3';
import { bytesToHex, utf8ToBytes } from '@noble/hashes/utils';

// eth_abi.encode(crypto_policy.BUY_TYPES / SELL_TYPES, …) for the same args,
// with a real V3 route (USDT -0.05%-> BTCB) as the quote would serve it.
const ROUTE = '0x00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000040000000000000000000000000000000000000000000000000000000000000002b55d398326f99059ff775485246999027b31979550001f47130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c000000000000000000000000000000000000000000';
const TOKEN = '0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c';
const BUY = '0x8a0a08f200000000000000000000000000000000000000000000000000000000000000010000000000000000000000000000000000000000000000008ac7230489e800000000000000000000000000000000000000000000000000008987647e9c1f000000000000000000000000000000000000000000000000000000000000000000e00000000000000000000000007130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c00000000000000000000000000000000000000000000000000007048860ddf79000000000000000000000000000000000000000000000000000000000000005a00000000000000000000000000000000000000000000000000000000000000a000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000040000000000000000000000000000000000000000000000000000000000000002b55d398326f99059ff775485246999027b31979550001f47130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c000000000000000000000000000000000000000000';
const SELL = '0x9817b1ac00000000000000000000000000000000000000000000000000000000000000000000000000000000000000007130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c00000000000000000000000000000000000000000000000000005af3107a400000000000000000000000000000000000000000000000000000000000000000e00000000000000000000000000000000000000000000000008963dd8c2c5e000000000000000000000000000000000000000000000000000088009813ced40000000000000000000000000000000000000000000000000000000000000000005a00000000000000000000000000000000000000000000000000000000000000a000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000040000000000000000000000000000000000000000000000000000000000000002b55d398326f99059ff775485246999027b31979550001f47130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c000000000000000000000000000000000000000000';

const kindId = (kind: string, requestId = '') =>
  '0x' + bytesToHex(keccak_256(utf8ToBytes(`${kind}:${requestId}`)));

describe('ConfioSwapRouter calldata', () => {
  it('encodes buy byte-for-byte like eth_abi', () => {
    expect(encodeCryptoBuyCall({
      dollar: 1,
      amountIn: 10n ** 19n,
      minUsdtOut: 9_910_000_000_000_000_000n,
      route: ROUTE,
      tokenOut: TOKEN,
      minTokenOut: 123_456_789_012_345n,
      maxFeeBps: 90n,
    })).toBe(BUY);
  });

  it('encodes sell byte-for-byte like eth_abi', () => {
    expect(encodeCryptoSellCall({
      dollar: 0,
      tokenIn: TOKEN,
      amountIn: 10n ** 14n,
      route: ROUTE,
      minUsdtOut: 9_900_000_000_000_000_000n,
      minDestOut: 9_800_000_000_000_000_000n,
      maxFeeBps: 90n,
    })).toBe(SELL);
  });

  it('uses the selectors the relay allowlists', () => {
    expect(BUY.slice(0, 10)).toBe(selector('buy(uint8,uint256,uint256,bytes,address,uint256,uint256)'));
    expect(SELL.slice(0, 10)).toBe(selector('sell(uint8,address,uint256,bytes,uint256,uint256,uint256)'));
  });

  it('rejects a malformed route instead of signing it', () => {
    expect(() => encodeCryptoSellCall({
      dollar: 0, tokenIn: TOKEN, amountIn: 1n, route: '0xabc', minUsdtOut: 1n, minDestOut: 1n, maxFeeBps: 90n,
    })).toThrow('invalid route bytes');
  });
});

describe('deriveIntentId parity with sponsor_7702.classify_calls_kind', () => {
  const approve = { to: TOKEN, valueWei: 0n, data: selector('approve(address,uint256)') + '00'.repeat(64) };
  const redeem = { to: TOKEN, valueWei: 0n, data: '0xf4794519' + '00'.repeat(96) };
  const stockBuy = {
    to: TOKEN, valueWei: 0n,
    data: selector('buyWithSavings((uint256,uint256,bytes32,address,uint256,uint256,uint256,uint8,bytes32),bytes,uint256,uint256,uint256,uint256)'),
  };

  it('classifies crypto buys and sells, approve included', () => {
    expect(deriveIntentId([approve, { to: TOKEN, valueWei: 0n, data: BUY }])).toBe(kindId('crypto_buy'));
    expect(deriveIntentId([approve, { to: TOKEN, valueWei: 0n, data: SELL }], 'gm_1'))
      .toBe(kindId('crypto_sell', 'gm_1'));
  });

  it('checks crypto before stock and redeem', () => {
    expect(deriveIntentId([redeem, stockBuy, { to: TOKEN, valueWei: 0n, data: BUY }])).toBe(kindId('crypto_buy'));
    expect(deriveIntentId([redeem, { to: TOKEN, valueWei: 0n, data: SELL }])).toBe(kindId('crypto_sell'));
    expect(deriveIntentId([stockBuy])).toBe(kindId('stock_buy'));
    expect(deriveIntentId([redeem])).toBe(kindId('redeem'));
  });
});
