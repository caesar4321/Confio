"""
Ondo GM (tokenized stock) holdings — universe scan, no per-user bookkeeping.

Design (locked with Julian 2026-07-10, replacing a per-account holdings
model): the ONLY durable state is a system-wide token registry
(gm_tokens.json: symbol -> {address, decimals}, one entry per GM asset).
A user's portfolio is discovered by scanning the whole registry against
their address with Multicall3 — every balanceOf in ONE eth_call — so the
chain stays the single source of truth and nothing can go invisible
because a row wasn't created. No DB model, no sync jobs.

Freshness mirrors vault.position_usd: 30s fresh cache per address, 7-day
last-known fallback so a dead node degrades to a stale portfolio, never a
vanished one. USD values are never stored — the resolver computes them
from the globally cached GM market payload (display only, chain-first).

The registry ships empty until Ondo's trading-integration docs (PP-gated)
give us the contract addresses — the display API doesn't expose them
(probed 2026-07-10). Empty registry = empty portfolio, honestly.
"""
import json
import logging
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

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


@lru_cache(maxsize=1)
def registry() -> dict:
    """symbol -> {'address': '0x…', 'decimals': int} for the GM universe."""
    path = Path(__file__).parent / 'gm_tokens.json'
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def _scan(user_bsc_address: str) -> dict:
    """One Multicall3 pass over the whole registry; returns nonzero
    balances as {symbol: units_float}. Raises on RPC failure."""
    entries = list(registry().items())
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
        res = vault._rpc('eth_call', [{'to': MULTICALL3, 'data': '0x' + data.hex()}, 'latest'])
        results = decode(['(bool,bytes)[]'], bytes.fromhex(res[2:]))[0]
        for (ok, ret), (symbol, item) in zip(results, chunk):
            if not ok or len(ret) < 32:
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
    if not registry():
        return {}
    key = user_bsc_address.lower()
    cached = cache.get(f'gm_hold:{key}')
    if cached is not None:
        return cached
    try:
        held = _scan(key)
    except Exception:  # noqa: BLE001 — degrade to stale, never to vanished
        logger.warning('GM holdings scan failed for %s', user_bsc_address, exc_info=True)
        return cache.get(f'gm_hold_last:{key}')
    cache.set(f'gm_hold:{key}', held, SCAN_TTL)
    cache.set(f'gm_hold_last:{key}', held, SCAN_LAST_TTL)
    return held
