// Futuros (Hyperliquid perps) — the client half of cusd_plus/perps_flow.
//
// Every money step is issued by the server (exact BSC calls, exact
// Hyperliquid actions) and signed here with the member's own key. Before
// signing, this module re-checks what it is asked to sign: calls may only
// touch Confío's dollars, USDT and Relay's depository, pay the member's own
// address, and Hyperliquid actions may only move USDC between the member's
// own balances or to Relay. A server can ask; it can never make the app sign
// a payment to someone else.
//
// Open:  exit + Relay deposit (one sponsored batch) → wait for Relay → sign
//        the open plan (leverage, order) on Hyperliquid.
// Close: sign the reduce-only close → bring the money home (Relay
//        withdrawal: nonce mapping + sendAsset) → sign the entry batch.
// Each stage is resumable: the server tracks the position's next step.
//
// Every query here is its own document (isolated-field rule): against a
// server without Futuros only these fail, and a failure reads as
// "not available".

import { gql } from '@apollo/client';

import { BatchCall, RELAY_BSC_DEPOSITORY, isTrustedDelegate, selector } from './evmWallet';
import { BUNDLED_CUSD_ADDRESS, BUNDLED_VAULT_ADDRESS, publicBscCall } from './emergencyExit/bscExit';
import { positionValueUsd } from '../utils/perpsPresentation';
import {
  bindDepositQuote, bindReturnQuote,
} from './relayQuotes';
import {
  fetchBounded, venueFill, venueLeverage, venueMarket, venueOrderOutcome, venuePosition, venueTriggers,
} from './hyperliquidInfo';
import { HlSignature, nextNonce, signAction, signRelayNonceMapping } from './hyperliquidSigning';

const client = async () => (await import('../apollo/client')).apolloClient;

export const RELAY_HL_DEPOSITORY = '0x66cf0aace1b4e562593bec10ec7868fba9932224';
export const HL_USDC_TOKEN = 'USDC:0x6d1e7cde53ba9467b783cb7c530ce054';
const USDT_BSC = '0x55d398326f99059ff775485246999027b3197955';

// ── documents ───────────────────────────────────────────────────────────

export const GET_PERPS_CAPABILITIES = gql`
  query PerpsCapabilities {
    perpsCapabilities {
      enabled
      tradingEnabled
      openEnabled
      ackRequired
      ackVersion
      disclosureTitle
      disclosurePoints
      promotionAllowed
      fundingDollar
      feeBps
      impactWarnBps
      impactMaxBps
      slippageBps
      minMarginUsd
      firstMinMarginUsd
      newAccountChargeUsd
      newAccount
      blockedMessage
    }
  }
`;

export const GET_PERPS_MARKETS = gql`
  query PerpsMarkets {
    perpsMarkets {
      coin
      dex
      ticker
      name
      assetClass
      assetId
      szDecimals
      maxLeverage
      onlyIsolated
      takerFeeRate
      markPx
      dayChangePct
      fundingRate
      openInterestUsd
      dayVolumeUsd
    }
  }
`;

export const GET_PERPS_CANDLES = gql`
  query PerpsCandles($coin: String!, $range: String) {
    perpsCandles(coin: $coin, range: $range) {
      timestamp
      close
    }
  }
`;

const POSITION_FIELDS = `
  id coin ticker name assetClass side leverage marginUsd state stepError nextAction
  size entryPx markPx unrealizedPnlUsd returnOnEquity liquidationPx marginUsedUsd valueUsd pendingMarginUsd protectionKnown takeProfitPx stopLossPx
  positionValueUsd fundingUsd realizedPnlUsd venueFeesUsd returnedUsd resultUsd putInUsd liquidation
  costs { marginUsd exitFeeUsd bridgeCostUsd activationUsd creditedUsd notionalUsd openFeeUsd }
  createdAt openedAt closedAt doneAt
`;

export const GET_PERPS_POSITIONS = gql`
  query PerpsPositions($includeDone: Boolean) {
    perpsPositions(includeDone: $includeDone) { ${POSITION_FIELDS} }
  }
`;

const ACKNOWLEDGE = gql`
  mutation AcknowledgePerpsRisk($version: Int!) {
    acknowledgePerpsRisk(version: $version) { success error }
  }
`;

const BATCH_PLAN = `success error positionId callsJson requestId kind deadline relayQuoteJson
  costs { marginUsd exitFeeUsd bridgeCostUsd activationUsd creditedUsd notionalUsd openFeeUsd }`;

const PREPARE_OPEN = gql`
  mutation PerpsPrepareOpen($coin: String!, $side: String!, $leverage: Int!, $marginUsd: String!) {
    perpsPrepareOpen(coin: $coin, side: $side, leverage: $leverage, marginUsd: $marginUsd) { ${BATCH_PLAN} }
  }
`;
const PREPARE_MARGIN_ADD = gql`
  mutation PerpsPrepareMarginAdd($positionId: ID!, $amountUsd: String!) {
    perpsPrepareMarginAdd(positionId: $positionId, amountUsd: $amountUsd) { ${BATCH_PLAN} }
  }
`;
const PREPARE_RETRY = gql`
  mutation PerpsPrepareBridgeRetry($positionId: ID!) {
    perpsPrepareBridgeRetry(positionId: $positionId) { ${BATCH_PLAN} }
  }
`;
const PREPARE_ENTRY = gql`
  mutation PerpsPrepareEntry($positionId: ID!) {
    perpsPrepareEntry(positionId: $positionId) { ${BATCH_PLAN} }
  }
`;
const PLAN = gql`
  mutation PerpsPlan($positionId: ID!, $stage: String!, $takeProfitPx: String, $stopLossPx: String) {
    perpsPlan(positionId: $positionId, stage: $stage, takeProfitPx: $takeProfitPx, stopLossPx: $stopLossPx) {
      success error replan impactBps impactWarn avgPx size liquidationPx relayQuoteJson
      steps { purpose actionJson }
      mappingTypedJson sendActionJson returnUsd returnMinUsd
    }
  }
`;
const SUBMIT_ACTION = gql`
  mutation PerpsSubmitAction($positionId: ID!, $purpose: String!, $actionJson: String!, $nonce: String!,
                             $signature: PerpSignatureInput!) {
    perpsSubmitAction(positionId: $positionId, purpose: $purpose, actionJson: $actionJson, nonce: $nonce,
                      signature: $signature) { success error state }
  }
`;
const SUBMIT_RETURN = gql`
  mutation PerpsSubmitReturn($positionId: ID!, $mappingSignature: PerpSignatureInput!,
                             $sendSignature: PerpSignatureInput!) {
    perpsSubmitReturn(positionId: $positionId, mappingSignature: $mappingSignature,
                      sendSignature: $sendSignature) { success error state }
  }
`;
const RELEASE_REFUND = gql`
  mutation PerpsReleaseRefund($positionId: ID!) { perpsReleaseRefund(positionId: $positionId) { success error } }
`;
const CANCEL_QUOTE = gql`
  mutation PerpsCancelQuote($positionId: ID!) { perpsCancelQuote(positionId: $positionId) { success } }
`;
const DOLLAR_ADDRESSES = gql`
  query PerpsDollarAddresses { cusdPlusConvertParams { vaultAddress cusdAddress } }
`;

// ── types ───────────────────────────────────────────────────────────────

export type AssetClass = 'crypto' | 'stock' | 'index' | 'commodity' | 'fx';
export type Side = 'long' | 'short';

export interface PerpsCapabilities {
  enabled: boolean;
  tradingEnabled: boolean;
  openEnabled: boolean;
  ackRequired: boolean;
  ackVersion: number;
  disclosureTitle: string;
  disclosurePoints: string[];
  promotionAllowed: boolean;
  fundingDollar: 'cusd_plus' | 'cusd';
  feeBps: number | null;
  impactWarnBps: number;
  impactMaxBps: number;
  slippageBps: number;
  minMarginUsd: number;
  firstMinMarginUsd: number;
  newAccountChargeUsd: number;
  /** The Hyperliquid account does not exist yet (null: unknown). */
  newAccount: boolean | null;
  blockedMessage: string | null;
}

export interface PerpMarket {
  coin: string;
  dex: string;
  ticker: string;
  name: string;
  assetClass: AssetClass;
  assetId: number;
  szDecimals: number;
  maxLeverage: number;
  onlyIsolated: boolean;
  takerFeeRate: number;
  markPx: number | null;
  dayChangePct: number | null;
  fundingRate: number | null;
  openInterestUsd: number | null;
  dayVolumeUsd: number | null;
}

export interface PerpCosts {
  marginUsd: number | null;
  exitFeeUsd: number | null;
  bridgeCostUsd: number | null;
  activationUsd: number | null;
  creditedUsd: number | null;
  notionalUsd: number | null;
  openFeeUsd: number | null;
}

export type NextAction =
  | 'sign_open' | 'wait_bridge' | 'retry_bridge' | 'open_order' | 'manage' | 'finish_margin'
  | 'return' | 'enter' | 'wait_return' | 'none';

export interface PerpPosition {
  id: string;
  coin: string;
  ticker: string;
  name: string;
  assetClass: AssetClass;
  side: Side;
  leverage: number;
  marginUsd: number;
  state: string;
  stepError: string | null;
  nextAction: NextAction;
  size: number | null;
  entryPx: number | null;
  markPx: number | null;
  unrealizedPnlUsd: number | null;
  returnOnEquity: number | null;
  liquidationPx: number | null;
  marginUsedUsd: number | null;
  /** What this position's money is worth now, whatever its step (null: not known yet). */
  valueUsd: number | null;
  /** A top-up that arrived and waits to join the margin: what it adds. */
  pendingMarginUsd: number | null;
  /** The venue answered the protection lookup (false: unknown — never replace it). */
  protectionKnown: boolean | null;
  /** Live protection triggers on the venue. */
  takeProfitPx: number | null;
  stopLossPx: number | null;
  positionValueUsd: number | null;
  fundingUsd: number | null;
  realizedPnlUsd: number | null;
  venueFeesUsd: number | null;
  returnedUsd: number | null;
  resultUsd: number | null;
  /** Dollars put in (margin + top-ups), less top-ups that came back. */
  putInUsd: number | null;
  liquidation: string | null;
  costs: PerpCosts | null;
  createdAt: string;
  openedAt: string | null;
  closedAt: string | null;
  doneAt: string | null;
}

// ── errors ──────────────────────────────────────────────────────────────

const ERROR_COPY: Record<string, string> = {
  trade_not_available: 'Los futuros no están disponibles para tu cuenta en este momento.',
  perps_ack_required: 'Antes de tu primera operación, lee y acepta cómo funcionan los futuros.',
  open_pending: 'Tu orden anterior todavía puede llegar a Hyperliquid. Por seguridad no firmamos otra; inténtalo mañana o trae tu dinero de vuelta.',
  return_amount_changed: 'No trajimos tu dinero: Hyperliquid muestra un monto distinto al de tu posición. Inténtalo de nuevo.',
  close_declined: 'Tu posición sigue abierta. Puedes intentar cerrarla de nuevo cuando haya más liquidez.',
  impact_declined: 'No abrimos la posición. Tu margen ya está en Hyperliquid: puedes abrirla más tarde o traer tu dinero de vuelta.',
  margin_too_small: 'El margen es muy pequeño para esta operación.',
  notional_too_small: 'La posición es muy pequeña: Hyperliquid pide al menos US$10. Sube el margen o el apalancamiento.',
  position_exists: 'Ya tienes una posición abierta en este mercado. Puedes agregarle margen.',
  insufficient_funds: 'No tienes saldo suficiente en dólares para este margen.',
  bad_leverage: 'Ese apalancamiento no está disponible en este mercado.',
  market_not_openable: 'Este mercado no acepta posiciones nuevas por ahora.',
  market_not_listed: 'Este mercado ya no está disponible.',
  impact_too_high: 'El mercado está muy delgado para este monto: el precio se movería demasiado. Prueba con menos.',
  market_too_thin: 'No hay suficiente liquidez para este monto ahora mismo.',
  hyperliquid_unavailable: 'Hyperliquid no responde en este momento. Tu dinero está seguro; intenta de nuevo en unos minutos.',
  relay_unavailable: 'La transferencia entre redes no está disponible en este momento. Intenta de nuevo en unos minutos.',
  order_not_filled: 'El precio se movió antes de ejecutar la orden. Tu margen sigue en tu cuenta: intenta de nuevo.',
  hyperliquid_rejected: 'Hyperliquid rechazó la operación. Tu dinero sigue en tu cuenta.',
  return_quote_expired: 'La cotización venció. Vuelve a intentarlo.',
  perps_quote_expired: 'La cotización venció. Vuelve a intentarlo.',
  perps_quote_not_found: 'La cotización ya no es válida. Vuelve a intentarlo.',
  nothing_to_return: 'No hay saldo para traer de vuelta todavía.',
  position_already_closed: 'Esta posición ya se cerró.',
  bad_trigger_side: 'Revisa los precios: la toma de ganancia y el stop deben estar del lado correcto del precio de entrada.',
  amount_too_small: 'El monto es muy pequeño para mover en este momento.',
  unsafe_plan: 'No pudimos verificar la operación. Por seguridad no se firmó nada.',
  refunded: 'La transferencia a Hyperliquid no se completó y tus USDT volvieron a tu cuenta. Puedes reintentar.',
  timeout: 'Esto está tardando más de lo normal. Puedes salir: seguimos el proceso y te avisamos.',
  finish_pending_first: 'Primero termina tu otra operación en curso (por ejemplo, traer a tus dólares una posición cerrada).',
  step_out_of_order: 'La operación cambió mientras firmabas. Vuelve a intentarlo.',
  plan_expired: 'La operación venció. Vuelve a intentarlo.',
  action_mismatch: 'La operación cambió mientras firmabas. Vuelve a intentarlo.',
  already_open: 'Tu posición ya está abierta.',
  entry_in_flight: 'Tu dinero ya está entrando a tus dólares.',
  nothing_to_bridge: 'No encontramos los USDT devueltos en tu cuenta.',
  one_position_at_a_time: 'Por ahora puedes tener una posición a la vez: cierra la que tienes para abrir otra.',
  step_in_flight: 'Hay un paso en curso. Espera unos segundos y vuelve a intentarlo.',
  step_unconfirmed: 'Estamos confirmando tu último paso con Hyperliquid. Intenta de nuevo en un minuto.',
  margin_change_in_flight: 'Tu margen extra todavía va en camino. Espera unos segundos.',
  tpsl_rejected: 'Hyperliquid no aceptó uno de los niveles de protección. Revisa los precios e inténtalo de nuevo.',
};

export const perpsErrorCopy = (error: unknown): string => {
  const code = (error as { code?: string } | null)?.code;
  if (code && ERROR_COPY[code]) return ERROR_COPY[code];
  const message = error instanceof Error ? error.message : '';
  const known = Object.keys(ERROR_COPY).find((c) => new RegExp(`\\b${c}\\b`).test(message));
  return known ? ERROR_COPY[known] : 'No pudimos completar la operación. Tu dinero sigue seguro en tu cuenta.';
};

const WAD = 10n ** 18n;

/** "12.34" dollars → 18-decimal wei, exactly (no float). */
export const usdToWei = (usd: string | number): bigint => {
  const text = typeof usd === 'number' ? usd.toFixed(6) : String(usd).trim();
  if (!/^\d+(\.\d+)?$/.test(text)) throw coded('unsafe_plan');
  const [whole, frac = ''] = text.split('.');
  return BigInt(whole) * WAD + BigInt((frac + '0'.repeat(18)).slice(0, 18));
};

const coded = (code: string): Error =>
  Object.assign(new Error(ERROR_COPY[code] || code), { code });

// ── safety checks on what the server asks us to sign ───────────────────

const word = (data: string, i: number) => data.slice(10 + i * 64, 10 + (i + 1) * 64);
const wordAddress = (data: string, i: number) => '0x' + word(data, i).slice(24);

const SEL = {
  approve: selector('approve(address,uint256)').slice(2),
  cusdRedeem: selector('redeemWithFee(uint256,uint256,address)').slice(2),
  plusRedeem: selector('redeemToUsdt(uint256,uint256,address)').slice(2),
  cusdMint: selector('mintWithFee(uint256,uint256,address)').slice(2),
  plusMint: selector('subscribeAndMint(uint256,uint256,address)').slice(2),
  relayDeposit: 'e8017952',
};

interface IssuedCall { to: string; value: string; data: string }

export interface CallBounds {
  /** 'out': dollars → Relay (open, top-up, bridge retry): exactly one Relay
   *  deposit, nothing above `maxWei`. 'in': USDT → the member's own dollars
   *  (the entry): no Relay, no redemption. */
  direction: 'out' | 'in';
  /** The most dollars (18 decimals) the member reviewed for this step. */
  maxWei: bigint | null;
  /** Confío Dollar+ price per share (1e18), read from the chain, to value
   *  a share redemption against `maxWei`. */
  plusPriceWad?: bigint | null;
  /** The dollar the member saw leaving: exactly one redemption of it is
   *  required (an open or a top-up never spends loose USDT instead). */
  dollar?: 'cusd' | 'cusd_plus' | null;
  /** A refund retry re-sends USDT already on the wallet: no redemption at all. */
  refundRetry?: boolean;
  /** The Relay order the app fetched itself: the deposit must be exactly its call. */
  relayDeposit?: { depository: string; depositData: string } | null;
}

/** Rounding room on a redemption: a share redemption is rounded up. */
const REDEEM_SLACK_BPS = 100n;

const wordUint = (data: string, i: number) => {
  const w = word(data, i);
  if (w.length !== 64) throw coded('unsafe_plan');
  return BigInt('0x' + w);
};

/** Refuse anything but Confío-dollar exits/entries to the member, approvals
 *  to Confío's vaults or Relay, and one Relay deposit credited to the member,
 *  for no more than the member reviewed. */
export const verifyIssuedCalls = (
  calls: IssuedCall[],
  wallet: string,
  dollars: { vaultAddress: string; cusdAddress: string },
  bounds: CallBounds,
): BatchCall[] => {
  const me = wallet.toLowerCase();
  const vault = dollars.vaultAddress.toLowerCase();
  const cusd = dollars.cusdAddress.toLowerCase();
  const out = bounds.direction === 'out';
  const spenders = new Set((out ? [RELAY_BSC_DEPOSITORY] : [vault, cusd]).filter(Boolean));
  if (!Array.isArray(calls) || calls.length === 0 || calls.length > 4) throw coded('unsafe_plan');
  const capped = (amount: bigint) => {
    if (bounds.maxWei != null && amount > bounds.maxWei) throw coded('unsafe_plan');
  };
  let deposits = 0;
  let depositWei = 0n;
  let redemptions = 0;
  let redeemedWei = 0n;
  let minOutWei = 0n; // what the redemptions guarantee in USDT (or revert)
  const verified = calls.map((c) => {
    const to = String(c.to).toLowerCase();
    const data = String(c.data).toLowerCase();
    if (String(c.value) !== '0' || !/^0x[0-9a-f]*$/.test(data)) throw coded('unsafe_plan');
    const sel = data.slice(2, 10);
    if (sel === SEL.approve && to === USDT_BSC) {
      if (!spenders.has(wordAddress(data, 0))) throw coded('unsafe_plan');
      capped(wordUint(data, 1));
    } else if (out && to === cusd && sel === SEL.cusdRedeem && bounds.dollar !== 'cusd_plus') {
      if (wordAddress(data, 2) !== me) throw coded('unsafe_plan');
      redeemedWei += wordUint(data, 0); // cUSD is one dollar per unit
      minOutWei += wordUint(data, 1);
      redemptions += 1;
    } else if (out && to === vault && sel === SEL.plusRedeem && bounds.dollar !== 'cusd') {
      // Shares, valued at the chain's share price.
      if (wordAddress(data, 2) !== me) throw coded('unsafe_plan');
      minOutWei += wordUint(data, 1);
      redemptions += 1;
      if (bounds.maxWei != null) {
        if (!bounds.plusPriceWad || bounds.plusPriceWad <= 0n) throw coded('unsafe_plan');
        redeemedWei += (wordUint(data, 0) * bounds.plusPriceWad) / WAD;
      }
    } else if (!out && ((to === cusd && sel === SEL.cusdMint) || (to === vault && sel === SEL.plusMint))) {
      if (wordAddress(data, 2) !== me) throw coded('unsafe_plan');
      redeemedWei += wordUint(data, 0); // USDT in: all mints together stay within what landed
    } else if (out && to === RELAY_BSC_DEPOSITORY && sel === SEL.relayDeposit) {
      if (wordAddress(data, 0) !== me || wordAddress(data, 1) !== USDT_BSC) throw coded('unsafe_plan');
      // Only into the order Relay created for the member (the app asked for it).
      if (out && (!bounds.relayDeposit || to !== bounds.relayDeposit.depository
          || data !== bounds.relayDeposit.depositData.toLowerCase())) {
        throw coded('unsafe_plan');
      }
      capped(wordUint(data, 2));
      depositWei += wordUint(data, 2);
      deposits += 1;
    } else {
      throw coded('unsafe_plan');
    }
    return { to, valueWei: 0n, data };
  });
  if (out && deposits !== 1) throw coded('unsafe_plan');
  if (out && bounds.dollar && redemptions !== 1) throw coded('unsafe_plan');
  if (out && bounds.refundRetry && redemptions !== 0) throw coded('unsafe_plan');
  if (out && bounds.dollar && bounds.maxWei != null) {
    // The reviewed dollars are what is redeemed (rounding aside), and the
    // deposit never exceeds what that redemption yields: no loose USDT spent.
    // The deposit is covered by what the redemption guarantees (its minimum
    // out, net of the exit fee, or it reverts): loose USDT is never spent;
    // and that is the reviewed amount less the exit costs (≤ 2%).
    if (redeemedWei < (bounds.maxWei * 99n) / 100n || depositWei > minOutWei
        || minOutWei < (bounds.maxWei * 98n) / 100n || depositWei < (bounds.maxWei * 98n) / 100n) {
      throw coded('unsafe_plan');
    }
  }
  if (bounds.maxWei != null && redeemedWei > bounds.maxWei + (bounds.maxWei * REDEEM_SLACK_BPS) / 10_000n) {
    throw coded('unsafe_plan'); // all redemptions (or mints) together, never more than reviewed
  }
  if (!out && bounds.maxWei != null && redeemedWei === 0n) throw coded('unsafe_plan');
  return verified;
};

const ALLOWED_BY_PURPOSE: Record<string, string[]> = {
  abstraction: ['userSetAbstraction'],
  fund_dex: ['sendAsset'],
  margin_fund_dex: ['sendAsset'],
  return_dex: ['sendAsset'],
  leverage: ['updateLeverage'],
  margin_add: ['updateIsolatedMargin'],
  open_order: ['order'],
  close_order: ['order'],
  tpsl_cancel: ['cancel'],
  tpsl: ['order'],
};

export type PlanStage = 'open' | 'close' | 'tpsl' | 'margin' | 'return';

const STAGE_PURPOSES: Record<PlanStage, string[]> = {
  open: ['abstraction', 'fund_dex', 'leverage', 'open_order'],
  close: ['close_order'],
  tpsl: ['tpsl_cancel', 'tpsl'],
  margin: ['margin_fund_dex', 'margin_add'],
  return: ['return_dex'],
};

/** The trade the member chose: every action must be exactly about it. */
export interface TradeContext {
  stage: PlanStage;
  assetId: number;
  dex: string;
  side: Side;
  leverage: number;
  /** Hyperliquid's mark price now: sizes and limits are judged against it. */
  markPx: number;
  /** Largest order value (size × mark) the member's margin allows. */
  maxNotionalUsd: number;
  /** Reduce-only stages: the live size on the venue (never close more). */
  maxSize?: number | null;
  /** Dollars the member chose to move in this stage (a top-up), if known. */
  budgetUsd?: number | null;
  /** The protection prices the member entered. */
  triggers?: { tp: number | null; sl: number | null };
  /** A close deeper than CLOSE_PX_DEVIATION the member confirmed (thin book). */
  deepCloseOk?: boolean;
  /** The least exposure (size × mark) the open must deliver: what was reviewed, less costs. */
  minNotionalUsd?: number | null;
}

/** How far from the mark an order's limit may sit: opens are tight (the
 *  server uses its slippage setting), closes get room to fill. */
const OPEN_PX_DEVIATION = 0.05; // max price impact (3%) + slippage, with room
const CLOSE_PX_DEVIATION = 0.15;
const TRIGGER_TOLERANCE = 0.005;
/** A trigger's execution limit stays within this of its trigger price. */
const TRIGGER_LIMIT_DEVIATION = 0.1;
/** Beyond this, a close is not signed even when confirmed. */
const MAX_CLOSE_PX_DEVIATION = 0.5;
/** A top-up must add at least this share of the reviewed amount (the rest is crossing costs). */
const MIN_TOPUP_SHARE = 0.85;

const finite = (v: unknown): number => {
  const n = Number(v);
  if (!Number.isFinite(n)) throw coded('unsafe_plan');
  return n;
};

/** A Hyperliquid action only moves the member's own USDC between their own
 *  balances (or to Relay, on the return), on the member's own account, and
 *  trades only the market, side, leverage and size the member chose. */
export const verifyAction = (
  action: Record<string, any>, purpose: string, wallet: string, trade: TradeContext,
): void => {
  const me = wallet.toLowerCase();
  if (!STAGE_PURPOSES[trade.stage]?.includes(purpose)) throw coded('unsafe_plan');
  if (!(ALLOWED_BY_PURPOSE[purpose] || []).includes(action?.type)) throw coded('unsafe_plan');
  if ('vaultAddress' in action || 'builder' in action) throw coded('unsafe_plan');
  if (action.type === 'sendAsset') {
    const dest = String(action.destination).toLowerCase();
    if (dest !== me || action.token !== HL_USDC_TOKEN || action.fromSubAccount !== '') throw coded('unsafe_plan');
    if (!trade.dex || !(finite(action.amount) > 0)) throw coded('unsafe_plan');
    if (purpose !== 'return_dex' && trade.budgetUsd != null && finite(action.amount) > trade.budgetUsd) {
      throw coded('unsafe_plan');
    }
    const [from, to] = purpose === 'return_dex' ? [trade.dex, ''] : ['', trade.dex];
    if (action.sourceDex !== from || action.destinationDex !== to) throw coded('unsafe_plan');
  }
  if (action.type === 'userSetAbstraction' && (String(action.user).toLowerCase() !== me
      || !['disabled', 'unifiedAccount'].includes(action.abstraction))) {
    throw coded('unsafe_plan');
  }
  if (action.type === 'order') {
    const orders = Array.isArray(action.orders) ? action.orders : [];
    if (!orders.length) throw coded('unsafe_plan');
    const opening = purpose === 'open_order';
    const isBuy = opening ? trade.side === 'long' : trade.side === 'short';
    if (orders.some((o: any) => o?.a !== trade.assetId || o.b !== isBuy || o.r !== !opening)) {
      throw coded('unsafe_plan');
    }
    const off = (px: number) => Math.abs(px - trade.markPx) / trade.markPx;
    if (opening) {
      const [o] = orders;
      // Judged at the mark, not the limit: a sell's limit is a floor, not a price.
      // A client order id is required: it is how a retry finds this order again.
      if (orders.length !== 1 || action.grouping !== 'na' || !o.t?.limit || o.t.limit.tif !== 'Ioc'
          || typeof o.c !== 'string' || !/^0x[0-9a-f]{32}$/.test(o.c)
          || finite(o.s) * trade.markPx > trade.maxNotionalUsd || off(finite(o.p)) > OPEN_PX_DEVIATION
          || (trade.minNotionalUsd != null && finite(o.s) * trade.markPx < trade.minNotionalUsd)) {
        throw coded('unsafe_plan');
      }
    } else if (trade.maxSize == null || orders.some((o: any) => finite(o.s) > trade.maxSize! * (1 + 1e-9))) {
      throw coded('unsafe_plan');
    }
    if (purpose === 'close_order' && (orders.length !== 1 || orders[0].t?.limit?.tif !== 'Ioc'
        || action.grouping !== 'na' || typeof orders[0].c !== 'string' || !/^0x[0-9a-f]{32}$/.test(orders[0].c)
        || off(finite(orders[0].p)) > (trade.deepCloseOk ? MAX_CLOSE_PX_DEVIATION : CLOSE_PX_DEVIATION))) {
      throw coded('unsafe_plan');
    }
    if (purpose === 'tpsl') {
      if (orders.some((o: any) => typeof o.c !== 'string' || !/^0x[0-9a-f]{32}$/.test(o.c))) throw coded('unsafe_plan');
      // Protection covers the whole position (venue rounding aside), never a sliver of it.
      if (orders.some((o: any) => finite(o.s) < trade.maxSize! * (1 - 1e-6))) throw coded('unsafe_plan');
      const want = trade.triggers ?? { tp: null, sl: null };
      const kinds = orders.map((o: any) => o.t?.trigger?.tpsl);
      // Exactly the protections the member asked for: none missing, none extra.
      const asked = (['tp', 'sl'] as const).filter((k) => want[k] != null);
      if (action.grouping !== 'positionTpsl' || new Set(kinds).size !== kinds.length
          || kinds.length !== asked.length || asked.some((k) => !kinds.includes(k))) {
        throw coded('unsafe_plan');
      }
      for (const o of orders) {
        const t = o.t?.trigger;
        const target = t?.tpsl === 'tp' ? want.tp : t?.tpsl === 'sl' ? want.sl : null;
        if (!t || t.isMarket !== true || target == null
            || Math.abs(finite(t.triggerPx) - target) / target > TRIGGER_TOLERANCE
            || Math.abs(finite(o.p) - finite(t.triggerPx)) / finite(t.triggerPx) > TRIGGER_LIMIT_DEVIATION) {
          throw coded('unsafe_plan');
        }
      }
    }
  }
  if (action.type === 'cancel') {
    // Only this market's orders (the old protection, replaced in the same plan).
    const cancels = Array.isArray(action.cancels) ? action.cancels : [];
    if (!cancels.length || cancels.some((c: any) => c?.a !== trade.assetId || !Number.isSafeInteger(c?.o) || c.o <= 0)) {
      throw coded('unsafe_plan');
    }
  }
  if (action.type === 'updateLeverage' && (action.asset !== trade.assetId || action.isCross !== false
      || action.leverage !== trade.leverage)) {
    throw coded('unsafe_plan');
  }
  if (action.type === 'updateIsolatedMargin' && (action.asset !== trade.assetId || action.isBuy !== true
      || !(finite(action.ntli) > 0)
      || (trade.budgetUsd != null && finite(action.ntli) > trade.budgetUsd * 1_000_000)
      || (trade.budgetUsd != null && finite(action.ntli) < trade.budgetUsd * MIN_TOPUP_SHARE * 1_000_000))) {
    throw coded('unsafe_plan'); // a top-up only ever adds margin, at most what the member added
  }
};

const verifyReturn = (mapping: Record<string, any>, send: Record<string, any>, wallet: string): void => {
  const me = wallet.toLowerCase();
  if (String(mapping.wallet).toLowerCase() !== me || String(mapping.depositor).toLowerCase() !== me
      || mapping.chainId !== 'hyperliquid') {
    throw coded('unsafe_plan');
  }
  if (send.type !== 'sendAsset' || String(send.destination).toLowerCase() !== RELAY_HL_DEPOSITORY
      || send.token !== HL_USDC_TOKEN || send.sourceDex !== '' || send.destinationDex !== ''
      || send.fromSubAccount !== ''
      || send.nonce !== mapping.nonce) {
    throw coded('unsafe_plan');
  }
};

// ── plumbing ────────────────────────────────────────────────────────────

const signer = async () => {
  const { getActiveEvmWallet } = await import('./secureDeterministicWallet');
  const wallet = await getActiveEvmWallet();
  if (!wallet) throw coded('trade_not_available');
  return wallet;
};

const delegate = async (): Promise<string> => {
  const { fetchSponsored7702Params } = await import('./sponsored7702');
  const sponsored = await fetchSponsored7702Params();
  if (!sponsored.enabled || !sponsored.delegateAddress) throw coded('trade_not_available');
  // Only Confío's audited delegate, compiled into the app (also enforced where
  // the authorization is signed).
  if (!isTrustedDelegate(sponsored.delegateAddress)) throw coded('unsafe_plan');
  return sponsored.delegateAddress;
};

/** Confío's dollar contracts as compiled into the app: the server's answer
 *  must agree with them, never replace them (an approval goes there). */
export const pinnedDollars = (served: { vaultAddress?: string | null; cusdAddress?: string | null }) => {
  const pinned = { vaultAddress: BUNDLED_VAULT_ADDRESS.toLowerCase(), cusdAddress: (BUNDLED_CUSD_ADDRESS || '').toLowerCase() };
  for (const key of ['vaultAddress', 'cusdAddress'] as const) {
    const value = (served[key] || '').toLowerCase();
    if (value && value !== pinned[key]) throw coded('unsafe_plan');
  }
  return pinned;
};

const dollarAddresses = async () => {
  const { data } = await (await client()).query({ query: DOLLAR_ADDRESSES, fetchPolicy: 'cache-first' });
  return pinnedDollars(data?.cusdPlusConvertParams || {});
};

/** A batch plan with the Relay order it pays into, proven by the app: the
 *  server's raw quote is authenticated here (the order id is the hash of its
 *  terms, signed by Relay's solver; the member is sender, recipient and
 *  refund address), and the deposit must be exactly that order's call. */
const withRelayOrder = async <T>(
  mutation: any, variables: Record<string, unknown>, field: string, maxAmount: bigint,
): Promise<{ result: T; quote: ReturnType<typeof bindDepositQuote> }> => {
  const result: any = await mutate<any>(mutation, variables, field);
  let raw: any;
  try {
    raw = JSON.parse(result?.relayQuoteJson ?? '');
  } catch {
    throw coded('unsafe_plan');
  }
  const amount = BigInt(String(raw?.details?.currencyIn?.amount ?? '0'));
  if (amount <= 0n || amount > maxAmount) throw coded('unsafe_plan');
  const wallet = await signer();
  const quote = bindDepositQuote(raw, wallet.address, amount);
  // The batch never outlives the order it pays into.
  result.deadline = Math.min(Number(result.deadline) || quote.deadline, quote.deadline);
  return { result: result as T, quote };
};

const mutate = async <T>(mutation: any, variables: Record<string, unknown>, field: string): Promise<T> => {
  const { data } = await (await client()).mutate({ mutation, variables, fetchPolicy: 'no-cache' });
  const result = data?.[field];
  if (!result?.success) throw coded(result?.error || 'unavailable');
  return result as T;
};

export const fetchPositions = async (includeDone = false): Promise<PerpPosition[] | null> => {
  const { data } = await (await client()).query({
    query: GET_PERPS_POSITIONS, variables: { includeDone }, fetchPolicy: 'network-only',
  });
  return data?.perpsPositions ?? null;
};

const fetchPosition = async (id: string): Promise<PerpPosition | null> =>
  (await fetchPositions(true))?.find((p) => p.id === id) ?? null;

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Poll until the position reaches one of `states` (the server reconciles
 *  inline on each read). Throws 'refunded' / 'timeout' / the step error. */
export const waitForPosition = async (
  id: string,
  done: (p: PerpPosition) => boolean,
  { timeoutMs = 180_000, failOn = [] as string[] } = {},
): Promise<PerpPosition> => {
  const started = Date.now();
  let delay = 1200;
  while (Date.now() - started < timeoutMs) {
    const p = await fetchPosition(id).catch(() => null);
    if (p) {
      if (done(p)) return p;
      if (failOn.includes(p.state)) throw coded(p.state === 'refunded' ? 'refunded' : 'hyperliquid_rejected');
    }
    await sleep(delay);
    delay = Math.min(delay * 1.4, 5000);
  }
  throw coded('timeout');
};

const sendBatch = async (
  plan: { callsJson: string; requestId: string; deadline?: number | null },
  bounds: CallBounds,
) => {
  const [wallet, delegateAddress, dollars] = await Promise.all([signer(), delegate(), dollarAddresses()]);
  const issued: IssuedCall[] = JSON.parse(plan.callsJson);
  let plusPriceWad: bigint | null = null;
  if (issued.some((c) => String(c.data).toLowerCase().slice(2, 10) === SEL.plusRedeem)) {
    // Read over public RPCs: the price that bounds a redemption is never the server's word.
    const hex = await publicBscCall('eth_call', [{ to: dollars.vaultAddress, data: selector('pPlus()') }, 'latest'])
      .catch(() => null);
    plusPriceWad = typeof hex === 'string' && /^0x[0-9a-fA-F]{1,64}$/.test(hex) ? BigInt(hex) : null;
  }
  const calls = verifyIssuedCalls(issued, wallet.address, dollars, { ...bounds, plusPriceWad });
  const { executeSponsoredBatch } = await import('./sponsored7702');
  return executeSponsoredBatch({
    wallet, calls, delegateAddress, requestId: plan.requestId, notAfter: plan.deadline ?? undefined,
  });
};

const sig = (s: HlSignature) => ({ r: s.r, s: s.s, v: s.v });

const capabilitiesSlippageBps = async (): Promise<number | null> => (await capabilitiesLimits()).slippageBps;

/** The member's tolerances: the server's settings, never looser than these. */
const capabilitiesLimits = async () => {
  const { data } = await (await client()).query({ query: GET_PERPS_CAPABILITIES, fetchPolicy: 'cache-first' })
    .catch(() => ({ data: null }));
  const c = data?.perpsCapabilities;
  return {
    slippageBps: Math.min(Number(c?.slippageBps ?? 50), 100),
    warnBps: Math.min(Number(c?.impactWarnBps ?? 100), 100),
    maxBps: Math.min(Number(c?.impactMaxBps ?? 300), 300),
  };
};

// ── one open, one nonce ─────────────────────────────────────────────────
// A retried open is signed with the FIRST open's nonce while that order may
// still reach Hyperliquid: of two signatures, at most one can ever execute.
// A fresh nonce only once Hyperliquid shows the first order dead (unfilled).

const OPEN_NONCE_SERVICE = 'confio_perps_open_nonce';
// Kept until Hyperliquid itself would refuse the nonce (2 days), so an
// unresolved signature is never forgotten while it could still execute; the
// server accepts a retried open's nonce for 46 h.
const OPEN_NONCE_KEEP_MS = 49 * 3600 * 1000;
const OPEN_NONCE_REUSE_MS = 45 * 3600 * 1000;

// Per WALLET, not per position: a signature left from one position shares
// its nonce with the next one's open, so at most one of them can execute.
// Closes too: a withheld close can never execute alongside a later open.
type OrderKind = 'open' | 'close';
type OpenNonces = Record<string, {
  nonce: number; cloids: { cloid: string; positionId: string; kind?: OrderKind }[];
}>;

const readOpenNonces = async (): Promise<OpenNonces> => {
  const Keychain = await import('react-native-keychain');
  const stored = await Keychain.getGenericPassword({ service: OPEN_NONCE_SERVICE });
  if (!stored) return {};
  try {
    return JSON.parse(stored.password) as OpenNonces;
  } catch {
    return {};
  }
};

// One allocation at a time: two overlapping opens can never each get a nonce.
let openNonceQueue: Promise<unknown> = Promise.resolve();

export const openNonce = (
  positionId: string, wallet: string, cloid: string | null, kind: OrderKind = 'open',
): Promise<number> => {
  const next = openNonceQueue.then(() => allocateOpenNonce(positionId, wallet, cloid, kind));
  openNonceQueue = next.catch(() => undefined);
  return next;
};

const allocateOpenNonce = async (
  positionId: string, wallet: string, cloid: string | null, kind: OrderKind,
): Promise<number> => {
  const Keychain = await import('react-native-keychain');
  const now = Date.now();
  const key = wallet.toLowerCase();
  const all = Object.fromEntries(Object.entries(await readOpenNonces())
    .filter(([, v]) => now - v.nonce < OPEN_NONCE_KEEP_MS && Array.isArray(v.cloids)
      && v.cloids.every((c) => typeof c?.cloid === 'string'))) as OpenNonces;
  let entry: OpenNonces[string] | undefined = all[key];
  if (entry) {
    // Every order signed with this nonce: this position's one filled = it is
    // open; any processed after the nonce existed = the nonce is spent and
    // none of them can execute any more.
    const seen = await Promise.all(entry.cloids.map((c) => venueOrderOutcome(wallet, c.cloid).catch(() => null)));
    if (seen.includes(null)) throw coded('hyperliquid_unavailable');
    const outcomes = seen as { outcome: string; placedMs: number | null }[];
    // This position's open already executed: never a second one. (A close
    // that executed, even partly, only spends the nonce: the live venue size
    // bounds the next close.)
    const mine = (i: number) =>
      entry!.cloids[i].positionId === positionId && (entry!.cloids[i].kind ?? 'open') === 'open';
    if (kind === 'open' && outcomes.some((o, i) => (o.outcome === 'filled' || o.outcome === 'open') && mine(i))) {
      throw coded('already_open');
    }
    // Only an order Hyperliquid placed after this nonce existed can have spent
    // it: an old one is no proof (its id could be replayed by a server).
    // (5 min of slack for this phone's clock; replayed old ids are refused below anyway.)
    const nonce = entry.nonce;
    if (outcomes.some((o) => o.outcome !== 'unknown' && o.placedMs != null && o.placedMs >= nonce - 300_000)) {
      entry = undefined;
    } else if (now - entry.nonce >= OPEN_NONCE_REUSE_MS) {
      // Unresolved and too old to re-sign: wait until Hyperliquid refuses it.
      throw coded('open_pending');
    }
  }
  if (!cloid) throw coded('unsafe_plan');
  const known = Boolean(entry?.cloids.some((c) => c.cloid === cloid));
  if (!known) {
    // A new order id must be new to Hyperliquid too: never an old order's.
    // Checked BEFORE anything is recorded: a refused plan changes no record.
    const fresh = await venueOrderOutcome(wallet, cloid).catch(() => null);
    if (!fresh) throw coded('hyperliquid_unavailable');
    if (fresh.outcome !== 'unknown') throw coded('unsafe_plan');
  }
  if (kind === 'open') {
    // A withheld protection (TP/SL) signature must never act on this new
    // position: the open takes its nonce, so at most one of them executes.
    const pending = await unresolvedTpslNonce(wallet);
    if (pending != null) {
      if (entry && entry.nonce !== pending) throw coded('open_pending');
      entry = entry ?? { nonce: pending, cloids: [] };
      // The open's (fresh) order joins the protection record too: once it is
      // processed, that shared nonce is spent for both.
      await shareWithTpsl(wallet, cloid);
    }
  }
  entry = entry ?? { nonce: nextNonce(), cloids: [] };
  if (!known) entry.cloids = [...entry.cloids, { cloid, positionId, kind }];
  all[key] = entry;
  // Kept BEFORE signing: unrecorded, a retry could not tie itself to this one.
  const ok = await Keychain.setGenericPassword('perps', JSON.stringify(all), { service: OPEN_NONCE_SERVICE });
  if (!ok) throw coded('unavailable');
  return entry.nonce;
};

// ── one leverage change, one nonce ──────────────────────────────────────
// A withheld leverage update must never apply after a later reviewed one:
// each new update reuses the last unconfirmed one's nonce (only one of them
// can ever execute), and the record is spent once Hyperliquid shows the
// reviewed setting.

const LEVERAGE_NONCE_SERVICE = 'confio_perps_leverage_nonce';

type LeverageNonces = Record<string, { nonce: number; spent: boolean; coin?: string; value?: number; from?: string }>;

const readLeverageNonces = async (): Promise<LeverageNonces> => {
  const Keychain = await import('react-native-keychain');
  const stored = await Keychain.getGenericPassword({ service: LEVERAGE_NONCE_SERVICE });
  if (!stored) return {};
  try {
    return JSON.parse(stored.password) as LeverageNonces;
  } catch {
    return {};
  }
};

const writeLeverageNonces = async (all: LeverageNonces) => {
  const Keychain = await import('react-native-keychain');
  const ok = await Keychain.setGenericPassword('perps', JSON.stringify(all), { service: LEVERAGE_NONCE_SERVICE });
  if (!ok) throw coded('unavailable');
};

export const leverageNonce = (wallet: string, coin: string, value: number): Promise<number> => {
  const next = openNonceQueue.then(async () => {
    const all = await readLeverageNonces();
    const key = wallet.toLowerCase();
    let kept: LeverageNonces[string] | undefined = all[key];
    const setting = (s: { type: string; value: number }) => `${s.type}:${s.value}`;
    if (kept && !kept.spent && kept.coin) {
      // The venue MOVED to the recorded setting (from another one): an update
      // holding this nonce executed, so the nonce is spent.
      const live = await venueLeverage(wallet, kept.coin).catch(() => null);
      if (!live) throw coded('hyperliquid_unavailable');
      if (setting(live) === `isolated:${kept.value}` && kept.from !== `isolated:${kept.value}`) kept = undefined;
    }
    // Never a no-op: an update to the setting already live proves nothing later.
    const now = await venueLeverage(wallet, coin).catch(() => null);
    if (!now) throw coded('hyperliquid_unavailable');
    if (setting(now) === `isolated:${value}`) throw coded('unsafe_plan');
    if (kept && !kept.spent && Date.now() - kept.nonce < OPEN_NONCE_REUSE_MS) {
      all[key] = { ...kept, coin, value, from: setting(now) }; // the same nonce, now for this update
      await writeLeverageNonces(all);
      return kept.nonce;
    }
    if (kept && !kept.spent && Date.now() - kept.nonce < OPEN_NONCE_KEEP_MS) throw coded('open_pending');
    all[key] = { nonce: nextNonce(), spent: false, coin, value, from: setting(now) };
    await writeLeverageNonces(all); // kept BEFORE signing
    return all[key].nonce;
  });
  openNonceQueue = next.catch(() => undefined);
  return next;
};

// ── protection: one nonce while a previous protection may still arrive ──

const TPSL_NONCE_SERVICE = 'confio_perps_tpsl_nonce';

type TpslNonces = Record<string, { nonce: number; cloids: string[] }>;

/** The nonce of a protection signature that may still reach Hyperliquid
 *  (none of its orders processed yet), or null. */
const unresolvedTpslNonce = async (wallet: string): Promise<number | null> => {
  const Keychain = await import('react-native-keychain');
  const stored = await Keychain.getGenericPassword({ service: TPSL_NONCE_SERVICE });
  let all: TpslNonces = {};
  try { all = stored ? JSON.parse(stored.password) as TpslNonces : {}; } catch { all = {}; }
  const entry = all[wallet.toLowerCase()];
  if (!entry || Date.now() - entry.nonce >= OPEN_NONCE_KEEP_MS) return null;
  const seen = await Promise.all(entry.cloids.map((c) => venueOrderOutcome(wallet, c).catch(() => null)));
  if (seen.includes(null)) throw coded('hyperliquid_unavailable');
  const spent = (seen as { outcome: string; placedMs: number | null }[])
    .some((o) => o.outcome !== 'unknown' && o.placedMs != null && o.placedMs >= entry.nonce - 300_000);
  if (spent) return null;
  if (Date.now() - entry.nonce >= OPEN_NONCE_REUSE_MS) throw coded('open_pending');
  return entry.nonce;
};

const shareWithTpsl = async (wallet: string, cloid: string) => {
  const Keychain = await import('react-native-keychain');
  const stored = await Keychain.getGenericPassword({ service: TPSL_NONCE_SERVICE });
  let all: TpslNonces = {};
  try { all = stored ? JSON.parse(stored.password) as TpslNonces : {}; } catch { all = {}; }
  const key = wallet.toLowerCase();
  if (!all[key] || all[key].cloids.includes(cloid)) return;
  all[key] = { ...all[key], cloids: [...all[key].cloids, cloid] };
  const ok = await Keychain.setGenericPassword('perps', JSON.stringify(all), { service: TPSL_NONCE_SERVICE });
  if (!ok) throw coded('unavailable');
};

export const tpslNonce = (wallet: string, cloids: string[]): Promise<number> => {
  const next = openNonceQueue.then(async () => {
    const Keychain = await import('react-native-keychain');
    const stored = await Keychain.getGenericPassword({ service: TPSL_NONCE_SERVICE });
    let all: TpslNonces = {};
    try { all = stored ? JSON.parse(stored.password) as TpslNonces : {}; } catch { all = {}; }
    const key = wallet.toLowerCase();
    let entry: TpslNonces[string] | undefined = all[key];
    if (entry && Date.now() - entry.nonce >= OPEN_NONCE_KEEP_MS) entry = undefined;
    if (entry) {
      // A withheld old protection shares this nonce with its replacement (at
      // most one executes); any of them processed since = the nonce is spent.
      const seen = await Promise.all(entry.cloids.map((c) => venueOrderOutcome(wallet, c).catch(() => null)));
      if (seen.includes(null)) throw coded('hyperliquid_unavailable');
      const nonce = entry.nonce;
      if ((seen as { outcome: string; placedMs: number | null }[])
        .some((o) => o.outcome !== 'unknown' && o.placedMs != null && o.placedMs >= nonce - 300_000)) {
        entry = undefined;
      } else if (Date.now() - entry.nonce >= OPEN_NONCE_REUSE_MS) {
        throw coded('open_pending');
      }
    }
    if (!cloids.length || cloids.some((c) => !/^0x[0-9a-f]{32}$/.test(c))) throw coded('unsafe_plan');
    entry = entry ?? { nonce: nextNonce(), cloids: [] };
    for (const c of cloids) {
      if (entry.cloids.includes(c)) continue;
      const fresh = await venueOrderOutcome(wallet, c).catch(() => null);
      if (!fresh) throw coded('hyperliquid_unavailable');
      if (fresh.outcome !== 'unknown') throw coded('unsafe_plan');
      entry.cloids = [...entry.cloids, c];
    }
    all[key] = entry;
    const ok = await Keychain.setGenericPassword('perps', JSON.stringify(all), { service: TPSL_NONCE_SERVICE });
    if (!ok) throw coded('unavailable');
    return entry.nonce;
  });
  openNonceQueue = next.catch(() => undefined);
  return next;
};

/** Before an open: the reviewed setting is live. A record of THIS change
 *  (same market and value, moved from another setting) is now spent; any
 *  other unresolved leverage signature could still apply, so no open yet. */
const spendLeverageNonce = (wallet: string, coin: string, value: number): Promise<void> => {
  const next = openNonceQueue.then(async () => {
    const all = await readLeverageNonces();
    const key = wallet.toLowerCase();
    const kept = all[key];
    if (!kept || kept.spent || Date.now() - kept.nonce >= OPEN_NONCE_KEEP_MS) return;
    if (kept.coin === coin && kept.value === value && kept.from !== `isolated:${value}`) {
      all[key] = { ...kept, spent: true };
      await writeLeverageNonces(all);
      return;
    }
    throw coded('open_pending');
  });
  openNonceQueue = next.catch(() => undefined);
  return next;
};

// ── retiring outstanding signatures before new money moves ─────────────
// Before funding a trade or a top-up, every nonce a signature may still be
// waiting under (an order, a protection, a leverage change) is spent with
// Hyperliquid's own 'noop', posted straight to Hyperliquid (never through
// Confío): a withheld signature can then never execute against new funds.

const HL_EXCHANGE = 'https://api.hyperliquid.xyz/exchange';
const SIGNED_NONCES_SERVICE = 'confio_perps_signed_nonces';

type SignedNonces = Record<string, number[]>;

const readSignedNonces = async (): Promise<SignedNonces> => {
  const Keychain = await import('react-native-keychain');
  const stored = await Keychain.getGenericPassword({ service: SIGNED_NONCES_SERVICE });
  try { return stored ? JSON.parse(stored.password) as SignedNonces : {}; } catch { return {}; }
};

/** Every nonce the member signs under is kept (BEFORE signing) until it is
 *  retired: transfers, returns, margin, setup steps, not only orders. */
export const rememberNonce = (wallet: string, nonce: number): Promise<void> => {
  const next = openNonceQueue.then(async () => {
    const Keychain = await import('react-native-keychain');
    const all = await readSignedNonces();
    const key = wallet.toLowerCase();
    const now = Date.now();
    all[key] = [...new Set([...(all[key] || []).filter((n) => now - n < OPEN_NONCE_KEEP_MS), nonce])];
    const ok = await Keychain.setGenericPassword('perps', JSON.stringify(all), { service: SIGNED_NONCES_SERVICE });
    if (!ok) throw coded('unavailable');
  });
  openNonceQueue = next.catch(() => undefined);
  return next;
};

const retireNonce = async (nonce: number, privKeyHex: string): Promise<boolean> => {
  const action = { type: 'noop' };
  const signature = signAction(action, nonce, privKeyHex);
  const res = await fetchBounded(HL_EXCHANGE, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, nonce, signature: sig(signature), vaultAddress: null }),
  }).catch(() => null);
  const body = res ? await res.json().catch(() => null) : null;
  if (body?.status === 'ok') return true;
  // Already used, or too old: nothing can ever execute under it. A nonce too
  // far in the FUTURE (or any other answer) is not retirement: kept.
  const text = JSON.stringify(body?.response ?? '').toLowerCase();
  return text.includes('nonce') && !text.includes('future')
    && ['used', 'duplicate', 'past', 'old', 'low', 'expired'].some((w) => text.includes(w));
};

export const retireOutstanding = (wallet: { address: string; privKeyHex: string }): Promise<void> => {
  const next = openNonceQueue.then(async () => {
    const Keychain = await import('react-native-keychain');
    const key = wallet.address.toLowerCase();
    const now = Date.now();
    const orders = await readOpenNonces();
    const levers = await readLeverageNonces();
    const stored = await Keychain.getGenericPassword({ service: TPSL_NONCE_SERVICE });
    let protections: TpslNonces = {};
    try { protections = stored ? JSON.parse(stored.password) as TpslNonces : {}; } catch { protections = {}; }
    const signed = await readSignedNonces();
    const nonces = new Set<number>((signed[key] || []).filter((n) => now - n < OPEN_NONCE_KEEP_MS));
    if (orders[key] && now - orders[key].nonce < OPEN_NONCE_KEEP_MS) nonces.add(orders[key].nonce);
    if (protections[key] && now - protections[key].nonce < OPEN_NONCE_KEEP_MS) nonces.add(protections[key].nonce);
    if (levers[key] && !levers[key].spent && now - levers[key].nonce < OPEN_NONCE_KEEP_MS) nonces.add(levers[key].nonce);
    for (const nonce of nonces) {
      if (!(await retireNonce(nonce, wallet.privKeyHex))) throw coded('hyperliquid_unavailable');
    }
    if (!nonces.size) return;
    delete orders[key];
    delete protections[key];
    delete levers[key];
    delete signed[key];
    const ok = await Keychain.setGenericPassword('perps', JSON.stringify(orders), { service: OPEN_NONCE_SERVICE })
      && await Keychain.setGenericPassword('perps', JSON.stringify(signed), { service: SIGNED_NONCES_SERVICE })
      && await Keychain.setGenericPassword('perps', JSON.stringify(protections), { service: TPSL_NONCE_SERVICE })
      && await Keychain.setGenericPassword('perps', JSON.stringify(levers), { service: LEVERAGE_NONCE_SERVICE });
    if (!ok) throw coded('unavailable');
  });
  openNonceQueue = next.catch(() => undefined);
  return next;
};

/** Asked before an open whose execution moves the price past the warning
 *  level: resolve true to go ahead. Without it, such an open is not signed. */
export type ImpactPrompt = (impact: { impactBps: number; avgPx: number | null }) => Promise<boolean>;

/** What the member reviewed on the order screen: the open signs only this. */
export interface ReviewedOpen {
  coin: string; side: Side; leverage: number; marginUsd: string; dollar?: 'cusd' | 'cusd_plus';
  /** The exposure the review showed (the quote's notional). */
  notionalUsd?: number | null;
}

/** What a member sees on a position: the trade a resumed open may sign. */
export const reviewedFromPosition = (p: PerpPosition): ReviewedOpen => ({
  coin: p.coin, side: p.side, leverage: p.leverage, marginUsd: p.marginUsd.toFixed(2),
});

/** Asked when Hyperliquid holds more than the position showed (beyond 5% + $1):
 *  resolve true to bring that amount home. Without it, it is not signed. */
export type AmountPrompt = (usd: number) => Promise<boolean>;

export interface PlanOptions {
  reviewed?: ReviewedOpen;
  onImpact?: ImpactPrompt;
  /** The market on the member's screen: a plan for any other is refused. */
  expectedCoin?: string;
  /** The return: what the position showed, and who confirms more than that. */
  shownUsd?: number | null;
  onAmount?: AmountPrompt;
  budgetUsd?: number | null;
  triggers?: { tp: number | null; sl: number | null };
}

/** The signing context, from Hyperliquid itself and from what the member
 *  chose: never from the server alone. */
const tradeContext = async (stage: PlanStage, position: PerpPosition, wallet: string, opts: PlanOptions) => {
  const { reviewed } = opts;
  if (opts.expectedCoin && opts.expectedCoin !== position.coin) throw coded('unsafe_plan');
  if (reviewed && (reviewed.coin !== position.coin || reviewed.side !== position.side
      || reviewed.leverage !== position.leverage)) {
    throw coded('unsafe_plan');
  }
  let market;
  let live;
  try {
    [market, live] = await Promise.all([
      venueMarket(position.coin), stage === 'open' ? Promise.resolve(null) : venuePosition(wallet, position.coin),
    ]);
  } catch {
    throw coded('hyperliquid_unavailable');
  }
  if (!market.usdcCollateral) throw coded('unsafe_plan');
  let { side, leverage } = reviewed ?? position;
  if (live) {
    side = live.szi > 0 ? 'long' : 'short';
    leverage = live.leverage;
  } else if (stage === 'close' || stage === 'tpsl' || stage === 'margin') {
    throw coded('position_already_closed');
  }
  const margin = reviewed ? Number(reviewed.marginUsd) : position.marginUsd;
  // The open must deliver the exposure reviewed, less crossing costs and a
  // first account's activation (at most ~20% of a minimum first margin).
  // Bound to the exposure the review showed when known (less the open fee,
  // slippage and size rounding: ≤ 7% at high leverage), else to 80% of margin × leverage.
  // One lot of rounding either way (the size is rounded down to the venue's lot).
  const lot = 10 ** -market.szDecimals * market.markPx;
  const quoted = stage === 'open' && reviewed?.notionalUsd && reviewed.notionalUsd > 0 ? reviewed.notionalUsd : null;
  const minNotionalUsd = stage !== 'open' || !reviewed ? null
    : quoted ? quoted * 0.93 - lot
      : Number(reviewed.marginUsd) * reviewed.leverage * 0.8;
  const slip = 1 + 2 * Math.min((await capabilitiesSlippageBps()) ?? 50, 300) / 10_000;
  return {
    stage, assetId: market.assetId, dex: market.dex, side, leverage, markPx: market.markPx,
    // Never more exposure than the review showed (plus a lot and a mark move).
    maxNotionalUsd: quoted ? Math.min(quoted * 1.02 + lot, margin * leverage * slip) : margin * leverage * slip,
    maxSize: live ? Math.abs(live.szi) : null,
    // An open moves at most its reviewed margin into a builder dex.
    budgetUsd: opts.budgetUsd ?? (reviewed ? Number(reviewed.marginUsd) : null), triggers: opts.triggers,
    minNotionalUsd,
  } as TradeContext;
};

/** Ask for a stage's Hyperliquid steps, sign each and submit it, re-asking
 *  while the server says the plan changes (first-time account setup). */
const runPlan = async (
  positionId: string,
  stage: PlanStage,
  extra: Record<string, unknown> = {},
  opts: PlanOptions = {},
): Promise<any> => {
  const { onImpact } = opts;
  const [wallet, position] = await Promise.all([signer(), fetchPosition(positionId)]);
  if (!position) throw coded('unavailable');
  const trade = await tradeContext(stage, position, wallet.address, opts);
  // Each step is signed at most once per run: a plan can never repeat an
  // order or a transfer to go past what the member reviewed.
  const signed = new Set<string>();
  for (let round = 0; round < 4; round++) {
    const plan: any = await mutate(PLAN, { positionId, stage, ...extra }, 'perpsPlan');
    const purposes = (plan.steps || []).map((st: any) => st.purpose);
    // Protection is replaced, never just removed: a cancel only with its new triggers.
    if (purposes.includes('tpsl_cancel') && !purposes.includes('tpsl')) throw coded('unsafe_plan');
    // The whole plan is verified before anything in it is signed: a bad last
    // step must never leave an earlier one (a cancel, a transfer) signed.
    const closeIndex = purposes.indexOf('close_order');
    if (closeIndex >= 0) {
      // A thin book: the close may only fill deeper than usual. The member
      // decides (staying exposed is worse); past the hard limit it is never signed.
      const p = finite(JSON.parse(plan.steps[closeIndex].actionJson)?.orders?.[0]?.p);
      const off = Math.abs(p - trade.markPx) / trade.markPx;
      const caps = await capabilitiesLimits();
      // Past the warning level (as for opens), the member sees it before closing.
      const warn = plan.impactWarn || off * 10_000 > caps.warnBps + caps.slippageBps;
      if (off <= MAX_CLOSE_PX_DEVIATION && (warn || off > CLOSE_PX_DEVIATION)) {
        const go = onImpact ? await onImpact({ impactBps: Math.round(off * 10_000), avgPx: p }) : false;
        if (!go) throw coded('close_declined');
        trade.deepCloseOk = true;
      }
    }
    const actions = (plan.steps || []).map((step: any) => {
      const action = JSON.parse(step.actionJson);
      if (signed.has(step.purpose)) throw coded('unsafe_plan');
      signed.add(step.purpose);
      verifyAction(action, step.purpose, wallet.address, trade);
      return action;
    });
    const openIndex = purposes.indexOf('open_order');
    if (openIndex >= 0) {
      // Impact from Hyperliquid's own book, not the server's word: past the
      // warning the member confirms, past the maximum it is not signed, and
      // the limit sits within the member's slippage of that fill.
      const order = actions[openIndex].orders[0];
      const caps = await capabilitiesLimits();
      const fill = await venueFill(position.coin, order.b, finite(order.s)).catch(() => null);
      if (!fill) throw coded('hyperliquid_unavailable');
      const impactBps = (Math.abs(fill.avgPx - fill.mid) / fill.mid) * 10_000;
      if (impactBps > caps.maxBps) throw coded('impact_too_high');
      // (+50 bps: the book moves between the server's plan and this read.)
      const bound = fill.avgPx * (1 + (order.b ? 1 : -1) * (caps.slippageBps + 50) / 10_000);
      if (order.b ? finite(order.p) > bound : finite(order.p) < bound) throw coded('unsafe_plan');
      if (impactBps > caps.warnBps || plan.impactWarn) {
        const go = onImpact ? await onImpact({ impactBps: Math.round(impactBps), avgPx: fill.avgPx }) : false;
        if (!go) throw coded('impact_declined');
      }
    }
    for (const [i, step] of (plan.steps || []).entries()) {
      const action = actions[i];
      if (step.purpose === 'tpsl_cancel') {
        // The old protection is cancelled only once Hyperliquid itself shows
        // the new triggers live, full size, at the prices entered.
        const live = await venueTriggers(wallet.address, position.coin).catch(() => null);
        if (!live) throw coded('hyperliquid_unavailable');
        const cancelling = new Set(action.cancels.map((c: any) => c.o));
        const want = trade.triggers ?? { tp: null, sl: null };
        for (const kind of ['tp', 'sl'] as const) {
          const target = want[kind];
          if (target == null) continue;
          const placed = live.some((o) => o.kind === kind && !cancelling.has(o.oid)
            && Math.abs(o.triggerPx - target) / target <= TRIGGER_TOLERANCE
            && Math.abs(o.limitPx - o.triggerPx) / o.triggerPx <= TRIGGER_LIMIT_DEVIATION
            && o.size >= (trade.maxSize ?? 0) * (1 - 1e-6));
          if (!placed) throw coded('tpsl_rejected');
        }
      }
      if (step.purpose === 'open_order') {
        // The venue itself must show isolated margin at the reviewed leverage,
        // and no exposure yet: an order whose answer was lost may have filled.
        const [setting, existing] = await Promise.all([
          venueLeverage(wallet.address, position.coin), venuePosition(wallet.address, position.coin),
        ]).catch(() => [null, undefined] as const);
        if (!setting || existing === undefined) throw coded('hyperliquid_unavailable');
        if (existing) throw coded('already_open');
        if (setting.type !== 'isolated' || setting.value !== trade.leverage) throw coded('unsafe_plan');
        // The reviewed setting is live: whatever update held the shared nonce, no other can apply now.
        await spendLeverageNonce(wallet.address, position.coin, trade.leverage);
      }
      // Orders (open and close) share one nonce record per wallet; other actions are fresh.
      const nonce = step.purpose === 'open_order' || step.purpose === 'close_order'
        ? await openNonce(positionId, wallet.address, action.orders?.[0]?.c,
          step.purpose === 'open_order' ? 'open' : 'close')
        : step.purpose === 'leverage' ? await leverageNonce(wallet.address, position.coin, action.leverage)
          : step.purpose === 'tpsl' ? await tpslNonce(wallet.address, action.orders.map((o: any) => o.c))
          : nextNonce();
      if ('nonce' in action) action.nonce = nonce; // same key position: the hash keeps its order
      await rememberNonce(wallet.address, nonce);
      const signature = signAction(action, nonce, wallet.privKeyHex);
      await mutate(SUBMIT_ACTION, {
        positionId, purpose: step.purpose, actionJson: JSON.stringify(action), nonce: String(nonce),
        signature: sig(signature),
      }, 'perpsSubmitAction');
    }
    if (plan.mappingTypedJson || plan.sendActionJson) {
      // A withdrawal is signed only when the member asked to bring money home.
      if (stage !== 'return' || !plan.mappingTypedJson || !plan.sendActionJson) throw coded('unsafe_plan');
      const typed = JSON.parse(plan.mappingTypedJson);
      const send = JSON.parse(plan.sendActionJson);
      verifyReturn(typed.message, send, wallet.address);
      // The withdrawal's order, proven from Relay's signed quote: the mapping
      // and the transfer must be exactly for that order, paying the member.
      let raw: any;
      try {
        raw = JSON.parse(plan.relayQuoteJson ?? '');
      } catch {
        throw coded('unsafe_plan');
      }
      const units = BigInt(String(raw?.details?.currencyIn?.amount ?? '0'));
      const order = bindReturnQuote(raw, wallet.address, units);
      if (String(typed.message.id).toLowerCase() !== order.orderId
          || typed.message.nonce !== order.nonce || send.nonce !== order.nonce
          || send.amount !== order.amount || String(send.destination).toLowerCase() !== order.destination) {
        throw coded('unsafe_plan');
      }
      const amount = finite(send.amount);
      const shown = opts.shownUsd ?? 0;
      if (amount > shown * 1.05 + 1) {
        const go = opts.onAmount ? await opts.onAmount(amount) : false;
        if (!go) throw coded('return_amount_changed');
      }
      // Checked again right before signing: the member may have taken a while to confirm.
      if (order.deadline * 1000 <= Date.now() + 60_000) throw coded('return_quote_expired');
      await rememberNonce(wallet.address, Number(send.nonce));
      const mappingSig = signRelayNonceMapping(typed.message, Number(typed.domain.chainId), wallet.privKeyHex);
      const sendSig = signAction(send, send.nonce, wallet.privKeyHex);
      await mutate(SUBMIT_RETURN, { positionId, mappingSignature: sig(mappingSig), sendSignature: sig(sendSig) },
        'perpsSubmitReturn');
      return plan;
    }
    if (!plan.replan && !(stage === 'return' && (plan.steps || []).length)) return plan;
  }
  return null;
};

// ── flows ───────────────────────────────────────────────────────────────

export type PerpsStep = 'exit' | 'bridge' | 'open' | 'close' | 'return' | 'enter' | 'done';

export const acknowledgePerpsRisk = async (version: number) =>
  mutate(ACKNOWLEDGE, { version }, 'acknowledgePerpsRisk');

export interface OpenParams {
  coin: string;
  side: Side;
  leverage: number;
  marginUsd: string;
  onStep?: (step: PerpsStep) => void;
}

/** Quote only (creates the position as "quoted"): costs for the review. */
export const quoteOpen = async ({ coin, side, leverage, marginUsd }: OpenParams) => {
  const { result, quote } = await withRelayOrder<any>(
    PREPARE_OPEN, { coin, side, leverage, marginUsd }, 'perpsPrepareOpen', usdToWei(marginUsd));
  // The review shows what the app's OWN order delivers, never more: credited
  // margin and exposure come from Relay's signed order, not the server's word.
  const credited = Number(quote.expectedOut) / 1e8;
  const costs = result?.costs;
  if (!costs || Math.abs(Number(costs.creditedUsd) - credited) > 0.000001
      || Math.abs(Number(costs.notionalUsd) - credited * leverage) > 0.01) {
    throw coded('unsafe_plan');
  }
  return { ...result, memberRelay: quote };
};

export const cancelQuote = async (positionId: string) =>
  (await client()).mutate({ mutation: CANCEL_QUOTE, variables: { positionId } }).catch(() => null);

/** Sign the quoted open, then follow it until the position is open. */
export interface FlowResult { position: PerpPosition; txHash: string | null }

export const confirmOpen = async (
  quote: any, onStep: ((s: PerpsStep) => void) | undefined, reviewed: ReviewedOpen, onImpact?: ImpactPrompt,
): Promise<FlowResult> => {
  onStep?.('exit');
  await retireOutstanding(await signer());
  const receipt = await sendBatch(quote, {
    direction: 'out', maxWei: usdToWei(reviewed.marginUsd), dollar: reviewed.dollar ?? null,
    relayDeposit: quote.memberRelay,
  });
  onStep?.('bridge');
  await waitForPosition(quote.positionId, (p) => ['funded', 'open'].includes(p.state),
    { failOn: ['refunded', 'failed'] });
  onStep?.('open');
  await openOnVenue(quote.positionId, { reviewed, onImpact });
  onStep?.('done');
  const position = await waitForPosition(quote.positionId, (p) => p.state === 'open', { timeoutMs: 30_000 });
  return { position, txHash: receipt?.txHash ?? null };
};

export const openOnVenue = async (positionId: string, opts: PlanOptions = {}) =>
  runPlan(positionId, 'open', {}, opts);

export const closePosition = async (
  positionId: string, onStep?: (s: PerpsStep) => void, onAmount?: AmountPrompt, shownUsd?: number | null,
  expectedCoin?: string, onImpact?: ImpactPrompt,
) => {
  onStep?.('close');
  await runPlan(positionId, 'close', {}, { expectedCoin, onImpact });
  await waitForPosition(positionId, (p) => ['closed', 'liquidated', 'done'].includes(p.state), { timeoutMs: 60_000 });
  return bringHome(positionId, onStep, onAmount, shownUsd, expectedCoin);
};

/** Hyperliquid → BSC USDT → Confío dollars. Safe to call again at any step. */
/** `shownUsd`: what the member's screen showed when they tapped (the return
 *  is bounded by it; anything more needs their confirmation). */
export const bringHome = async (
  positionId: string, onStep?: (s: PerpsStep) => void, onAmount?: AmountPrompt, shownUsd?: number | null,
  expectedCoin?: string,
): Promise<FlowResult> => {
  let txHash: string | null = null;
  let p = await fetchPosition(positionId);
  if (p && ['closed', 'liquidated', 'funded', 'return_failed'].includes(p.state)) {
    onStep?.('return');
    await runPlan(positionId, 'return', {}, { shownUsd: shownUsd ?? 0, onAmount, expectedCoin });
    p = await waitForPosition(positionId, (x) => ['landed', 'done'].includes(x.state),
      { failOn: ['return_failed'] });
  } else if (p?.state === 'returning') {
    onStep?.('return');
    p = await waitForPosition(positionId, (x) => ['landed', 'done'].includes(x.state),
      { failOn: ['return_failed'] });
  }
  if (p?.state === 'landed' && p.nextAction === 'enter') {
    onStep?.('enter');
    const entry = await mutate<any>(PREPARE_ENTRY, { positionId }, 'perpsPrepareEntry');
    // No more than what landed from Hyperliquid (never other USDT in the wallet).
    if (p.valueUsd == null) throw coded('unavailable');
    const landedWei = usdToWei(p.valueUsd);
    txHash = (await sendBatch(entry, { direction: 'in', maxWei: landedWei + landedWei / 200n }))?.txHash ?? null;
  }
  const final = await waitForPosition(positionId, (x) => x.state === 'done', { timeoutMs: 120_000 });
  onStep?.('done');
  return { position: final, txHash };
};

export const retryBridge = async (positionId: string, onStep?: (s: PerpsStep) => void, onImpact?: ImpactPrompt) => {
  const position = await fetchPosition(positionId);
  if (!position) throw coded('unavailable');
  const { result: plan, quote } = await withRelayOrder<any>(
    PREPARE_RETRY, { positionId }, 'perpsPrepareBridgeRetry', usdToWei(position.marginUsd));
  onStep?.('bridge');
  await retireOutstanding(await signer());
  // The refund is at most what left: never more than this position's margin.
  await sendBatch(plan, {
    direction: 'out', maxWei: usdToWei(position.marginUsd), refundRetry: true, relayDeposit: quote,
  });
  await waitForPosition(positionId, (p) => ['funded', 'open'].includes(p.state), { failOn: ['refunded'] });
  onStep?.('open');
  await openOnVenue(positionId, { onImpact, reviewed: reviewedFromPosition(position) });
  onStep?.('done');
};

/** Keep refunded USDT: it goes back to your dollars (ordinary entry). */
export const releaseRefund = async (positionId: string) =>
  mutate(RELEASE_REFUND, { positionId }, 'perpsReleaseRefund');

export const addMargin = async (
  positionId: string, amountUsd: string, onStep?: (s: PerpsStep) => void, dollar?: 'cusd' | 'cusd_plus',
  expectedCoin?: string,
) => {
  const { result: plan, quote } = await withRelayOrder<any>(
    PREPARE_MARGIN_ADD, { positionId, amountUsd }, 'perpsPrepareMarginAdd', usdToWei(amountUsd));
  onStep?.('exit');
  await retireOutstanding(await signer());
  await sendBatch(plan, {
    direction: 'out', maxWei: usdToWei(amountUsd), dollar: dollar ?? null, relayDeposit: quote,
  });
  onStep?.('bridge');
  await waitForPosition(positionId, (p) => p.nextAction === 'finish_margin');
  onStep?.('open');
  await runPlan(positionId, 'margin', {}, { budgetUsd: Number(amountUsd), expectedCoin });
  onStep?.('done');
};

export const setTpSl = async (
  positionId: string, takeProfitPx: string | null, stopLossPx: string | null, expectedCoin?: string,
) =>
  runPlan(positionId, 'tpsl', { takeProfitPx, stopLossPx }, {
    expectedCoin,
    triggers: { tp: takeProfitPx ? Number(takeProfitPx) : null, sl: stopLossPx ? Number(stopLossPx) : null },
  });

/** Continue whatever step a position stopped at. */
export const resumePosition = async (
  p: PerpPosition, onStep?: (s: PerpsStep) => void, onImpact?: ImpactPrompt, onAmount?: AmountPrompt,
): Promise<unknown> => {
  switch (p.nextAction) {
    case 'wait_bridge':
      onStep?.('bridge');
      await waitForPosition(p.id, (x) => x.nextAction !== 'wait_bridge', { failOn: ['refunded'] });
      return resumePosition((await fetchPosition(p.id))!, onStep, onImpact, onAmount);
    case 'retry_bridge':
      return retryBridge(p.id, onStep, onImpact);
    case 'open_order':
      onStep?.('open');
      // The trade on the member's screen is the one that may be signed.
      await openOnVenue(p.id, { onImpact, reviewed: reviewedFromPosition(p) });
      onStep?.('done');
      return;
    case 'finish_margin':
      onStep?.('open');
      if (p.pendingMarginUsd == null) throw coded('unavailable');
      await runPlan(p.id, 'margin', {}, { budgetUsd: p.pendingMarginUsd, expectedCoin: p.coin });
      onStep?.('done');
      return;
    case 'return':
    case 'enter':
    case 'wait_return':
      await bringHome(p.id, onStep, onAmount, positionValueUsd(p), p.coin);
      return;
    default:
  }
};

// ── shared math for the screens ─────────────────────────────────────────

/** Hyperliquid's isolated liquidation price, estimated before the fill
 *  (mirrors cusd_plus/perps_flow.estimate_liquidation_px). */
export const estimateLiquidationPx = (
  entryPx: number, notionalUsd: number, marginUsd: number, side: Side, maxLeverage: number,
): number | null => {
  if (!(entryPx > 0) || !(notionalUsd > 0) || !(maxLeverage > 0)) return null;
  const size = notionalUsd / entryPx;
  const s = side === 'long' ? 1 : -1;
  const mmr = 1 / (2 * maxLeverage);
  const available = marginUsd - size * entryPx * mmr;
  const liq = entryPx - (s * available) / size / (1 - mmr * s);
  return liq > 0 ? liq : 0;
};

/** What reaches Hyperliquid from `marginUsd` of Confío dollars, before Relay. */
export const afterExitFee = (marginUsd: number, feeBps: number | null) =>
  marginUsd * (1 - (feeBps ?? 90) / 10_000);
