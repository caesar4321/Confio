// Ondo GM stock execution — binding attestations + sponsored router calls.
//
// The server owns the Ondo API keys and returns signed quote material. The
// device owns the user's EVM key and signs one EIP-712 batch containing an
// optional ERC-20 approval plus the exact router call. Confío sponsors gas;
// neither the backend nor the sponsor can alter the signed calls.

import { gql } from '@apollo/client';

import {
  BatchCall,
  encodeCall,
} from './evmWallet';
import { encodeBuyStockCall, encodeSellStockCall, GmRouterQuote } from './ondoStocksAbi';
import { installBscServerTransport } from './bscServerRpc';
import {
  getErc20Allowance,
  getErc20BalanceWei,
  getVaultPrices,
  getVaultShares,
  predictRedeemUsdtOut,
  predictSubscribeSharesOut,
  sharesForUsdtOut,
} from './cusdPlusVault';
import { getActiveEvmWallet } from './secureDeterministicWallet';
import {
  createSponsoredRequestId,
  executeSponsoredBatch,
  fetchSponsored7702Params,
} from './sponsored7702';

const WAD = 10n ** 18n;
const BPS = 10_000n;
const MAX_UINT256 = (1n << 256n) - 1n;

const STOCK_CONFIG = gql`
  query StockTradingConfig {
    cusdPlusSummary {
      stocksTradingEnabled
    }
    cusdPlusConvertParams {
      vaultAddress
      stockRouterAddress
      gmTradeFeeBps
    }
  }
`;

const SOFT_QUOTE = gql`
  query GmSoftQuote($symbol: String!, $side: String!, $notionalValue: String!, $duration: String) {
    gmSoftQuote(symbol: $symbol, side: $side, notionalValue: $notionalValue, duration: $duration) {
      success errorCode errorMessage chainId symbol ticker assetAddress side tokenAmount price notionalWei
    }
  }
`;

const PREPARE_TRADE = gql`
  mutation PrepareGmTrade(
    $requestId: String!
    $symbol: String!
    $side: String!
    $notionalValue: String!
    $duration: String
  ) {
    prepareGmTrade(
      requestId: $requestId
      symbol: $symbol
      side: $side
      notionalValue: $notionalValue
      duration: $duration
    ) {
      quote {
        success errorCode errorMessage attestationId userId chainId symbol ticker assetAddress side
        tokenAmount price expiration signatureHex additionalDataHex notionalWei
      }
    }
  }
`;

export interface GmTradeQuote extends GmRouterQuote {
  success: boolean;
  errorCode?: string;
  errorMessage?: string;
  attestationId?: string;
  userId?: string;
  chainId: string;
  symbol: string;
  ticker: string;
  assetAddress: string;
  side: string;
  tokenAmount: string;
  price: string;
  expiration?: number;
  signatureHex?: string;
  additionalDataHex?: string;
  notionalWei: string;
}

interface StockConfig {
  enabled: boolean;
  vaultAddress: string;
  routerAddress: string;
  feeBps: bigint;
}

const formatWei = (value: bigint): string => {
  const whole = value / WAD;
  const frac = (value % WAD).toString().padStart(18, '0').replace(/0+$/, '');
  return frac ? `${whole}.${frac}` : whole.toString();
};

export const usdToWei = (value: number): bigint => {
  if (!Number.isFinite(value) || value <= 0) return 0n;
  const fixed = value.toFixed(18);
  const [whole, frac = ''] = fixed.split('.');
  return BigInt(whole) * WAD + BigInt(frac.padEnd(18, '0').slice(0, 18));
};

const stockError = (quote: Partial<GmTradeQuote>): Error => {
  const code = quote.errorCode || 'QUOTE_UNAVAILABLE';
  const messages: Record<string, string> = {
    MARKET_CLOSED: 'El mercado está cerrado en este momento.',
    MARKET_PAUSED: 'La negociación está pausada temporalmente.',
    TRADE_NOT_AVAILABLE: 'Esta inversión no está disponible en tu ubicación.',
    TRADING_DISABLED: 'La compra y venta de acciones aún no está habilitada.',
    SPONSOR_NOT_CONFIGURED: 'Las operaciones patrocinadas no están disponibles en este momento.',
    FEE_CONFIG_MISMATCH: 'La configuración de la comisión no coincide con el contrato.',
    RATE_LIMITED: 'Espera un momento antes de solicitar otra cotización.',
    QUOTE_IN_PROGRESS: 'La cotización ya se está preparando. Inténtalo de nuevo en un momento.',
    BAD_NOTIONAL: 'El monto está fuera de los límites permitidos.',
  };
  return new Error(messages[code] || quote.errorMessage || 'No pudimos obtener una cotización de Ondo.');
};

const fetchConfig = async (): Promise<StockConfig> => {
  const { apolloClient } = await import('../apollo/client');
  const { data } = await apolloClient.query({ query: STOCK_CONFIG, fetchPolicy: 'no-cache' });
  const p = data?.cusdPlusConvertParams;
  const config = {
    enabled: Boolean(data?.cusdPlusSummary?.stocksTradingEnabled),
    vaultAddress: p?.vaultAddress || '',
    routerAddress: p?.stockRouterAddress || '',
    feeBps: BigInt(p?.gmTradeFeeBps ?? 30),
  };
  if (!config.enabled || !config.vaultAddress || !config.routerAddress || config.feeBps !== 30n) {
    throw new Error('La compra y venta de acciones aún no está habilitada.');
  }
  return config;
};

const requestQuote = async (
  binding: boolean,
  symbol: string,
  side: 'buy' | 'sell',
  notionalWei: bigint,
  duration: 'short' | 'long' = 'short',
  requestId?: string,
): Promise<GmTradeQuote> => {
  const { apolloClient } = await import('../apollo/client');
  const variables = { symbol, side, notionalValue: formatWei(notionalWei), duration };
  const response = binding
    ? await apolloClient.mutate({
        mutation: PREPARE_TRADE,
        variables: { ...variables, requestId: requestId || createSponsoredRequestId() },
      })
    : await apolloClient.query({ query: SOFT_QUOTE, variables, fetchPolicy: 'no-cache' });
  const quote = (binding ? response.data?.prepareGmTrade?.quote : response.data?.gmSoftQuote) as GmTradeQuote;
  if (!quote?.success) throw stockError(quote || {});
  return quote;
};

export const getSoftStockQuote = async (
  symbol: string,
  side: 'buy' | 'sell',
  grossAmountUsd: number,
  feeBps = 30,
): Promise<GmTradeQuote> => {
  const gross = usdToWei(grossAmountUsd);
  const notional = side === 'buy' ? gross - (gross * BigInt(feeBps)) / BPS : gross;
  return requestQuote(false, symbol, side, notional);
};

const approveCall = (token: string, router: string): BatchCall => ({
  to: token,
  valueWei: 0n,
  data: encodeCall('approve(address,uint256)', [
    { type: 'address', value: router },
    { type: 'uint', value: MAX_UINT256 },
  ]),
});

const requireSponsored = async () => {
  const sponsored = await fetchSponsored7702Params();
  if (!sponsored.enabled || !sponsored.delegateAddress) {
    throw new Error('Las operaciones patrocinadas no están disponibles en este momento.');
  }
  return sponsored.delegateAddress;
};

export const buyStockWithSavings = async (params: {
  symbol: string;
  grossAmountUsd: number;
  minTokenAmountWei?: bigint;
  requestId?: string;
}): Promise<{ txHash: string; tokenAmountWei: bigint; feeWei: bigint }> => {
  installBscServerTransport();
  const [config, wallet, delegateAddress] = await Promise.all([
    fetchConfig(), getActiveEvmWallet(), requireSponsored(),
  ]);
  const grossTarget = usdToWei(params.grossAmountUsd);
  const requestId = params.requestId || createSponsoredRequestId();
  const requestedSpend = grossTarget - (grossTarget * config.feeBps) / BPS;
  const quote = await requestQuote(true, params.symbol, 'buy', requestedSpend, 'short', `${requestId}_q0`);
  if (params.minTokenAmountWei && BigInt(quote.tokenAmount) < params.minTokenAmountWei) {
    throw new Error('El precio cambió más de 1%. Revisa la nueva cotización antes de continuar.');
  }
  const spend = BigInt(quote.notionalWei);
  const fee = (spend * config.feeBps + (BPS - config.feeBps) - 1n) / (BPS - config.feeBps);
  const requiredGross = spend + fee;

  const [{ pPlusWad, oraclePriceWad }, ownedShares] = await Promise.all([
    getVaultPrices(config.vaultAddress),
    getVaultShares(config.vaultAddress, wallet.address),
  ]);
  let shares = sharesForUsdtOut(requiredGross, pPlusWad);
  // The ceiling helper can ask for one share above the wallet balance at MAX.
  // Use the complete position when its live redemption value still covers the
  // attested debit; otherwise preserve the insufficient-balance failure.
  if (shares > ownedShares && predictRedeemUsdtOut(ownedShares, pPlusWad, oraclePriceWad) >= requiredGross) {
    shares = ownedShares;
  }
  if (shares <= 0n || shares > ownedShares || predictRedeemUsdtOut(shares, pPlusWad, oraclePriceWad) < requiredGross) {
    throw new Error('Tu ahorro disponible no alcanza para completar esta compra.');
  }

  const needsApprove = (await getErc20Allowance(wallet.address, config.routerAddress, config.vaultAddress)) < shares;
  const calls: BatchCall[] = [
    ...(needsApprove ? [approveCall(config.vaultAddress, config.routerAddress)] : []),
    {
      to: config.routerAddress,
      valueWei: 0n,
      data: encodeBuyStockCall(quote, shares, spend, requiredGross, config.feeBps),
    },
  ];
  const result = await executeSponsoredBatch({ wallet, calls, delegateAddress, requestId });
  return { txHash: result.txHash, tokenAmountWei: BigInt(quote.tokenAmount), feeWei: fee };
};

export const sellStockToSavings = async (params: {
  symbol: string;
  grossAmountUsd: number;
  /** MAX is a user intent, not an imprecise USD valuation. Requote against
   * the exact on-chain token balance when the first quote rounds above it. */
  sellAll?: boolean;
  minExpectedNetWei?: bigint;
  requestId?: string;
}): Promise<{ txHash: string; tokenAmountWei: bigint; expectedNetWei: bigint }> => {
  installBscServerTransport();
  const [config, wallet, delegateAddress] = await Promise.all([
    fetchConfig(), getActiveEvmWallet(), requireSponsored(),
  ]);
  const requestId = params.requestId || createSponsoredRequestId();
  let quote = await requestQuote(
    true, params.symbol, 'sell', usdToWei(params.grossAmountUsd), 'short', `${requestId}_q0`);
  let quantity = BigInt(quote.tokenAmount);
  const held = await getErc20BalanceWei(quote.assetAddress, wallet.address);
  // The portfolio card is a floating USD display value, so MAX can initially
  // quote one or more token wei above the real balance. The signed GM quote
  // cannot be edited locally. Ask Ondo for a fresh binding quote whose USD
  // notional is derived from the exact balance and the latest signed price.
  // A second pass covers a price update between attestations without ever
  // transferring more than the user owns.
  for (let attempt = 0; params.sellAll && quantity !== held && attempt < 2; attempt += 1) {
    // Ceil here because Ondo derives token quantity by flooring the inverse
    // operation. A floored notional can otherwise leave one token wei behind.
    const balanceNotional = (held * BigInt(quote.price) + WAD - 1n) / WAD;
    if (balanceNotional <= 0n) break;
    quote = await requestQuote(
      true, params.symbol, 'sell', balanceNotional, 'short', `${requestId}_q${attempt + 1}`);
    quantity = BigInt(quote.tokenAmount);
  }
  if (params.sellAll && quantity !== held) {
    throw new Error('El precio cambió mientras calculábamos MAX. Actualiza tu posición e inténtalo de nuevo.');
  }
  if (quantity <= 0n || quantity > held) throw new Error('No tienes suficientes unidades para completar esta venta.');

  const quoteCost = (quantity * BigInt(quote.price)) / WAD;
  const minUsdt = (quoteCost * 99n) / 100n;
  const expectedFee = (quoteCost * config.feeBps) / BPS;
  const expectedNet = quoteCost - expectedFee;
  if (params.minExpectedNetWei && expectedNet < params.minExpectedNetWei) {
    throw new Error('El precio cambió más de 1%. Revisa la nueva cotización antes de continuar.');
  }
  const { pPlusWad, oraclePriceWad } = await getVaultPrices(config.vaultAddress);
  const expectedShares = predictSubscribeSharesOut(expectedNet, pPlusWad, oraclePriceWad);
  const minShares = (expectedShares * 99n) / 100n;
  if (minUsdt <= 0n || minShares <= 0n) throw new Error('El monto es demasiado pequeño para vender.');

  const needsApprove = (await getErc20Allowance(wallet.address, config.routerAddress, quote.assetAddress)) < quantity;
  const calls: BatchCall[] = [
    ...(needsApprove ? [approveCall(quote.assetAddress, config.routerAddress)] : []),
    {
      to: config.routerAddress,
      valueWei: 0n,
      data: encodeSellStockCall(quote, minUsdt, minShares, config.feeBps),
    },
  ];
  const result = await executeSponsoredBatch({ wallet, calls, delegateAddress, requestId });
  return { txHash: result.txHash, tokenAmountWei: quantity, expectedNetWei: expectedNet };
};
