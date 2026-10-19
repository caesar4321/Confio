"""A wallet's crypto & metals balances (the catalog in crypto_tokens.json).

The small sibling of gm_holdings.py. The catalog is a few dozen tokens at
most, so a read is ONE Multicall3 call that must answer for every token
(complete or nothing). Same safety rules as stocks:
- a scan is stored (CryptoHoldings) only if no swap of the wallet is on the
  wire and no node behind the wallet's last confirmed swap served it;
- invalidation after a swap moves a generation, so a scan that read the
  pre-trade chain is never stored;
- unknown is None, never an empty portfolio.

Balances are kept in exact base units (strings): BTC positions of a few
dollars are 1e-5 BTC and must not be rounded through floats.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from uuid import uuid4

from django.core.cache import cache
from django.utils import timezone
from eth_abi import decode, encode

from . import vault
from .crypto_catalog import tokens
from .gm_holdings import MULTICALL3, SEL_BALANCE_OF, SEL_GET_BLOCK_NUMBER, SEL_TRY_AGGREGATE

logger = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=2)
FLOOR_TTL = 10 * 60
GEN_TTL = 7 * 24 * 3600
# A sponsored intent can stay executable for up to 30 minutes (deadline cap
# in SponsorBscBatch); until then an unresolved swap may still land.
IN_FLIGHT_MAX_AGE = timedelta(minutes=35)


def _key(address: str) -> str:
    return (address or '').lower()


def _scan(address: str) -> tuple[dict, int | None]:
    """({symbol: units_str} nonzero, block) for EVERY catalog token, delisted
    entries included so a held position never vanishes. Raises unless every
    balanceOf answered."""
    universe = tokens(include_unlisted=True)
    holder = encode(['address'], [address])
    calls = [(MULTICALL3, SEL_GET_BLOCK_NUMBER)] + [
        (t.address, SEL_BALANCE_OF + holder) for t in universe
    ]
    data = SEL_TRY_AGGREGATE + encode(['bool', '(address,bytes)[]'], [False, calls])
    res = vault._rpc('eth_call', [{'to': MULTICALL3, 'data': '0x' + data.hex()}, 'latest'])
    results = decode(['(bool,bytes)[]'], bytes.fromhex(res[2:]))[0]
    if len(results) != len(calls):
        raise RuntimeError('crypto Multicall returned an incomplete result set')
    head, rest = results[0], results[1:]
    block = int.from_bytes(head[1][:32], 'big') if head[0] and len(head[1]) >= 32 else None
    held = {}
    for (ok, ret), token in zip(rest, universe):
        if not ok or len(ret) < 32:
            raise RuntimeError(f'crypto balanceOf failed for {token.symbol}')
        raw = int.from_bytes(ret[:32], 'big')
        if raw:
            held[token.symbol] = str(raw)
    return held, block


def batches_in_flight(address: str):
    from blockchain.models import CRYPTO_BATCH_KINDS, SponsoredBatch

    return SponsoredBatch.objects.filter(
        user_bsc_address__iexact=address, kind__in=CRYPTO_BATCH_KINDS,
        status__in=('signed', 'sent'), created_at__gte=timezone.now() - IN_FLIGHT_MAX_AGE)


def _generation(key: str):
    return cache.get(f'crypto_hold_gen:{key}')


def invalidate_holdings(address: str, min_block: int | None = None) -> None:
    """After a swap (broadcast or confirmation): the stored row is stale,
    any scan already running is not storable, and with `min_block` no read
    from a node behind that block is stored either."""
    from blockchain.models import CryptoHoldings

    key = _key(address)
    try:
        if min_block is not None:
            from blockchain.bsc_balance_service import raise_floor
            raise_floor(f'crypto_hold_floor:{key}', int(min_block), FLOOR_TTL)
        cache.set(f'crypto_hold_gen:{key}', uuid4().hex, GEN_TTL)
    finally:
        # The durable mark lands even when Redis is down.
        CryptoHoldings.objects.filter(bsc_address=key).update(is_stale=True)


def _storable(key: str, generation, block: int | None) -> bool:
    if _generation(key) != generation:
        return False
    floor = cache.get(f'crypto_hold_floor:{key}')
    if floor and (block is None or block < int(floor)):
        return False
    try:
        return not batches_in_flight(key).exists()
    except Exception:  # noqa: BLE001 — unknown: serve, don't store
        logger.warning('crypto in-flight check failed for %s', key, exc_info=True)
        return False


def holdings_units(address: str) -> dict | None:
    """{symbol: base units (int)} the wallet holds; {} when nothing; None
    when UNKNOWN (scan failed and no stored row)."""
    from blockchain.models import CryptoHoldings

    if not address:
        return {}
    key = _key(address)
    row = CryptoHoldings.objects.filter(bsc_address=key).first()
    if row is not None and not row.is_stale and timezone.now() - row.scanned_at <= STALE_AFTER:
        return {s: int(u) for s, u in row.held.items()}
    generation = _generation(key)
    try:
        held, block = _scan(key)
    except Exception:  # noqa: BLE001 — degrade to last-known, never to vanished
        logger.warning('crypto holdings scan failed for %s', key, exc_info=True)
        return {s: int(u) for s, u in row.held.items()} if row is not None else None
    if _storable(key, generation, block):
        blocks = {symbol: block for symbol in held}
        CryptoHoldings.objects.update_or_create(
            bsc_address=key,
            defaults={'held': held, 'blocks': blocks, 'scanned_at': timezone.now(), 'is_stale': False},
        )
        # An invalidation between the check and the write must win: if the
        # generation moved meanwhile, this pre-trade read is stale.
        if _generation(key) != generation:
            CryptoHoldings.objects.filter(bsc_address=key).update(is_stale=True)
    return {s: int(u) for s, u in held.items()}
