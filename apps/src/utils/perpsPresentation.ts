// How Futuros reads on screen: names, signs and precision. Numbers follow
// the viewer's country format (utils/numberLocale), prices keep the
// precision the market trades in, money is two decimals, and an unknown
// value is "—", never a confident zero.

import { formatDecimal } from './numberLocale';
import type { AssetClass, PerpPosition, Side } from '../services/perps';

/** What the money already shown is worth: the open position's margin on
 *  the venue, else its step's known amount, else what was put in (in flight). */
/** An open position's result at a live price (between the server's reads);
 *  the server's own figure when there is no live price or no size yet. */
export const livePnl = (p: PerpPosition, mid: number | null | undefined): number | null =>
  p.state === 'open' && mid != null && p.entryPx && p.size != null
    ? (mid - p.entryPx) * p.size
    : p.unrealizedPnlUsd;

export const positionValueUsd = (p: PerpPosition): number =>
  p.valueUsd ?? p.marginUsedUsd ?? p.marginUsd ?? 0;

export const ASSET_CLASS_LABELS: Record<AssetClass, string> = {
  crypto: 'Cripto',
  stock: 'Acciones',
  index: 'Índices',
  commodity: 'Materias primas',
  fx: 'Divisas',
};
export const ASSET_CLASS_ORDER: AssetClass[] = ['crypto', 'stock', 'index', 'commodity', 'fx'];

export const sideLabel = (side: Side) => (side === 'long' ? 'Largo' : 'Corto');
export const sideVerb = (side: Side) => (side === 'long' ? 'sube' : 'baja');

/** Long = emerald, short = sky blue (the app's "money out" hue: neutral, never alarming). */
export const SIDE_COLORS: Record<Side, { solid: string; text: string; soft: string }> = {
  long: { solid: '#10B981', text: '#047857', soft: '#D1FAE5' },
  short: { solid: '#2563EB', text: '#1D4ED8', soft: '#DBEAFE' },
};

export const UP = '#059669';
export const DOWN = '#DC2626';

export const pnlColor = (value: number | null | undefined, neutral = '#6B7280') =>
  value == null || value === 0 ? neutral : value > 0 ? UP : DOWN;

/** Price with the precision it trades at: Hyperliquid prices carry up to 5
 *  significant figures (1.0847 ≠ 1.0801), never fewer than 2 decimals. */
export const formatPerpPrice = (px: number | null | undefined): string => {
  if (px == null || !Number.isFinite(px) || px <= 0) return '—';
  const digits = Math.min(8, Math.max(2, 5 - (Math.floor(Math.log10(px)) + 1)));
  return `$${formatDecimal(px, { decimals: digits })}`;
};

export const formatUsd = (v: number | null | undefined, digits = 2): string =>
  v == null || !Number.isFinite(v)
    ? '—'
    : `$${formatDecimal(Math.abs(v), { decimals: digits })}`;

export const formatUsdSigned = (v: number | null | undefined): string => {
  if (v == null || !Number.isFinite(v)) return '—';
  const sign = v > 0.004 ? '+' : v < -0.004 ? '−' : '';
  return `${sign}${formatUsd(v)}`;
};

export const formatPctSigned = (v: number | null | undefined, digits = 2): string => {
  if (v == null || !Number.isFinite(v)) return '—';
  const sign = v > 0 ? '+' : v < 0 ? '−' : '';
  return `${sign}${formatDecimal(Math.abs(v), { decimals: digits })}%`;
};

export const formatCompactUsd = (v: number | null | undefined): string => {
  if (v == null || !Number.isFinite(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 1e9) return `$${formatDecimal(abs / 1e9, { decimals: 1 })} mil M`;
  if (abs >= 1e6) return `$${formatDecimal(abs / 1e6, { decimals: 1 })} M`;
  if (abs >= 1e3) return `$${formatDecimal(abs / 1e3, { decimals: 1 })} mil`;
  return formatUsd(abs, 0);
};

/** Hourly funding in words: who pays whom, per hour. */
export const fundingLine = (rate: number | null | undefined): string => {
  if (rate == null || !Number.isFinite(rate)) return '—';
  const pct = formatDecimal(Math.abs(rate) * 100, { decimals: 4 });
  if (rate === 0) return 'Sin financiamiento ahora';
  return rate > 0 ? `Los largos pagan ${pct}%/h` : `Los cortos pagan ${pct}%/h`;
};

/** 0 (calm) → 1 (as risky as the venue allows), for the leverage tint. */
export const leverageRisk = (leverage: number, maxLeverage: number) =>
  maxLeverage <= 1 ? 0 : Math.min(1, Math.max(0, (leverage - 1) / (maxLeverage - 1)));

const mix = (a: number[], b: number[], t: number) => a.map((x, i) => Math.round(x + (b[i] - x) * t));
const hex = (rgb: number[]) => `#${rgb.map((x) => x.toString(16).padStart(2, '0')).join('')}`;

/** Emerald → amber → red as leverage climbs. */
export const leverageColor = (leverage: number, maxLeverage: number): string => {
  const t = leverageRisk(leverage, maxLeverage);
  const emerald = [16, 185, 129];
  const amber = [245, 158, 11];
  const red = [220, 38, 38];
  return hex(t < 0.5 ? mix(emerald, amber, t * 2) : mix(amber, red, (t - 0.5) * 2));
};

export const leverageWord = (leverage: number, maxLeverage: number): string => {
  const t = leverageRisk(leverage, maxLeverage);
  if (leverage <= 1) return 'Sin apalancamiento';
  if (t < 0.15) return 'Moderado';
  if (t < 0.45) return 'Alto';
  if (t < 0.8) return 'Muy alto';
  return 'Extremo';
};

/** A deterministic hue per ticker for initial discs. */
export const tickerColor = (ticker: string) => {
  let seed = 0;
  for (const c of ticker) seed = (seed * 31 + c.charCodeAt(0)) % 359;
  return `hsl(${seed}, 45%, 38%)`;
};

/** The Spanish status line for a position that is between steps. */
export const stepLabel = (nextAction: string, state: string): string | null => {
  switch (nextAction) {
    case 'wait_bridge':
      return 'Tu margen va en camino a Hyperliquid';
    case 'retry_bridge':
      return 'La transferencia no se completó: tus USDT volvieron';
    case 'open_order':
      return 'Tu margen llegó: falta abrir la posición';
    case 'finish_margin':
      return 'Tu margen extra llegó: falta sumarlo';
    case 'wait_fill':
      return 'Tu orden espera su precio';
    case 'return':
      return state === 'liquidated' ? 'Se liquidó: revisa si quedó saldo' : 'Cerrada: trae el dinero a tus dólares';
    case 'wait_return':
      return 'Tu dinero va en camino a tus dólares';
    case 'enter':
      return 'Tu dinero llegó: confirma para sumarlo';
    default:
      return null;
  }
};
