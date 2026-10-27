// What a Futuros share card says: the member's own position (open) or its
// realized result (closed), posted by the member to their own social
// networks — never by Confío. Percent by default; dollars only when the
// member turns them on (it is their money, and their call to show it).

import { formatDecimal } from './numberLocale';
import { SHARE_LINKS } from '../config/shareLinks';
import { formatPerpPrice, sideLabel } from './perpsPresentation';
import type { PerpPosition } from '../services/perps';

export type FuturesShareKind = 'position' | 'result';

export interface FuturesShareContent {
  kind: FuturesShareKind;
  ticker: string;
  name: string;
  side: PerpPosition['side'];
  sideLine: string; // "Largo 5x"
  headline: string; // "+12,40%"
  headlineValue: number;
  caption: string; // "sobre el margen" / "resultado con todos los costos"
  usdLine: string | null; // "+US$1,24", only when shown
  rows: { label: string; value: string }[];
  liquidated: boolean;
  message: string; // the text that rides with the image
}

const pct = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${formatDecimal(Math.abs(v), { decimals: 2 })}%`;
const usd = (v: number) =>
  `${v > 0.004 ? '+' : v < -0.004 ? '−' : ''}US$${formatDecimal(Math.abs(v), { decimals: 2 })}`;

/** The open card's figures: P&L on the margin at work (live when given). */
export const openShareFigures = (position: PerpPosition, liveMid: number | null, shownPx: number | null = null) => {
  const pnl = liveMid != null && position.entryPx && position.size != null
    ? (liveMid - position.entryPx) * position.size : position.unrealizedPnlUsd;
  const margin = position.marginUsedUsd ?? null;
  const roe = pnl != null && margin ? (pnl / margin) * 100
    : position.returnOnEquity != null ? position.returnOnEquity * 100 : null;
  // The price the screen shows (live, the server's mark, then the market's).
  return { pnl, roe, markPx: liveMid ?? position.markPx ?? shownPx };
};

/** Null when there is nothing honest to show yet (no figure known). */
export const futuresShareContent = (
  position: PerpPosition,
  kind: FuturesShareKind,
  showUsd: boolean,
  liveMid: number | null = null,
  /** The screen's own fallback price (the market's mark). */
  shownPx: number | null = null,
): FuturesShareContent | null => {
  const sideLine = `${sideLabel(position.side)} ${position.leverage}x`;
  const liquidated = Boolean(position.liquidation);
  let headlineValue: number;
  let caption: string;
  let usdValue: number | null;
  let rows: { label: string; value: string }[];
  if (kind === 'position') {
    const { pnl, roe, markPx } = openShareFigures(position, liveMid, shownPx);
    if (roe == null || !Number.isFinite(roe)) return null;
    headlineValue = roe;
    caption = 'sobre el margen';
    usdValue = pnl;
    rows = [
      { label: 'Entrada', value: formatPerpPrice(position.entryPx) },
      { label: 'Precio actual', value: formatPerpPrice(markPx) },
    ];
  } else {
    const putIn = position.putInUsd ?? position.marginUsd;
    const result = position.resultUsd;
    if (result == null || !putIn) return null;
    headlineValue = (result / putIn) * 100;
    caption = 'resultado con todos los costos';
    usdValue = result;
    rows = [{ label: 'Entrada', value: formatPerpPrice(position.entryPx) }];
  }
  const headline = pct(headlineValue);
  const usdLine = showUsd && usdValue != null && Number.isFinite(usdValue) ? usd(usdValue) : null;
  const what = kind === 'position'
    ? `Mi posición en ${position.ticker}: ${sideLine}, ${headline}${usdLine ? ` (${usdLine})` : ''} sobre el margen.`
    : liquidated
      ? `Me liquidaron ${position.ticker} (${sideLine}): ${headline}${usdLine ? ` (${usdLine})` : ''} con todos los costos.`
      : `Cerré ${position.ticker} (${sideLine}): ${headline}${usdLine ? ` (${usdLine})` : ''} con todos los costos.`;
  const message = `${what}\nOpero futuros desde Confío 💚\n\n${SHARE_LINKS.web.landing}\n\n${SHARE_LINKS.hashtags}`;
  return {
    kind,
    ticker: position.ticker,
    name: position.name,
    side: position.side,
    sideLine,
    headline,
    headlineValue,
    caption,
    usdLine,
    rows,
    liquidated: kind === 'result' && liquidated,
    message,
  };
};
