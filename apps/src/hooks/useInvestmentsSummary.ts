// Home's one "Inversiones" row: U.S. stocks + Bitcoin + gold.
//
// `summarizeInvestments` is pure (the gating matrix is tested on it);
// the hook only wires the reads. Home adds exactly one term from here,
// `totalUsd`, to its total.

import { useMemo } from 'react';

import { CRYPTO_TRADING_UI_ENABLED } from '../config/features';
import type { CryptoAsset, CryptoHolding } from '../services/cryptoTrading';
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
}

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
  const holds = holdsStocks || holdsCrypto;
  const cryptoUnknown = input.cryptoHoldings === null || held.some((h) => h.valueUsd == null);
  const cryptoUsd = held.reduce((sum, h) => sum + (h.valueUsd ?? 0), 0);

  let subtitle: string;
  if (holds) {
    subtitle = [
      stockCount > 0 ? `${stockCount} ${stockCount === 1 ? 'acción' : 'acciones'}` : null,
      ...unique(held.map(label)),
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
    totalUsd: stocksUsd + cryptoUsd,
    // Before crypto answers, the row is unknown only for someone who could
    // hold crypto; nobody else waits on a "—".
    totalKnown: !(cryptoUnknown && (input.cryptoEnabled || holdsCrypto)),
    subtitle,
  };
};

export const useInvestmentsSummary = (): InvestmentsSummary => {
  const { stocks } = useSavingsPortfolio();
  const { capabilities } = useCryptoCapabilities();
  const cryptoEnabled = CRYPTO_TRADING_UI_ENABLED && Boolean(capabilities?.enabled);
  const { holdings } = useCryptoHoldings(false, 120_000);
  const { assets } = useCryptoMarket(cryptoEnabled);
  return useMemo(
    () => summarizeInvestments({
      stocksEnabled: stocks.enabled,
      stockPositionCount: stocks.positions.length,
      stocksTotalUsd: stocks.totalUsd,
      cryptoEnabled,
      cryptoHoldings: holdings,
      cryptoAssets: assets,
    }),
    [stocks.enabled, stocks.positions.length, stocks.totalUsd, cryptoEnabled, holdings, assets],
  );
};
