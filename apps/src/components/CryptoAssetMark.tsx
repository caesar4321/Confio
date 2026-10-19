import React from 'react';

import BitcoinMark from './svg/BitcoinMark';
import GoldMark from './svg/GoldMark';
import { TickerLogo } from './TickerLogo';

/**
 * The mark for a Bitcoin & gold asset: gold for any metal, the ₿ disc for
 * Bitcoin, and the generic ticker disc for anything the catalog lists later
 * (the server decides the list; this only picks a picture).
 */
export function CryptoAssetMark({
  ticker,
  category,
  size = 40,
}: {
  ticker?: string | null;
  category?: string | null;
  size?: number;
}) {
  if (category === 'metal') return <GoldMark size={size} />;
  if ((ticker || '').toUpperCase() === 'BTC') return <BitcoinMark size={size} />;
  return <TickerLogo ticker={ticker || '?'} color="#334155" size={size} />;
}
