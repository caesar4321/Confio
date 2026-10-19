// Bitcoin & gold (ConfioSwapRouter on PancakeSwap): the floors a trade signs.
//
// The relay (cusd_plus/crypto_policy.decode_crypto_call) re-quotes every
// trade and refuses one whose floors are weaker than its own, or a buy whose
// exit floor is above what the dollar exit can yield. These helpers mirror
// its formulas exactly, so a correct client is never refused:
//
//   buy   minUsdtOut  = net USDT of the dollar exit (fee taken by cUSD)
//         minTokenOut = quote(net) · (1 − slip)
//   sell  minUsdtOut  = quote(amount) · (1 − slip)
//         minDestOut  = expected dollars at that floor · (1 − slip)
//                       cUSD:  entry net of fee (mints 1:1)
//                       cUSD+: shares a subscribe of that net mints
//
// Pure (no network, no wallet): Jest runs the parity vectors in Node.

import { perimeterFee } from './stockFeeMath';

export const BPS = 10_000n;

/** Router `dollar` argument: where dollars come from (buy) or return to (sell). */
export const DOLLAR_PLUS = 0; // cUSD+ (Confío Dollar+)
export const DOLLAR = 1; // cUSD (Confío Dollar)
export type CryptoDollar = typeof DOLLAR_PLUS | typeof DOLLAR;
export type FundingDollar = 'cusd_plus' | 'cusd';

export const dollarFor = (funding: FundingDollar): CryptoDollar =>
  (funding === 'cusd_plus' ? DOLLAR_PLUS : DOLLAR);

/** Mirror of crypto_policy._slip_floor: amount · (1e4 − slip) / 1e4, floored. */
export const slipFloor = (amount: bigint, slipBps: bigint): bigint =>
  (amount <= 0n ? 0n : (amount * (BPS - slipBps)) / BPS);

/** Same threshold as the server's vault.MIN_SAFE_MINT_WEI ($1.000001): a
 * cUSD+ sale netting less is refused (savings_mint_too_small). Kept in sync
 * with cusdPlusVault.INTERNAL_CUSD_MIN_WRAP_WEI, which tests assert. */
export const SAVINGS_MIN_MINT_WEI = 10n ** 18n + 10n ** 12n;

/** cUSD+ redeemToUsdt, floored twice exactly like the vault
 * (same math as cusdPlusVault.predictRedeemUsdtOut). */
export const plusRedeemGross = (shares: bigint, pPlusWad: bigint, oracleWad: bigint): bigint => {
  if (oracleWad <= 0n || shares <= 0n) return 0n;
  const usdyOut = (shares * pPlusWad) / oracleWad;
  return (usdyOut * oracleWad) / 10n ** 18n;
};

/** cUSD+ subscribeAndMint at the given prices
 * (same math as cusdPlusVault.predictSubscribeSharesOut). */
export const plusSubscribeShares = (usdtWei: bigint, pPlusWad: bigint, oracleWad: bigint): bigint => {
  if (usdtWei <= 0n || pPlusWad <= 0n || oracleWad <= 0n) return 0n;
  const usdyOut = (usdtWei * 10n ** 18n) / oracleWad;
  return (usdyOut * oracleWad) / pPlusWad;
};

export interface VaultPrices {
  pPlusWad: bigint;
  oraclePriceWad: bigint;
}

/**
 * (gross, net) USDT a buy's dollar exit yields for `amountIn` (cUSD wei or
 * cUSD+ shares). Mirrors crypto_policy.expected_exit_usdt: cUSD charges
 * ceil(gross · fee / 1e4); cUSD+ redeems to gross and the same fee applies.
 */
export const exitUsdt = (
  dollar: CryptoDollar,
  amountIn: bigint,
  feeBps: bigint,
  prices?: VaultPrices,
): { grossWei: bigint; netWei: bigint; feeWei: bigint } => {
  const grossWei = dollar === DOLLAR
    ? amountIn
    : plusRedeemGross(amountIn, prices?.pPlusWad ?? 0n, prices?.oraclePriceWad ?? 0n);
  const feeWei = perimeterFee(grossWei, feeBps);
  return { grossWei, netWei: grossWei - feeWei, feeWei };
};

/** Floors for buy(dollar, amountIn, minUsdtOut, route, token, minTokenOut, fee). */
export const buyFloors = (params: {
  netUsdtWei: bigint;
  quotedTokenOut: bigint;
  slipBps: bigint;
}): { minUsdtOut: bigint; minTokenOut: bigint } => ({
  // The exact net: never above what the exit yields (the relay refuses and
  // the router would revert), and well inside the slippage band.
  minUsdtOut: params.netUsdtWei,
  minTokenOut: slipFloor(params.quotedTokenOut, params.slipBps),
});

/**
 * The output floor to sign for a fresh quote, bound to what the person was
 * SHOWN: never weaker than the displayed quote's slippage floor (a fresh
 * quote within slippage must not get a second full allowance on top), and
 * never weaker than the relay's floor of the fresh quote. Null when the two
 * conflict (the fresh quote is already below what the person was promised):
 * refuse with PRICE_MOVED rather than sign a weaker floor.
 */
export const boundFloor = (freshOut: bigint, slipBps: bigint, displayedOut?: bigint): bigint | null => {
  const relay = slipFloor(freshOut, slipBps);
  if (!displayedOut || displayedOut <= 0n) return relay;
  const shown = slipFloor(displayedOut, slipBps);
  if (shown > freshOut) return null;
  return shown > relay ? shown : relay;
};

/** cUSD+ shares drift only with pPlus accrual between signing and mining
 * (well under 1 bp in an intent's ≤30 min): the dollar floor allows 1 bp,
 * not a second market slippage. */
export const SHARE_DRIFT_BPS = 1n;

/** Floors for sell(dollar, token, amountIn, route, minUsdtOut, minDestOut, fee). */
export const sellFloors = (params: {
  dollar: CryptoDollar;
  quotedUsdtOut: bigint;
  feeBps: bigint;
  slipBps: bigint;
  /** Mint-side prices: pPlus and the vault's CURRENT oracle (what subscribe uses). */
  prices?: VaultPrices;
  /** The USDT floor to sign, when bound to a displayed quote (boundFloor). */
  minUsdtOut?: bigint;
}): {
  minUsdtOut: bigint;
  /** Dollars that re-enter at the USDT floor, after Confío's fee. */
  entryNetWei: bigint;
  /** cUSD wei or cUSD+ shares expected at that floor. */
  expectedDest: bigint;
  minDestOut: bigint;
  /** cUSD+ only: the relay refuses mints under SAVINGS_MIN_MINT_WEI. */
  savingsMintTooSmall: boolean;
} => {
  const minUsdtOut = params.minUsdtOut ?? slipFloor(params.quotedUsdtOut, params.slipBps);
  const entryNetWei = minUsdtOut - perimeterFee(minUsdtOut, params.feeBps);
  const expectedDest = params.dollar === DOLLAR
    ? entryNetWei
    : plusSubscribeShares(entryNetWei, params.prices?.pPlusWad ?? 0n, params.prices?.oraclePriceWad ?? 0n);
  // The USDT floor already carries the market slippage. cUSD then mints
  // exact math (entry net, no further allowance); cUSD+ allows only share
  // drift. Both stay at or above the relay's own slippage floor.
  const tight = params.dollar === DOLLAR ? expectedDest : slipFloor(expectedDest, SHARE_DRIFT_BPS);
  const relayFloor = slipFloor(expectedDest, params.slipBps);
  return {
    minUsdtOut,
    entryNetWei,
    expectedDest,
    minDestOut: tight > relayFloor ? tight : relayFloor,
    savingsMintTooSmall: params.dollar === DOLLAR_PLUS && entryNetWei < SAVINGS_MIN_MINT_WEI,
  };
};

/** What the person receives in dollars for a sale quoting `quotedUsdtOut`
 * (display: the expected case, not the floor). */
export const sellNetUsdt = (quotedUsdtOut: bigint, feeBps: bigint): bigint =>
  quotedUsdtOut - perimeterFee(quotedUsdtOut, feeBps);

/** maxOrderUsd caps a BUY's gross (crypto_order_too_large). */
export const exceedsMaxOrder = (grossWei: bigint, maxOrderUsd: number | null | undefined): boolean =>
  maxOrderUsd != null && grossWei > BigInt(Math.floor(maxOrderUsd)) * 10n ** 18n;

/** Decimal string → base units (no float rounding). */
export const toBaseUnits = (value: string, decimals: number): bigint => {
  const clean = value.trim();
  if (!/^\d*(\.\d*)?$/.test(clean) || clean === '' || clean === '.') return 0n;
  const [whole, frac = ''] = clean.split('.');
  const scale = 10n ** BigInt(decimals);
  return BigInt(whole || '0') * scale + BigInt((frac + '0'.repeat(decimals)).slice(0, decimals) || '0');
};

/** Base units → JS number for display only. */
export const fromBaseUnits = (units: bigint | string, decimals: number): number => {
  const v = typeof units === 'string' ? BigInt(units || '0') : units;
  const scale = 10n ** BigInt(decimals);
  return Number(v / scale) + Number(v % scale) / Number(scale);
};

/** "Costo de mercado": PancakeSwap pool fees + price impact, in percent. */
export const marketCostPct = (poolFeeBps?: number | null, priceImpactBps?: number | null): number | null => {
  if (poolFeeBps == null && priceImpactBps == null) return null;
  // Impact is measured against the snapshot price INCLUDING the pool fee
  // (crypto_schema.resolve_crypto_quote): never add the fee twice.
  if (priceImpactBps != null) return Math.max(priceImpactBps, poolFeeBps ?? 0) / 100;
  return (poolFeeBps ?? 0) / 100;
};
