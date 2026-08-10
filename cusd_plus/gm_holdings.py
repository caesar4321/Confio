"""
Ondo GM (tokenized stock) holdings — universe scan, no per-user bookkeeping.

Design (locked with Julian 2026-07-10, replacing a per-account holdings
model): the ONLY durable state is a system-wide token registry
(gm_tokens.json: symbol -> {address, decimals}, one entry per GM asset).
A user's portfolio is discovered by scanning the whole registry against
their address with Multicall3 — balanceOf calls packed into 250-call
chunks — so the chain stays the single source of truth and nothing can go
invisible because a row wasn't created. No DB model, no sync jobs.

Freshness mirrors vault.position_usd: 30s fresh cache per address, 7-day
last-known fallback so a dead node degrades to a stale portfolio, never a
vanished one. USD values are never stored — the resolver computes them
from the globally cached GM market payload (display only, chain-first).

The live registry comes from Ondo's `/assets/all/addresses` metadata endpoint
and is cached server-side for one day. `gm_tokens.json` is only the deploy-time
fallback snapshot, so an upstream outage never makes held positions vanish.
"""
import json
import logging
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
import re

from django.core.cache import cache
from eth_abi import decode, encode
from eth_utils import keccak

from . import vault

logger = logging.getLogger(__name__)

# Canonical Multicall3 (same address on BSC as everywhere).
MULTICALL3 = '0xcA11bde05977b3631167028862bE2a173976CA11'
SEL_TRY_AGGREGATE = keccak(text='tryAggregate(bool,(address,bytes)[])')[:4]
SEL_BALANCE_OF = keccak(text='balanceOf(address)')[:4]

# Subcalls per eth_call — keeps calldata well under public-node limits.
CHUNK = 250

SCAN_TTL = 30
SCAN_LAST_TTL = 7 * 24 * 3600
REGISTRY_TTL = 24 * 3600
REGISTRY_FALLBACK_TTL = 5 * 60
REGISTRY_CACHE_KEY = 'gm_bsc_registry_v1'


@lru_cache(maxsize=1)
def _fallback_registry() -> dict:
    path = Path(__file__).parent / 'gm_tokens.json'
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError):
        logger.exception('GM fallback registry is missing or malformed')
        return {}


def registry() -> dict | None:
    """BSC symbol -> address metadata from Ondo, with local outage fallback."""
    cached = cache.get(REGISTRY_CACHE_KEY)
    if cached is not None:
        return cached
    fallback = _fallback_registry()
    try:
        from . import gm_api
        rows = gm_api.all_addresses()
        live = {}
        for row in rows:
            symbol = str(row.get('symbol') or '')
            for item in row.get('addresses') or []:
                address = str(item.get('address') or '')
                if (item.get('networkChainId') == 'bsc-56'
                        and re.fullmatch(r'0x[0-9a-fA-F]{40}', address)):
                    live[symbol] = {
                        'address': address,
                        'decimals': int(item.get('decimals') or 18),
                    }
                    break
        result = live or fallback
        if result:
            cache.set(REGISTRY_CACHE_KEY, result, REGISTRY_TTL if live else REGISTRY_FALLBACK_TTL)
        return result or None
    except Exception:  # noqa: BLE001 — portfolio degrades to shipped snapshot
        logger.warning('GM address registry unavailable; using local fallback', exc_info=True)
        if fallback:
            # Retry Ondo soon after an outage, but avoid a request stampede.
            cache.set(REGISTRY_CACHE_KEY, fallback, REGISTRY_FALLBACK_TTL)
        return fallback or None


def _scan(
    user_bsc_address: str,
    token_registry: dict,
    *,
    block_tag: str = 'latest',
    require_complete: bool = False,
) -> dict:
    """One Multicall3 pass over the whole registry; returns nonzero
    balances as {symbol: units_float}. Raises on RPC failure."""
    entries = list(token_registry.items())
    holder_arg = encode(['address'], [user_bsc_address])
    held = {}
    for i in range(0, len(entries), CHUNK):
        chunk = entries[i:i + CHUNK]
        calls = [
            (item['address'], SEL_BALANCE_OF + holder_arg)
            for _, item in chunk
        ]
        # requireSuccess=False: one misbehaving token must not hide the rest.
        data = SEL_TRY_AGGREGATE + encode(['bool', '(address,bytes)[]'], [False, calls])
        res = vault._rpc('eth_call', [{'to': MULTICALL3, 'data': '0x' + data.hex()}, block_tag])
        results = decode(['(bool,bytes)[]'], bytes.fromhex(res[2:]))[0]
        if require_complete and len(results) != len(chunk):
            raise RuntimeError('GM Multicall returned an incomplete result set')
        for (ok, ret), (symbol, item) in zip(results, chunk):
            if not ok or len(ret) < 32:
                if require_complete:
                    raise RuntimeError(f'GM balanceOf failed for {symbol}')
                continue
            raw = int.from_bytes(ret[:32], 'big')
            if raw:
                held[symbol] = float(Decimal(raw) / Decimal(10) ** item.get('decimals', 18))
    return held


def holdings_units(user_bsc_address: str) -> dict | None:
    """{symbol: units} for everything the address holds; {} when it holds
    nothing (or the registry is empty). None means UNKNOWN — the scan
    failed and no last-known value exists; callers must not render that
    as an empty portfolio."""
    if not user_bsc_address:
        return {}
    key = user_bsc_address.lower()
    cached = cache.get(f'gm_hold:{key}')
    if cached is not None:
        return cached
    token_registry = registry()
    if token_registry is None:
        return cache.get(f'gm_hold_last:{user_bsc_address.lower()}')
    if not token_registry:
        return {}
    try:
        held = _scan(key, token_registry)
    except Exception:  # noqa: BLE001 — degrade to stale, never to vanished
        logger.warning('GM holdings scan failed for %s', user_bsc_address, exc_info=True)
        return cache.get(f'gm_hold_last:{key}')
    cache.set(f'gm_hold:{key}', held, SCAN_TTL)
    cache.set(f'gm_hold_last:{key}', held, SCAN_LAST_TTL)
    return held
