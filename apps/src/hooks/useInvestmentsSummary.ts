// Home's one "Inversiones" row: U.S. stocks + Bitcoin + gold + Futuros.
// Futuros counts only what the member holds (never an invitation on Home),
// at the money that is the member's: the margin and its result, never the
// leveraged exposure.
//
// `summarizeInvestments` is pure (the gating matrix is tested on it);
// the hook only wires the reads. Home adds exactly one term from here,
// `totalUsd`, to its total.

import { useMemo } from 'react';

import { CRYPTO_TRADING_UI_ENABLED } from '../config/features';
import type { CryptoAsset, CryptoHolding } from '../services/cryptoTrading';
import type { PerpPosition } from '../services/perps';
import { positionValueUsd } from '../utils/perpsPresentation';
import { usePerpsPositions } from './usePerps';
import { useCryptoCapabilities, useCryptoHoldings, useCryptoMarket } from './useCrypto';
import { useSavingsPortfolio } from './useSavingsPortfolio';

export interface InvestmentsSummaryInput {
  stocksEnabled: boolean;
  stockPositionCount: number;
  stocksTotalUsd: number;
  /** cryptoCapabilities.enabled (discovery: switch + country policy). */
  cryptoEnabled: boolean;
  /** null = unknown (not loaded yet, scan failed). */
  cryptoHoldings: CryptoHolding[] | null;
  /** What the market lists (for the empty-state invitation). */
  cryptoAssets: Pick<CryptoAsset, 'name' | 'category'>[];
  /** Futuros positions not yet finished (null = not answered yet). */
  perpsPositions?: PerpPosition[] | null;
  /** Asked and not answered: the server said a held position is unreadable
   *  (Hyperliquid down), or the query failed. Never "no Futuros". */
  perpsUnreadable?: boolean;
}

/** Steps whose money already sits in the member's BSC USDT (counted with
 *  the dollars): never counted twice here. */
const PERPS_ON_BSC = new Set(['landed', 'refunded', 'done', 'cancelled', 'failed', 'quoted']);

export interface InvestmentsSummary {
  /** Show the row: any surface is enabled or anything is held. */
  visible: boolean;
  /** Something is held (a position at $0.00 is still held). */
  holds: boolean;
  /** Known value; unknown parts contribute nothing (understating is safe). */
  totalUsd: number;
  /** False when some crypto value is unknown: the row shows "—". */
  totalKnown: boolean;
  /** e.g. "3 acciones · oro · bitcoin", or the empty-state invitation. */
  subtitle: string;
}

/** 'oro' for any metal, the lower-case name for a coin. */
const label = (a: { name: string; category: string }) =>
  (a.category === 'metal' ? 'oro' : a.name.toLowerCase());

const unique = (items: string[]) => Array.from(new Set(items));

const joinY = (items: string[]) =>
  (items.length <= 1 ? items.join('') : `${items.slice(0, -1).join(', ')} y ${items[items.length - 1]}`);

export const summarizeInvestments = (input: InvestmentsSummaryInput): InvestmentsSummary => {
  const held = (input.cryptoHoldings ?? []).filter((h) => {
    try {
      return BigInt(h.units || '0') > 0n;
    } catch {
      return false;
    }
  });
  // Issuer eligibility is authoritative for stocks (positions are [] when
  // blocked). Crypto holdings always count: selling is never country-gated.
  const stockCount = input.stocksEnabled ? input.stockPositionCount : 0;
  const stocksUsd = input.stocksEnabled ? input.stocksTotalUsd : 0;
  const holdsStocks = stockCount > 0 || stocksUsd > 0;
  const holdsCrypto = held.length > 0;
  const perps = (input.perpsPositions ?? []).filter((p) => !PERPS_ON_BSC.has(p.state));
  // The server answers null only for someone with live positions.
  const holdsPerps = perps.length > 0 || (Boolean(input.perpsUnreadable) && input.perpsPositions === null);
  const holds = holdsStocks || holdsCrypto || holdsPerps;
  const cryptoUnknown = input.cryptoHoldings === null || held.some((h) => h.valueUsd == null);
  const cryptoUsd = held.reduce((sum, h) => sum + (h.valueUsd ?? 0), 0);
  // A return on its way may already be USDT in the dollars: unknown, never
  // counted twice; an open position whose value is not known yet likewise.
  // Money on the bridge either way (an open 'bridging' — before broadcast
  // it is still in the dollars —, a return 'returning', or a refund that may
  // already sit in the wallet's USDT) is unknown and counts nothing: the
  // row shows "—", and Home's headline understates for those minutes rather
  // than count the same dollars twice. Only the server's own valueUsd is a
  // value; the margin asked for is not.
  const inTransit = (p: PerpPosition) => p.state === 'bridging' || p.state === 'returning' || p.valueUsd == null;
  const perpsUnknown = Boolean(input.perpsUnreadable) || perps.some(inTransit);
  const perpsUsd = perps.reduce((sum, p) => sum + (inTransit(p) ? 0 : positionValueUsd(p)), 0);

  let subtitle: string;
  if (holds) {
    subtitle = [
      stockCount > 0 ? `${stockCount} ${stockCount === 1 ? 'acción' : 'acciones'}` : null,
      ...unique(held.map(label)),
      holdsPerps ? 'futuros' : null,
    ].filter(Boolean).join(' · ') || 'Tus inversiones';
  } else {
    const offered = [
      input.stocksEnabled ? 'acciones' : null,
      ...(input.cryptoEnabled ? unique(input.cryptoAssets.map(label)) : []),
    ].filter((v): v is string => Boolean(v));
    const phrase = joinY(offered);
    subtitle = phrase
      ? `${phrase.charAt(0).toUpperCase()}${phrase.slice(1)} desde US$1`
      : 'Tus inversiones';
  }

  return {
    visible: input.stocksEnabled || input.cryptoEnabled || holds,
    holds,
    totalUsd: stocksUsd + cryptoUsd + perpsUsd,
    // Before crypto answers, the row is unknown only for someone who could
    // hold crypto; nobody else waits on a "—". Futuros likewise: unknown
    // only while a held position's value is not known.
    totalKnown: !(cryptoUnknown && (input.cryptoEnabled || holdsCrypto)) && !perpsUnknown,
    subtitle,
  };
};

export const useInvestmentsSummary = (): InvestmentsSummary => {
  const { stocks } = useSavingsPortfolio();
  const { capabilities } = useCryptoCapabilities();
  const cryptoEnabled = CRYPTO_TRADING_UI_ENABLED && Boolean(capabilities?.enabled);
  const { holdings } = useCryptoHoldings(false, 120_000);
  const { assets } = useCryptoMarket(cryptoEnabled);
  // Always read: a held position counts even where opening is not offered.
  const { positions: perpsPositions, unknown: perpsUnreadable } = usePerpsPositions(true, { pollMs: 60_000 });
  return useMemo(
    () => summarizeInvestments({
      stocksEnabled: stocks.enabled,
      stockPositionCount: stocks.positions.length,
      stocksTotalUsd: stocks.totalUsd,
      cryptoEnabled,
      cryptoHoldings: holdings,
      cryptoAssets: assets,
      perpsPositions,
      perpsUnreadable,
    }),
    [stocks.enabled, stocks.positions.length, stocks.totalUsd, cryptoEnabled, holdings, assets, perpsPositions,
      perpsUnreadable],
  );
};
