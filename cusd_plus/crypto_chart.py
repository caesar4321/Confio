"""Price history for the crypto & gold detail chart (display only).

Trades are always priced by PancakeSwap (crypto_prices.quote_exact_in);
this module only draws the line. Our own 15-minute snapshots start at
launch, so history comes from OKX's public candles, which carry both
BTC-USDT and XAUT-USDT (Binance has no XAUt; CoinGecko's free tier stops
at 365 days). Same range keys and candle shape as gmOhlc, so the app reuses
the stock chart's range selector.
"""
from __future__ import annotations

import time

import requests
from django.core.cache import cache

OKX_CANDLES = 'https://www.okx.com/api/v5/market/history-candles'
PAGE = 100  # OKX's max per request
MAX_PAGES = 8

DAY_MS = 86_400_000
# range -> (OKX bar, lookback in ms or None = everything, cache seconds)
RANGES = {
    '1D': ('15m', DAY_MS, 300),
    '1M': ('4H', 30 * DAY_MS, 1800),
    '3M': ('12Hutc', 90 * DAY_MS, 3600),
    '6M': ('1Dutc', 182 * DAY_MS, 3600),
    '1Y': ('1Dutc', 365 * DAY_MS, 3600),
    'MAX': ('1Wutc', None, 6 * 3600),
}


def _fetch(instrument: str, bar: str, lookback_ms: int | None) -> list[dict]:
    since = int(time.time() * 1000) - lookback_ms if lookback_ms else 0
    rows: dict[int, dict] = {}
    after = None
    for _ in range(MAX_PAGES):
        params = {'instId': instrument, 'bar': bar, 'limit': PAGE}
        if after is not None:
            params['after'] = after  # older than this timestamp
        resp = requests.get(OKX_CANDLES, params=params, timeout=10)
        resp.raise_for_status()
        body = resp.json()
        if str(body.get('code')) != '0':
            raise RuntimeError(f"OKX {body.get('code')}: {body.get('msg')}")
        page = body.get('data') or []
        for c in page:  # newest first: [ts, open, high, low, close, ...]
            ts = int(c[0])
            if ts >= since:
                rows[ts] = {'timestamp': ts, 'open': float(c[1]), 'high': float(c[2]),
                            'low': float(c[3]), 'close': float(c[4])}
        if len(page) < PAGE or int(page[-1][0]) < since:
            break
        after = page[-1][0]
    return [rows[ts] for ts in sorted(rows)]


def ohlc(token, range_key: str) -> list[dict]:
    """Ascending candles for one catalog token. Raises on upstream failure
    (the resolver returns null so the app shows a retry, never a flat line)."""
    instrument = token.chart_instrument
    if not instrument:
        return []
    bar, lookback, ttl = RANGES[range_key]
    key = f'crypto_ohlc_v1_{instrument}_{range_key}'
    data = cache.get(key)
    if data is None:
        data = _fetch(instrument, bar, lookback)
        cache.set(key, data, ttl)
    return data
