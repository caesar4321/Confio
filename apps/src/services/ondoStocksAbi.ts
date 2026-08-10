// Pure, dependency-light ABI encoder for ConfioStockRouter. Kept separate
// from wallet/native modules so the exact calldata vectors run in Jest/Node.

import { encodeAddress, encodeUint, selector } from './evmWallet';

export interface GmRouterQuote {
  attestationId?: string;
  userId?: string;
  chainId: string;
  assetAddress: string;
  side: string;
  tokenAmount: string;
  price: string;
  expiration?: number;
  signatureHex?: string;
  additionalDataHex?: string;
}

const dynamicBytes = (hex: string): string => {
  const value = hex.replace(/^0x/, '');
  const paddedLength = Math.ceil(value.length / 64) * 64;
  return encodeUint(BigInt(value.length / 2)) + value.padEnd(paddedLength, '0');
};

const quoteWords = (q: GmRouterQuote): string =>
  encodeUint(BigInt(q.chainId)) +
  encodeUint(BigInt(q.attestationId as string)) +
  (q.userId as string).replace(/^0x/, '').padStart(64, '0') +
  encodeAddress(q.assetAddress) +
  encodeUint(BigInt(q.price)) +
  encodeUint(BigInt(q.tokenAmount)) +
  encodeUint(BigInt(Math.floor(q.expiration as number))) +
  encodeUint(BigInt(q.side)) +
  (q.additionalDataHex as string).replace(/^0x/, '').padStart(64, '0');

export const encodeBuyStockCall = (
  q: GmRouterQuote, shares: bigint, spend: bigint, minUsdt: bigint, maxFee: bigint,
): string => {
  const headWords = 14n;
  const head = quoteWords(q) + encodeUint(headWords * 32n) + encodeUint(shares) +
    encodeUint(spend) + encodeUint(minUsdt) + encodeUint(maxFee);
  return selector(
    'buyWithSavings((uint256,uint256,bytes32,address,uint256,uint256,uint256,uint8,bytes32),bytes,uint256,uint256,uint256,uint256)',
  ) + head + dynamicBytes(q.signatureHex as string);
};

export const encodeSellStockCall = (
  q: GmRouterQuote, minUsdt: bigint, minShares: bigint, maxFee: bigint,
): string => {
  const headWords = 13n;
  const head = quoteWords(q) + encodeUint(headWords * 32n) + encodeUint(minUsdt) +
    encodeUint(minShares) + encodeUint(maxFee);
  return selector(
    'sellToSavings((uint256,uint256,bytes32,address,uint256,uint256,uint256,uint8,bytes32),bytes,uint256,uint256,uint256)',
  ) + head + dynamicBytes(q.signatureHex as string);
};
