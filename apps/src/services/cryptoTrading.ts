// Bitcoin & gold execution — ConfioSwapRouter on PancakeSwap, inside the
// same sponsored EIP-7702 batch as Ondo stocks.
//
// The server serves the catalog, the live quote (with the exact `route` the
// relay accepts) and the fee; the device owns the key and signs one batch:
// an optional approve(router, MAX) on what the router pulls + the router
// call. Every floor is computed by services/cryptoSwapMath with the relay's
// own formulas, so a correct client is never refused and a stale one can
// never get the person's dollars swapped at a bad price.
//
// Each GraphQL field is queried ALONE: these fields are newer than the
// shared portfolio query, and one unknown field fails a whole query.

import { gql } from '@apollo/client';

import { BatchCall, encodeCall } from './evmWallet';
import { encodeCryptoBuyCall, encodeCryptoSellCall } from './cryptoSwapAbi';
import {
  boundFloor,
  CryptoDollar,
  dollarFor,
  DOLLAR,
  exceedsMaxOrder,
  exitUsdt,
  FundingDollar,
  plusRedeemGross,
  projectPPlus,
  sellFloors,
  sellNetUsdt,
  toBaseUnits,
  VaultPrices,
} from './cryptoSwapMath';
import { installBscServerTransport } from './bscServerRpc';
import {
  getErc20Allowance,
  getConfioYieldShareBps,
  getCurrentOraclePrice,
  getErc20BalanceWei,
  getVaultPrices,
  getVaultShares,
  sharesForUsdtOut,
} from './cusdPlusVault';
import { getActiveEvmWallet } from './secureDeterministicWallet';
import {
  createSponsoredRequestId,
  executeSponsoredBatch,
  fetchSponsored7702Params,
} from './sponsored7702';

const MAX_UINT256 = (1n << 256n) - 1n;
const WAD = 10n ** 18n;

export const GET_CRYPTO_CAPABILITIES = gql`
  query CryptoCapabilities {
    cryptoCapabilities {
      enabled
      tradingEnabled
      buyEnabled
      ackRequired
      ackVersion
      disclosureTitle
      disclosurePoints
      fundingDollar
      feeBps
      maxSlippageBps
      routerAddress
      blockedMessage
    }
  }
`;

export const GET_CRYPTO_MARKET = gql`
  query CryptoMarket {
    cryptoMarket {
      assets {
        symbol
        ticker
        name
        address
        decimals
        category
        featured
        custody
        maxOrderUsd
        priceUsd
        dayChangePct
        sparkline24h
      }
      updatedAt
    }
  }
`;

export const GET_CRYPTO_HOLDINGS = gql`
  query CryptoHoldings {
    cryptoHoldings {
      symbol
      ticker
      name
      address
      custody
      listed
      category
      units
      decimals
      valueUsd
      dayChangePct
    }
  }
`;

const CRYPTO_QUOTE = gql`
  query CryptoQuote($symbol: String!, $side: String!, $amountIn: String!) {
    cryptoQuote(symbol: $symbol, side: $side, amountIn: $amountIn) {
      success
      errorCode
      amountIn
      expectedOut
      route
      poolFeeBps
      priceImpactBps
    }
  }
`;

export const ACKNOWLEDGE_CRYPTO_RISK = gql`
  mutation AcknowledgeCryptoRisk($version: Int!) {
    acknowledgeCryptoRisk(version: $version) {
      success
      error
    }
  }
`;

// Long-standing fields, on their own so a newer field elsewhere never breaks them.
const DOLLAR_ADDRESSES = gql`
  query CryptoDollarAddresses {
    cusdPlusConvertParams {
      vaultAddress
      cusdAddress
    }
  }
`;

export type CryptoCategory = 'crypto' | 'metal' | string;

export interface CryptoCapabilities {
  enabled: boolean;
  tradingEnabled: boolean;
  buyEnabled: boolean;
  ackRequired: boolean;
  ackVersion: number;
  disclosureTitle: string;
  disclosurePoints: string[];
  fundingDollar: FundingDollar;
  feeBps: number | null;
  maxSlippageBps: number;
  routerAddress: string | null;
  blockedMessage: string | null;
}

export interface CryptoAsset {
  symbol: string;
  ticker: string;
  name: string;
  address: string;
  decimals: number;
  category: CryptoCategory;
  featured: boolean;
  custody: string;
  maxOrderUsd: number | null;
  /** Null until priced: unknown is not zero. */
  priceUsd: number | null;
  dayChangePct: number | null;
  sparkline24h: number[] | null;
}

export interface CryptoHolding {
  symbol: string;
  ticker: string;
  name: string;
  /** Everything a sale needs comes with the holding: a holder whose
   * country was blocked (no cryptoMarket) or whose token was delisted
   * must still be able to sell. */
  address: string;
  custody: string;
  /** False = sell only (delisted or deferred): no Comprar. */
  listed: boolean;
  category: CryptoCategory;
  /** Base units, exact. */
  units: string;
  decimals: number;
  /** Null when no price is known. */
  valueUsd: number | null;
  dayChangePct: number | null;
}

export interface CryptoQuote {
  amountIn: string;
  expectedOut: string;
  route: string;
  poolFeeBps: number | null;
  priceImpactBps: number | null;
}

// ─── Copy ───────────────────────────────────────────────────────────────

export const CRYPTO_FEE_CHANGED_MESSAGE =
  'La comisión de Confío cambió. Revisa el nuevo monto antes de confirmar.';
export const CRYPTO_FUNDING_CHANGED_MESSAGE =
  'Cambió el dólar con el que pagas. Revisa la operación antes de confirmar.';
export const CRYPTO_PRICE_MOVED_MESSAGE =
  'El precio cambió más de lo permitido. Revisa la nueva cotización antes de continuar.';
export const SAVINGS_MINT_TOO_SMALL_MESSAGE =
  'Para volver a Confío Dollar+ necesitas recibir al menos US$1.00. Vende un poco más o recibe la venta en Confío Dollar.';

/** Relay refusal codes (cusd_plus crypto_policy / crypto_risk) and quote codes. */
const ERROR_COPY: Record<string, string> = {
  crypto_ack_required: 'Antes de tu primera compra confirma que entiendes los riesgos.',
  trade_not_available: 'Esta operación no está disponible para tu cuenta en este momento.',
  savings_not_available: 'No puedes recibir esta venta en Confío Dollar+. Recíbela en Confío Dollar.',
  savings_mint_too_small: SAVINGS_MINT_TOO_SMALL_MESSAGE,
  crypto_order_too_large: 'El monto supera el máximo por operación para este activo. Prueba con uno menor.',
  bad_crypto_floor: 'El precio se movió mientras confirmabas. Inténtalo de nuevo para ver la nueva cotización.',
  crypto_quote_unavailable: 'No pudimos cotizar en este momento. Inténtalo de nuevo en un momento.',
  crypto_trading_disabled: 'La compra y venta de oro y bitcoin aún no está habilitada.',
  token_not_listed: 'Este activo ya no está disponible para comprar.',
  bad_crypto_fee_cap: CRYPTO_FEE_CHANGED_MESSAGE,
  route_not_allowed: 'La ruta de la operación cambió. Inténtalo de nuevo.',
  // cryptoQuote errorCode values
  NOT_LISTED: 'Este activo ya no está disponible para comprar.',
  NOT_AVAILABLE: 'Esta operación no está disponible para tu cuenta en este momento.',
  QUOTE_UNAVAILABLE: 'No pudimos cotizar en este momento. Inténtalo de nuevo en un momento.',
  BAD_AMOUNT: 'El monto está fuera de los límites permitidos.',
  AUTH_REQUIRED: 'Tu sesión expiró. Vuelve a iniciar sesión.',
};

const RELAY_CODES = Object.keys(ERROR_COPY).filter((code) => code === code.toLowerCase());

const codedError = (code: string, message?: string): Error =>
  Object.assign(new Error(message || ERROR_COPY[code] || 'No pudimos completar la operación.'), { code });

/** The relay/quote code carried by an error (thrown here or by the relay's "sponsored batch rejected: <code>"). */
export const cryptoErrorCode = (error: unknown): string | null => {
  const code = (error as { code?: string } | null)?.code;
  if (code) return code;
  const message = error instanceof Error ? error.message : '';
  return RELAY_CODES.find((c) => new RegExp(`\\b${c}\\b`).test(message)) || null;
};

export const isCryptoAckRequired = (error: unknown): boolean =>
  cryptoErrorCode(error) === 'crypto_ack_required';

/** Spanish copy for a refused or failed trade. */
export const cryptoTradeError = (error: unknown, side: 'buy' | 'sell'): string => {
  const code = cryptoErrorCode(error);
  if (code && ERROR_COPY[code]) return ERROR_COPY[code];
  const message = error instanceof Error ? error.message : '';
  if (/simulation_reverted|simulation rejected|simulation reverted/i.test(message)) {
    return side === 'sell'
      ? 'La red rechazó la venta antes de enviarla y no se cobró nada. Inténtalo de nuevo en un momento.'
      : 'La red rechazó la compra antes de enviarla y no se cobró nada. Inténtalo de nuevo en un momento.';
  }
  if (/^sponsored batch/i.test(message) || !message) {
    return side === 'sell' ? 'No pudimos completar la venta.' : 'No pudimos completar la compra.';
  }
  return message;
};

// ─── Reads ──────────────────────────────────────────────────────────────

const client = async () => (await import('../apollo/client')).apolloClient;

export const fetchCryptoCapabilities = async (): Promise<CryptoCapabilities> => {
  const { data } = await (await client()).query({ query: GET_CRYPTO_CAPABILITIES, fetchPolicy: 'no-cache' });
  const caps = data?.cryptoCapabilities as CryptoCapabilities | null | undefined;
  if (!caps) throw codedError('crypto_trading_disabled');
  return caps;
};

export const getCryptoQuote = async (
  symbol: string,
  side: 'buy' | 'sell',
  amountIn: bigint,
): Promise<CryptoQuote> => {
  if (amountIn <= 0n) throw codedError('BAD_AMOUNT');
  const { data } = await (await client()).query({
    query: CRYPTO_QUOTE,
    variables: { symbol, side, amountIn: amountIn.toString() },
    fetchPolicy: 'no-cache',
  });
  const q = data?.cryptoQuote;
  if (!q?.success || !q.route || !q.expectedOut) throw codedError(q?.errorCode || 'QUOTE_UNAVAILABLE');
  if (BigInt(q.expectedOut) <= 0n) throw codedError('QUOTE_UNAVAILABLE');
  return {
    amountIn: q.amountIn,
    expectedOut: q.expectedOut,
    route: q.route,
    poolFeeBps: q.poolFeeBps ?? null,
    priceImpactBps: q.priceImpactBps ?? null,
  };
};

const fetchDollarAddresses = async (): Promise<{ vaultAddress: string; cusdAddress: string }> => {
  const { data } = await (await client()).query({ query: DOLLAR_ADDRESSES, fetchPolicy: 'cache-first' });
  return {
    vaultAddress: data?.cusdPlusConvertParams?.vaultAddress || '',
    cusdAddress: data?.cusdPlusConvertParams?.cusdAddress || '',
  };
};

const requireSponsored = async () => {
  const sponsored = await fetchSponsored7702Params();
  if (!sponsored.enabled || !sponsored.delegateAddress) {
    throw new Error('Las operaciones patrocinadas no están disponibles en este momento.');
  }
  return sponsored.delegateAddress;
};

/** Dollars → wei from the DECIMAL the person typed, never through binary
 * float math (1.1 must be 1.1e18 exactly, not 1100000000000000089).
 * String(number) is the shortest decimal that round-trips, i.e. what was
 * typed; exponent forms (absurdly small/large) fall back to fixed. */
export const usdToWei = (value: number | string): bigint => {
  const text = typeof value === 'string' ? value.trim() : String(value);
  if (typeof value === 'number' && (!Number.isFinite(value) || value <= 0)) return 0n;
  const plain = /e/i.test(text) ? Number(text).toFixed(18) : text;
  return toBaseUnits(plain, 18);
};

/** Trading config for one execution, re-read from the server every time. */
const tradingConfig = async (expected: { feeBps?: number | null; funding?: FundingDollar }) => {
  const caps = await fetchCryptoCapabilities();
  if (!caps.tradingEnabled || !caps.routerAddress) throw codedError('crypto_trading_disabled');
  // Unknown fee: nothing to sign (the router binds it on-chain).
  if (caps.feeBps == null) throw codedError('crypto_quote_unavailable');
  // Execution signs only what the person saw (same rule as stocks'
  // requireDisplayedFee): a fee change between display and confirmation
  // re-prices the trade and must be shown first.
  if (expected.feeBps !== undefined && expected.feeBps !== caps.feeBps) {
    throw codedError('FEE_CHANGED', CRYPTO_FEE_CHANGED_MESSAGE);
  }
  if (expected.funding !== undefined && expected.funding !== caps.fundingDollar) {
    throw codedError('FUNDING_CHANGED', CRYPTO_FUNDING_CHANGED_MESSAGE);
  }
  return {
    caps,
    router: caps.routerAddress,
    feeBps: BigInt(caps.feeBps),
    slipBps: BigInt(caps.maxSlippageBps ?? 100),
  };
};

const approveCall = (token: string, spender: string): BatchCall => ({
  to: token,
  valueWei: 0n,
  data: encodeCall('approve(address,uint256)', [
    { type: 'address', value: spender },
    { type: 'uint', value: MAX_UINT256 },
  ]),
});

// ─── Preview (non-binding, for the screens) ─────────────────────────────

/** Buy preview: quote the net USDT a gross dollar amount leaves after the fee. */
export const previewCryptoBuy = async (params: {
  symbol: string;
  grossAmountUsd: number | string;
  feeBps: number;
}): Promise<CryptoQuote & { netWei: bigint }> => {
  const { netWei } = exitUsdt(DOLLAR, usdToWei(params.grossAmountUsd), BigInt(params.feeBps));
  return { ...(await getCryptoQuote(params.symbol, 'buy', netWei)), netWei };
};

/** Sell preview: quote `units` and what returns to Confío dollars after the fee. */
export const previewCryptoSell = async (params: {
  symbol: string;
  units: bigint;
  feeBps: number;
}): Promise<CryptoQuote & { netWei: bigint }> => {
  const quote = await getCryptoQuote(params.symbol, 'sell', params.units);
  return { ...quote, netWei: sellNetUsdt(BigInt(quote.expectedOut), BigInt(params.feeBps)) };
};

/** Units of a position matching a dollar amount, never above what is held. */
export const unitsForUsd = (heldUnits: bigint, positionUsd: number, amountUsd: number): bigint => {
  if (heldUnits <= 0n || !(positionUsd > 0) || !(amountUsd > 0)) return 0n;
  if (amountUsd >= positionUsd) return heldUnits;
  const num = BigInt(Math.round(amountUsd * 1e6));
  const den = BigInt(Math.round(positionUsd * 1e6));
  return den > 0n ? (heldUnits * num) / den : 0n;
};

// ─── Execution ──────────────────────────────────────────────────────────

export interface CryptoBuyResult {
  txHash: string;
  tokenOutUnits: bigint;
  grossWei: bigint;
  feeWei: bigint;
  netWei: bigint;
  /** The fee rate the trade was signed at (for the receipt). */
  feeBps: number;
}

export const buyCrypto = async (params: {
  asset: Pick<CryptoAsset, 'symbol' | 'address' | 'maxOrderUsd'>;
  /** The typed amount; a decimal string is converted exactly. */
  grossAmountUsd: number | string;
  /** MAX: spend the whole funding balance. */
  spendAll?: boolean;
  /** Fee and funding dollar the screen displayed; anything else is refused. */
  expectedFeeBps: number | null;
  expectedFunding: FundingDollar;
  /** The preview's token amount; a fresh quote below its slippage floor stops. */
  previewTokenOut?: bigint;
  requestId?: string;
}): Promise<CryptoBuyResult> => {
  installBscServerTransport();
  const [config, addresses, wallet, delegateAddress] = await Promise.all([
    tradingConfig({ feeBps: params.expectedFeeBps, funding: params.expectedFunding }),
    fetchDollarAddresses(),
    getActiveEvmWallet(),
    requireSponsored(),
  ]);
  if (!config.caps.buyEnabled) throw codedError('trade_not_available');
  const dollar: CryptoDollar = dollarFor(config.caps.fundingDollar);
  const requestId = params.requestId || createSponsoredRequestId();
  const grossTarget = usdToWei(params.grossAmountUsd);

  let amountIn: bigint;
  let pulled: string;
  let prices: VaultPrices | undefined;
  if (dollar === DOLLAR) {
    pulled = addresses.cusdAddress;
    if (!pulled) throw codedError('crypto_trading_disabled');
    const balance = await getErc20BalanceWei(pulled, wallet.address);
    amountIn = params.spendAll ? balance : grossTarget;
    if (amountIn <= 0n || amountIn > balance) {
      throw new Error('Tu saldo en Confío Dollar no alcanza para esta compra.');
    }
  } else {
    pulled = addresses.vaultAddress;
    if (!pulled) throw codedError('crypto_trading_disabled');
    const [vaultPrices, owned] = await Promise.all([
      getVaultPrices(pulled),
      getVaultShares(pulled, wallet.address),
    ]);
    prices = vaultPrices;
    let shares = params.spendAll ? owned : sharesForUsdtOut(grossTarget, prices.pPlusWad);
    // The ceiling helper can ask for a share above the balance at MAX: use
    // the whole position when it still covers the amount.
    if (shares > owned && plusRedeemGross(owned, prices.pPlusWad, prices.oraclePriceWad) >= grossTarget) {
      shares = owned;
    }
    if (shares <= 0n || shares > owned) {
      throw new Error('Tu saldo en Confío Dollar+ no alcanza para esta compra.');
    }
    amountIn = shares;
  }

  const { grossWei, netWei, feeWei } = exitUsdt(dollar, amountIn, config.feeBps, prices);
  if (netWei <= 0n) throw codedError('BAD_AMOUNT');
  if (exceedsMaxOrder(grossWei, params.asset.maxOrderUsd)) throw codedError('crypto_order_too_large');

  const quote = await getCryptoQuote(params.asset.symbol, 'buy', netWei);
  const expectedOut = BigInt(quote.expectedOut);
  // Bound to what the screen showed: one slippage allowance in total.
  const minTokenOut = boundFloor(expectedOut, config.slipBps, params.previewTokenOut);
  if (minTokenOut === null) throw codedError('PRICE_MOVED', CRYPTO_PRICE_MOVED_MESSAGE);
  // The exact exit net: never above what the exit yields (relay + router).
  const minUsdtOut = netWei;
  if (minUsdtOut <= 0n || minTokenOut <= 0n) throw codedError('BAD_AMOUNT');

  const needsApprove = (await getErc20Allowance(wallet.address, config.router, pulled)) < amountIn;
  const calls: BatchCall[] = [
    ...(needsApprove ? [approveCall(pulled, config.router)] : []),
    {
      to: config.router,
      valueWei: 0n,
      data: encodeCryptoBuyCall({
        dollar,
        amountIn,
        minUsdtOut,
        route: quote.route,
        tokenOut: params.asset.address,
        minTokenOut,
        maxFeeBps: config.feeBps,
      }),
    },
  ];
  const result = await executeSponsoredBatch({ wallet, calls, delegateAddress, requestId });
  return { txHash: result.txHash, tokenOutUnits: expectedOut, grossWei, feeWei, netWei, feeBps: Number(config.feeBps) };
};

export interface CryptoSellResult {
  txHash: string;
  unitsSold: bigint;
  /** Expected dollars back (USD wei, after Confío's fee). */
  expectedNetWei: bigint;
  feeWei: bigint;
  /** The fee rate the trade was signed at (for the receipt). */
  feeBps: number;
  dollar: CryptoDollar;
}

export const sellCrypto = async (params: {
  /** From the holding (cryptoHoldings) or the market: a sale never needs the catalog. */
  asset: Pick<CryptoAsset, 'symbol' | 'address'>;
  /** Base units to sell; ignored with sellAll (the exact on-chain balance). */
  units: bigint;
  sellAll?: boolean;
  expectedFeeBps: number | null;
  expectedFunding: FundingDollar;
  /** Receive the sale in Confío Dollar instead of Dollar+ (always open). */
  intoCusd?: boolean;
  /** The preview's quoted USDT; the signed floor never goes below its
   * slippage floor, and a fresh quote under it stops with PRICE_MOVED. */
  previewUsdtOut?: bigint;
  requestId?: string;
}): Promise<CryptoSellResult> => {
  installBscServerTransport();
  const [config, addresses, wallet, delegateAddress] = await Promise.all([
    tradingConfig({ feeBps: params.expectedFeeBps, funding: params.expectedFunding }),
    fetchDollarAddresses(),
    getActiveEvmWallet(),
    requireSponsored(),
  ]);
  const dollar: CryptoDollar = params.intoCusd ? DOLLAR : dollarFor(config.caps.fundingDollar);
  const requestId = params.requestId || createSponsoredRequestId();

  const held = await getErc20BalanceWei(params.asset.address, wallet.address);
  const units = params.sellAll ? held : params.units;
  if (units <= 0n || units > held) throw new Error('No tienes suficiente para completar esta venta.');

  const quote = await getCryptoQuote(params.asset.symbol, 'sell', units);
  const quotedUsdt = BigInt(quote.expectedOut);
  const minUsdtOut = boundFloor(quotedUsdt, config.slipBps, params.previewUsdtOut);
  if (minUsdtOut === null) throw codedError('PRICE_MOVED', CRYPTO_PRICE_MOVED_MESSAGE);
  if (dollar !== DOLLAR && !addresses.vaultAddress) throw codedError('crypto_trading_disabled');
  // Minting cUSD+ runs at the vault's CURRENT oracle (ORACLE().getPrice()),
  // as the relay's expected shares do — not lastOraclePrice(). And it runs
  // after accrue(), which first applies ALL growth pending since the
  // vault's last interaction: the shares are priced at the projected pPlus.
  let prices: VaultPrices | undefined;
  let projectedPPlusWad: bigint | undefined;
  if (dollar !== DOLLAR) {
    const [stored, oraclePriceWad, yieldShareBps] = await Promise.all([
      getVaultPrices(addresses.vaultAddress),
      getCurrentOraclePrice(addresses.vaultAddress),
      getConfioYieldShareBps(addresses.vaultAddress),
    ]);
    prices = { pPlusWad: stored.pPlusWad, oraclePriceWad };
    projectedPPlusWad = projectPPlus(stored.pPlusWad, stored.oraclePriceWad, oraclePriceWad, yieldShareBps);
  }
  const floors = sellFloors({
    dollar, quotedUsdtOut: quotedUsdt, feeBps: config.feeBps, slipBps: config.slipBps, prices, minUsdtOut,
    projectedPPlusWad,
  });
  if (floors.savingsMintTooSmall) throw codedError('savings_mint_too_small');
  const expectedNetWei = sellNetUsdt(quotedUsdt, config.feeBps);
  if (floors.minUsdtOut <= 0n || floors.minDestOut <= 0n) {
    throw new Error('El monto es demasiado pequeño para vender.');
  }

  const needsApprove = (await getErc20Allowance(wallet.address, config.router, params.asset.address)) < units;
  const calls: BatchCall[] = [
    ...(needsApprove ? [approveCall(params.asset.address, config.router)] : []),
    {
      to: config.router,
      valueWei: 0n,
      data: encodeCryptoSellCall({
        dollar,
        tokenIn: params.asset.address,
        amountIn: units,
        route: quote.route,
        minUsdtOut: floors.minUsdtOut,
        minDestOut: floors.minDestOut,
        maxFeeBps: config.feeBps,
      }),
    },
  ];
  const result = await executeSponsoredBatch({ wallet, calls, delegateAddress, requestId });
  return {
    txHash: result.txHash,
    unitsSold: units,
    expectedNetWei,
    feeWei: quotedUsdt - expectedNetWei,
    feeBps: Number(config.feeBps),
    dollar,
  };
};
