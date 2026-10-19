// Pure ABI encoder for ConfioSwapRouter (Bitcoin & gold on PancakeSwap).
// Kept apart from wallet/native modules so the calldata vectors run in Jest;
// byte-identical to eth_abi.encode with crypto_policy.BUY_TYPES / SELL_TYPES.

import { encodeAddress, encodeUint, selector } from './evmWallet';

export const CRYPTO_BUY_SIGNATURE = 'buy(uint8,uint256,uint256,bytes,address,uint256,uint256)';
export const CRYPTO_SELL_SIGNATURE = 'sell(uint8,address,uint256,bytes,uint256,uint256,uint256)';

// Seven head words; the dynamic `route` is the fourth argument in both.
const ROUTE_OFFSET = 7n * 32n;

const dynamicBytes = (hex: string): string => {
  const value = hex.replace(/^0x/, '').toLowerCase();
  if (value.length % 2 || !/^[0-9a-f]*$/.test(value)) throw new Error('invalid route bytes');
  const paddedLength = Math.ceil(value.length / 64) * 64;
  return encodeUint(BigInt(value.length / 2)) + value.padEnd(paddedLength, '0');
};

export const encodeCryptoBuyCall = (p: {
  dollar: number;
  amountIn: bigint;
  minUsdtOut: bigint;
  /** The quote's `route`, verbatim. */
  route: string;
  tokenOut: string;
  minTokenOut: bigint;
  maxFeeBps: bigint;
}): string =>
  selector(CRYPTO_BUY_SIGNATURE) +
  encodeUint(BigInt(p.dollar)) +
  encodeUint(p.amountIn) +
  encodeUint(p.minUsdtOut) +
  encodeUint(ROUTE_OFFSET) +
  encodeAddress(p.tokenOut) +
  encodeUint(p.minTokenOut) +
  encodeUint(p.maxFeeBps) +
  dynamicBytes(p.route);

export const encodeCryptoSellCall = (p: {
  dollar: number;
  tokenIn: string;
  amountIn: bigint;
  route: string;
  minUsdtOut: bigint;
  minDestOut: bigint;
  maxFeeBps: bigint;
}): string =>
  selector(CRYPTO_SELL_SIGNATURE) +
  encodeUint(BigInt(p.dollar)) +
  encodeAddress(p.tokenIn) +
  encodeUint(p.amountIn) +
  encodeUint(ROUTE_OFFSET) +
  encodeUint(p.minUsdtOut) +
  encodeUint(p.minDestOut) +
  encodeUint(p.maxFeeBps) +
  dynamicBytes(p.route);
