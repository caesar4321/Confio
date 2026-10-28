// Hyperliquid's public info API, read straight from the venue (no Confío
// server). The app uses it to check what it signs against the market and
// the position as Hyperliquid itself reports them, and the Salida de
// emergencia uses it when Confío is gone.

const API = 'https://api.hyperliquid.xyz';
/** USDC is spot token 0: the collateral of core and of the dexes Confío lists. */
export const USDC_COLLATERAL = 0;

/** A request that never hangs a money flow: aborted after `ms`, surfaced as an error. */
export const fetchBounded = async (
  url: string, init: RequestInit, fetcher: typeof fetch = fetch, ms = 15_000,
): Promise<Response> => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  try {
    return await fetcher(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
};

export const hlInfo = async (body: Record<string, unknown>, fetcher: typeof fetch = fetch): Promise<any> => {
  const res = await fetchBounded(`${API}/info`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }, fetcher);
  if (!res.ok) throw new Error(`Hyperliquid respondió ${res.status}`);
  return res.json();
};

export interface VenueMarket {
  coin: string;
  dex: string;
  assetId: number;
  szDecimals: number;
  maxLeverage: number;
  markPx: number;
  usdcCollateral: boolean;
}

export const dexOf = (coin: string) => (coin.includes(':') ? coin.split(':')[0] : '');

/** The market as Hyperliquid lists it: asset id = core index, or
 *  100000 + dex position × 10000 + index for a builder (HIP-3) dex. */
export const venueMarket = async (coin: string, fetcher: typeof fetch = fetch): Promise<VenueMarket> => {
  const dex = dexOf(coin);
  // Both read at once (a builder dex needs its position in the dex list too).
  const metaRead = hlInfo(dex ? { type: 'metaAndAssetCtxs', dex } : { type: 'metaAndAssetCtxs' }, fetcher);
  metaRead.catch(() => {}); // judged below, after the dex list
  let position = 0;
  if (dex) {
    const dexs: any[] = await hlInfo({ type: 'perpDexs' }, fetcher);
    position = Array.isArray(dexs) ? dexs.findIndex((d) => d?.name === dex) : -1;
    if (position <= 0) throw new Error(`Hyperliquid no lista el mercado ${coin}`);
  }
  const metaCtx = await metaRead;
  const universe: any[] = metaCtx?.[0]?.universe;
  if (!Array.isArray(universe)) throw new Error('Hyperliquid respondió sin mercados');
  const index = universe.findIndex((u) => u?.name === coin);
  const markPx = Number(metaCtx?.[1]?.[index]?.markPx);
  if (index < 0 || !(markPx > 0)) throw new Error(`Hyperliquid no lista el mercado ${coin}`);
  return {
    coin, dex, szDecimals: Number(universe[index].szDecimals || 0), maxLeverage: Number(universe[index].maxLeverage || 0),
    assetId: position === 0 ? index : 100000 + position * 10000 + index, markPx,
    usdcCollateral: Number(metaCtx[0].collateralToken ?? -1) === USDC_COLLATERAL,
  };
};

/** The account's margin setting on `coin` (applies to the next order). */
export const venueLeverage = async (
  user: string, coin: string, fetcher: typeof fetch = fetch,
): Promise<{ type: string; value: number }> => {
  const data = await hlInfo({ type: 'activeAssetData', user, coin }, fetcher);
  const type = data?.leverage?.type;
  const value = Number(data?.leverage?.value);
  if (typeof type !== 'string' || !Number.isFinite(value)) throw new Error('Hyperliquid respondió incompleto');
  return { type, value };
};

export type OrderOutcome = 'unknown' | 'filled' | 'open' | 'dead';

/** What became of an order, by its client order id: 'unknown' (never reached
 *  Hyperliquid), 'filled' (all or part), 'open' (resting) or 'dead', and when
 *  Hyperliquid placed it. */
export const venueOrderOutcome = async (
  user: string, cloid: string, fetcher: typeof fetch = fetch,
): Promise<{ outcome: OrderOutcome; placedMs: number | null }> => {
  const body = await hlInfo({ type: 'orderStatus', user, oid: cloid }, fetcher);
  if (body?.status === 'unknownOid') return { outcome: 'unknown', placedMs: null };
  const order = body?.order;
  if (body?.status !== 'order' || !order) throw new Error('Hyperliquid respondió incompleto');
  const inner = order.order || {};
  const placedMs = Number.isFinite(Number(inner.timestamp)) ? Number(inner.timestamp) : null;
  if (order.status === 'filled' || Number(inner.origSz) > Number(inner.sz)) return { outcome: 'filled', placedMs };
  if (order.status === 'open') return { outcome: 'open', placedMs };
  return { outcome: 'dead', placedMs };
};

/** Walk Hyperliquid's live book for `size`: the average fill and the mid. */
export const venueFill = async (
  coin: string, isBuy: boolean, size: number, fetcher: typeof fetch = fetch,
): Promise<{ avgPx: number; mid: number }> => {
  const book = await hlInfo({ type: 'l2Book', coin }, fetcher);
  const [bids, asks] = Array.isArray(book?.levels) ? book.levels : [];
  if (!Array.isArray(bids) || !Array.isArray(asks) || !bids.length || !asks.length) {
    throw new Error('Hyperliquid respondió sin libro');
  }
  const mid = (Number(bids[0].px) + Number(asks[0].px)) / 2;
  let left = size;
  let cost = 0;
  for (const level of isBuy ? asks : bids) {
    const take = Math.min(left, Number(level.sz));
    cost += take * Number(level.px);
    left -= take;
    if (left <= 1e-12) break;
  }
  if (left > 1e-12 || !(mid > 0)) throw new Error('Hyperliquid no tiene liquidez para este monto');
  return { avgPx: cost / size, mid };
};

/** The live reduce-only trigger orders (take-profit / stop-loss) on `coin`. */
export const venueTriggers = async (
  user: string, coin: string, fetcher: typeof fetch = fetch,
): Promise<{ oid: number; triggerPx: number; limitPx: number; size: number; kind: 'tp' | 'sl' | null }[]> => {
  const dex = dexOf(coin);
  const orders = await hlInfo(dex ? { type: 'frontendOpenOrders', user, dex } : { type: 'frontendOpenOrders', user }, fetcher);
  if (!Array.isArray(orders)) throw new Error('Hyperliquid respondió incompleto');
  return orders
    .filter((o: any) => o?.coin === coin && o.isTrigger && o.reduceOnly)
    .map((o: any) => ({
      oid: Number(o.oid), triggerPx: Number(o.triggerPx), limitPx: Number(o.limitPx), size: Number(o.sz),
      kind: String(o.orderType).includes('Take Profit') ? 'tp' as const
        : String(o.orderType).includes('Stop') ? 'sl' as const : null,
    }));
};

/** Every open order on `coin`: a resting limit entry, and the protection
 *  waiting on it (reduce-only triggers). */
export const venueOpenOrders = async (
  user: string, coin: string, fetcher: typeof fetch = fetch,
): Promise<{ oid: number; reduceOnly: boolean; isTrigger: boolean }[]> => {
  const dex = dexOf(coin);
  const orders = await hlInfo(dex ? { type: 'frontendOpenOrders', user, dex } : { type: 'frontendOpenOrders', user }, fetcher);
  if (!Array.isArray(orders)) throw new Error('Hyperliquid respondió incompleto');
  return orders
    .filter((o: any) => o?.coin === coin)
    .map((o: any) => ({ oid: Number(o.oid), reduceOnly: Boolean(o.reduceOnly), isTrigger: Boolean(o.isTrigger) }));
};

export interface VenuePosition { szi: number; leverage: number; isolated: boolean }

/** The member's live position on `coin`, or null when there is none. */
export const venuePosition = async (
  user: string, coin: string, fetcher: typeof fetch = fetch,
): Promise<VenuePosition | null> => {
  const dex = dexOf(coin);
  const state = await hlInfo(dex ? { type: 'clearinghouseState', user, dex } : { type: 'clearinghouseState', user }, fetcher);
  if (!Array.isArray(state?.assetPositions)) throw new Error('Hyperliquid respondió sin posiciones');
  const p = state.assetPositions.map((e: any) => e?.position).find((x: any) => x?.coin === coin);
  const szi = Number(p?.szi || 0);
  if (!p || !szi) return null;
  return { szi, leverage: Number(p.leverage?.value || 0), isolated: p.leverage?.type === 'isolated' };
};
