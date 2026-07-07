"""
Ondo GM Backend API client — server-side proxy behind the Acciones screens.

Display data ONLY (chain-first rule): accrue(), settlement and anything
money-touching never depend on this API — Ondo says so themselves ("prices
are intended for display only"; trading prices come from the attestation
quote at execution time).

Endpoints (verified live 2026-07-07 with the read-only key):
  GET /v1/assets/all/market                       438 assets: price, 24h
                                                  change + history, sessions,
                                                  name/52w/mcap
  GET /v1/assets/{symbol}/prices/ohlc             chart candles; only the
                                                  interval/range pairs in
                                                  OHLC_RANGES are valid
  GET /v1/status/market                           session state machine
  GET /v1/status/assets                           per-asset halts (earnings…)

Cached in Django cache per Ondo's endpoint-caching guidance — one upstream
call per TTL serves every app user.
"""
import logging

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

BASE = 'https://api.gm.ondo.finance/v1'

# Client-facing range key -> the API's only valid interval/range pairs.
OHLC_RANGES = {
    '1D': ('15min', '1day'),
    '1M': ('1hour', '1month'),
    '3M': ('1day', '3month'),
    '6M': ('1day', '6month'),
    '1Y': ('1day', '1year'),
    'MAX': ('1day', 'all'),
}


def _get(path: str, params: dict | None = None) -> dict | list:
    api_key = getattr(settings, 'ONDO_API_KEY', '')
    if not api_key:
        raise RuntimeError('ONDO_API_KEY not configured')
    resp = requests.get(
        f'{BASE}{path}',
        params=params or {},
        headers={'x-api-key': api_key},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _cached(key: str, ttl: int, fetch):
    data = cache.get(key)
    if data is None:
        data = fetch()
        cache.set(key, data, ttl)
    return data


def all_market() -> list:
    """Full asset universe with prices and 24h stats. ~438 entries."""
    return _cached('gm_all_market_v1', 60, lambda: _get('/assets/all/market'))


def market_status() -> dict:
    return _cached('gm_status_market_v1', 30, lambda: _get('/status/market'))


def asset_statuses() -> list:
    return _cached('gm_status_assets_v1', 60, lambda: _get('/status/assets'))


def ohlc(symbol: str, range_key: str) -> list:
    """Candles for one asset. range_key must be in OHLC_RANGES."""
    interval, rng = OHLC_RANGES[range_key]
    return _cached(
        f'gm_ohlc_v1_{symbol}_{range_key}', 300,
        lambda: _get(
            f'/assets/{symbol}/prices/ohlc',
            {'interval': interval, 'range': rng},
        ).get('primaryMarket', {}).get('data', []),
    )


def session_from_status(status: dict) -> str:
    """Map Ondo's market status onto the app's session union
    (core | extended | off-hours | closed)."""
    market = (status.get('marketStatus') or '').lower()
    if market == 'regular':
        return 'core'
    if market in ('premarket', 'postmarket', 'overnight'):
        return 'extended'
    if market == 'offhours' or (status.get('offhours') or {}).get('isOpen'):
        return 'off-hours'
    if status.get('isOpen'):
        return 'extended'
    return 'closed'
