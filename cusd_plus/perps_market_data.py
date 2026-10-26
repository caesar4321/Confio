"""Futuros display data: mark price, 24h change, funding, open interest,
volume and candles, straight from Hyperliquid (cached briefly). Display
only: trading uses the live book at plan time (perps_flow)."""
from __future__ import annotations

import logging
import time
from decimal import Decimal

from django.core.cache import cache

from . import hyperliquid

logger = logging.getLogger(__name__)

CTX_TTL_S = 15
CANDLE_TTL_S = 60
RANGES = {
    # range -> (interval, lookback seconds)
    '1D': ('15m', 24 * 3600),
    '1W': ('1h', 7 * 24 * 3600),
    '1M': ('4h', 30 * 24 * 3600),
    '3M': ('1d', 90 * 24 * 3600),
    '1Y': ('1d', 365 * 24 * 3600),
}


def _dec(value) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None
    return number if number.is_finite() else None


def contexts(dex: str = '') -> dict[str, dict]:
    """coin -> {mark_px, prev_day_px, funding, open_interest, day_volume_usd}."""
    key = f'perps_ctx:{dex or "core"}'
    cached = cache.get(key)
    if cached is not None:
        return cached
    meta, ctxs = hyperliquid.meta_and_asset_ctxs(dex)
    out = {}
    for entry, ctx in zip(meta.get('universe') or [], ctxs):
        if not isinstance(entry, dict) or not isinstance(ctx, dict) or not isinstance(entry.get('name'), str):
            continue
        mark = _dec(ctx.get('markPx'))
        prev = _dec(ctx.get('prevDayPx'))
        oi = _dec(ctx.get('openInterest'))
        out[entry['name']] = {
            'mark_px': mark,
            'prev_day_px': prev,
            'funding': _dec(ctx.get('funding')),
            'open_interest_usd': (oi * mark) if (oi is not None and mark is not None) else None,
            'day_volume_usd': _dec(ctx.get('dayNtlVlm')),
        }
    cache.set(key, out, CTX_TTL_S)
    return out


def all_contexts(dexes) -> dict[str, dict]:
    merged = {}
    for dex in sorted(set(dexes)):
        try:
            merged.update(contexts(dex))
        except hyperliquid.HyperliquidError:
            logger.warning('perps contexts unavailable for dex %r', dex)
    return merged


def day_change_pct(ctx: dict | None) -> float | None:
    if not ctx or not ctx.get('mark_px') or not ctx.get('prev_day_px'):
        return None
    return float((ctx['mark_px'] - ctx['prev_day_px']) / ctx['prev_day_px'] * 100)


def candles(coin: str, range_: str) -> list[dict]:
    if range_ not in RANGES:
        raise ValueError('bad_range')
    key = f'perps_candles:{coin}:{range_}'
    cached = cache.get(key)
    if cached is not None:
        return cached
    interval, lookback = RANGES[range_]
    end = int(time.time() * 1000)
    rows = hyperliquid.candles(coin, interval, end - lookback * 1000, end)
    out = []
    for row in rows:
        close = _dec(row.get('c')) if isinstance(row, dict) else None
        start = row.get('t') if isinstance(row, dict) else None
        if close is None or not isinstance(start, int):
            continue
        out.append({'timestamp': start, 'close': float(close)})
    cache.set(key, out, CANDLE_TTL_S)
    return out
