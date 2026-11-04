// What the external (WhatsApp / Instagram) image card says for an
// investment the member just made: the same verified activity Comunidad
// shows, laid out like the Futuros card, with the venue it trades on.
// "Mostrar monto" off hides every dollar figure; the percent stays.

import { formatDecimal, formatUsdAmount } from './numberLocale';
import { cryptoCategoryOf, isPerps, tradeSide, type ActivityShare } from '../components/ActivitySummary';
import type { ShareVenue } from '../components/share/VenueShareCard';

export type ActivityCardKind = 'stock' | 'crypto' | 'perps';

export interface ActivityCardContent {
  kind: ActivityCardKind;
  product: string;
  venue: ShareVenue;
  ticker: string;
  name: string | null;
  side: 'buy' | 'sell';
  tag: { icon: string; text: string } | null;
  kindLabel: string | null;
  headline: string;
  headlineValue: number | null;
  headlineIsText: boolean;
  usdLine: string | null;
  rows: { label: string; value: string }[];
  /** The text before the link (utils/shareCardLink.composeShareMessage adds it). */
  lead: string;
}

const signedPct = (v: number) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${formatDecimal(Math.abs(v), { decimals: 2 })}%`;
const signedUsd = (v: number) =>
  `${v > 0.004 ? '+' : v < -0.004 ? '−' : ''}US$${formatDecimal(Math.abs(v), { decimals: 2 })}`;

/** Null for anything that is not a stock, gold/Bitcoin or Futuros trade. */
export function activityCardContent(activity: ActivityShare, showAmount: boolean): ActivityCardContent | null {
  const side = tradeSide(activity);
  if (!side) return null;
  const kind: ActivityCardKind = isPerps(activity) ? 'perps' : cryptoCategoryOf(activity) ? 'crypto' : 'stock';
  const metal = cryptoCategoryOf(activity) === 'metal';
  const ticker = (activity.ticker || (kind === 'crypto' ? (metal ? 'ORO' : 'BTC') : '')).toUpperCase();
  if (!ticker) return null;
  const product = kind === 'perps' ? 'Futuros' : kind === 'crypto' ? 'Oro y Bitcoin' : 'Acciones';
  const venue: ShareVenue = kind === 'perps' ? 'hyperliquid' : kind === 'crypto' ? 'pancakeswap' : 'ondo';

  const amountN = activity.amountUsd != null ? Number(activity.amountUsd) : NaN;
  const amount = showAmount && Number.isFinite(amountN) && amountN > 0 ? formatUsdAmount(activity.amountUsd!) : null;
  const pctN = activity.pnlPct != null ? Number(activity.pnlPct) : NaN;
  const hasPnl = Number.isFinite(pctN);
  const pnlUsdN = activity.pnlUsd != null ? Number(activity.pnlUsd) : NaN;

  const verb = kind === 'perps'
    ? (side === 'buy' ? 'Abrí' : 'Cerré')
    : (side === 'buy' ? 'Compré' : 'Vendí');
  const tag = kind === 'perps'
    ? null
    : { icon: side === 'buy' ? 'trending-up' : 'trending-down', text: side === 'buy' ? 'Compra' : 'Venta' };

  let kindLabel: string | null;
  let headline: string;
  let headlineValue: number | null = null;
  let headlineIsText = false;
  let usdLine: string | null = null;
  const rows: { label: string; value: string }[] = [];
  if (hasPnl) {
    kindLabel = kind === 'perps'
      ? (side === 'sell' ? 'Resultado' : activity.position === 'closed' ? 'Al cerrar' : 'Desde la apertura')
      : side === 'sell' ? 'Resultado' : activity.position === 'closed' ? 'Al vender' : 'Desde la compra';
    headline = signedPct(pctN);
    headlineValue = pctN;
    if (showAmount && Number.isFinite(pnlUsdN)) usdLine = signedUsd(pnlUsdN);
    if (amount) rows.push({ label: side === 'buy' ? 'Monto' : 'Recibido', value: amount });
  } else if (amount) {
    kindLabel = kind === 'perps' ? (side === 'buy' ? 'Posición abierta' : 'Posición cerrada') : verb;
    headline = amount;
  } else {
    kindLabel = kind === 'perps' ? (side === 'buy' ? 'Posición abierta' : 'Posición cerrada') : null;
    headline = `${verb} ${ticker}`;
    headlineIsText = true;
  }

  const what = hasPnl
    ? `${verb} ${ticker}: ${signedPct(pctN)}${usdLine ? ` (${usdLine})` : ''}.`
    : `${verb} ${ticker}${amount ? ` por ${amount}` : ''}.`;
  const lead = `${what}\n${TAILS[kind]}`;

  return {
    kind, product, venue, ticker, name: activity.name || null, side, tag, kindLabel, headline, headlineValue,
    headlineIsText, usdLine, rows, lead,
  };
}

const TAILS: Record<ActivityCardKind, string> = {
  perps: 'Opero futuros desde Confío 💚',
  crypto: 'Compro oro y bitcoin desde Confío 💚',
  stock: 'Invierto en acciones de EE.UU. desde Confío 💚',
};

/** A holding shared later, from its own page: "En cartera", the return since
 * the purchase (the figure the investor profile shows) and, only when the
 * member turns dollars on, the gain and the current value. */
export function holdingCardContent(h: {
  kind: 'stock' | 'crypto';
  ticker: string;
  name?: string | null;
  pnlPct?: string | null;
  pnlUsd?: string | null;
  valueUsd?: string | number | null;
}, showAmount: boolean): ActivityCardContent | null {
  const ticker = (h.ticker || '').toUpperCase();
  if (!ticker) return null;
  const pctN = h.pnlPct != null ? Number(h.pnlPct) : NaN;
  const pnlUsdN = h.pnlUsd != null ? Number(h.pnlUsd) : NaN;
  const valueN = h.valueUsd != null ? Number(h.valueUsd) : NaN;
  const hasPnl = Number.isFinite(pctN);
  const value = showAmount && Number.isFinite(valueN) && valueN > 0 ? formatUsdAmount(String(valueN)) : null;
  const usdLine = hasPnl && showAmount && Number.isFinite(pnlUsdN) ? signedUsd(pnlUsdN) : null;
  const headline = hasPnl ? signedPct(pctN) : `Tengo ${ticker}`;
  const what = hasPnl
    ? `Mi inversión en ${ticker}: ${signedPct(pctN)}${usdLine ? ` (${usdLine})` : ''} desde la compra.`
    : `Tengo ${ticker} en mi cartera.`;
  return {
    kind: h.kind,
    product: h.kind === 'crypto' ? 'Oro y Bitcoin' : 'Acciones',
    venue: h.kind === 'crypto' ? 'pancakeswap' : 'ondo',
    ticker,
    name: h.name || null,
    side: 'buy',
    tag: { icon: 'briefcase', text: 'En cartera' },
    kindLabel: hasPnl ? 'Desde la compra' : null,
    headline,
    headlineValue: hasPnl ? pctN : null,
    headlineIsText: !hasPnl,
    usdLine,
    rows: value ? [{ label: 'Valor actual', value }] : [],
    lead: `${what}\n${TAILS[h.kind]}`,
  };
}

