// Copy and number formatting shared by the Bitcoin & gold screens.

import { formatDecimal, formatPercent } from './numberLocale';
import { fromBaseUnits } from '../services/cryptoSwapMath';

export const fundingDollarName = (funding?: string | null): string =>
  (funding === 'cusd_plus' ? 'Confío Dollar+' : 'Confío Dollar');

/** Who stands behind the asset, by the catalog's `custody`. */
export const custodyNote = (custody?: string | null): string | null => {
  switch (custody) {
    case 'binance_peg':
      return 'Bitcoin respaldado 1:1 por Binance en BNB Chain';
    case 'tether_gold':
      return 'Oro físico custodiado por Tether (1 XAUt = 1 onza troy)';
    case 'wrapped_native':
      return 'BNB envuelto (WBNB), 1:1 con BNB en BNB Chain';
    default:
      return null;
  }
};

/** Token amount for people: up to 8 decimals below 1 unit, 4 above. */
export const formatUnits = (units: bigint | string, decimals: number): string => {
  const value = fromBaseUnits(units, decimals);
  const digits = value > 0 && value < 1 ? Math.min(decimals, 8) : Math.min(decimals, 4);
  return formatDecimal(value, { decimals: digits, minDecimals: 2 });
};

export const formatUsdPrice = (value: number | null | undefined): string =>
  (value == null || !Number.isFinite(value)
    ? '—'
    : `$${formatDecimal(value, { decimals: value < 1 ? 4 : 2 })}`);

/** "0,9" from 90 bps. */
export const feePctLabel = (feeBps: number): string => formatPercent(feeBps / 100, 2);

