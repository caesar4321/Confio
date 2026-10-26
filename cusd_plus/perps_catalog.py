"""Futuros market catalog, synced from Hyperliquid.

Hyperliquid decides what is listed: every core perp and every market of a
HIP-3 dex whose collateral is USDC (the only token the Relay route
delivers). There is no volume floor; thin books are handled per order by the
price-impact check. Ops removes a broken market with PERPS_EXCLUDED_MARKETS.
`perps_markets.json` only adds Spanish names and asset classes.

Rows are kept after a delisting (listed=False) so an open position can
always be closed.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import hyperliquid

logger = logging.getLogger(__name__)

ASSET_CLASSES = ('crypto', 'stock', 'index', 'commodity', 'fx')
TRADABLE_COLLATERAL = 'USDC'
HIP3_ASSET_OFFSET = 100_000
HIP3_DEX_STRIDE = 10_000
_OVERLAY_PATH = Path(__file__).with_name('perps_markets.json')


@lru_cache(maxsize=1)
def _overlay() -> dict:
    markets = json.loads(_OVERLAY_PATH.read_text())['markets']
    for coin, entry in markets.items():
        if entry.get('asset_class', 'crypto') not in ASSET_CLASSES:
            raise ValueError(f'{coin}: unknown asset_class')
    return markets


def asset_id(dex_position: int, index: int) -> int:
    """Hyperliquid order asset id: core = universe index; HIP-3 = 100000 +
    position in perpDexs * 10000 + index."""
    if dex_position == 0:
        return index
    return HIP3_ASSET_OFFSET + dex_position * HIP3_DEX_STRIDE + index


def excluded_markets() -> frozenset:
    raw = getattr(settings, 'PERPS_EXCLUDED_MARKETS', '') or ''
    if isinstance(raw, str):
        raw = raw.split(',')
    return frozenset(str(m).strip() for m in raw if str(m).strip())


@dataclass(frozen=True)
class MarketView:
    coin: str
    dex: str
    ticker: str
    name: str
    asset_class: str
    asset_id: int
    sz_decimals: int
    max_leverage: int
    only_isolated: bool
    openable: bool
    taker_fee_rate: Decimal


def ticker_of(coin: str) -> str:
    return coin.split(':', 1)[1] if ':' in coin else coin


def view(market) -> MarketView:
    """Display + trading facts of one PerpMarket row."""
    extra = _overlay().get(market.coin, {})
    default_class = 'crypto' if not market.dex else 'stock'
    ticker = ticker_of(market.coin)
    return MarketView(
        coin=market.coin,
        dex=market.dex,
        ticker=ticker,
        name=extra.get('name') or ticker,
        asset_class=extra.get('asset_class') or default_class,
        asset_id=market.asset_id,
        sz_decimals=market.sz_decimals,
        max_leverage=market.max_leverage,
        only_isolated=market.only_isolated,
        openable=is_openable(market),
        taker_fee_rate=market.taker_fee_rate,
    )


def is_openable(market) -> bool:
    return bool(
        market.listed
        and market.collateral == TRADABLE_COLLATERAL
        and market.max_leverage >= 1
        and market.coin not in excluded_markets()
    )


def markets(*, openable_only: bool = True) -> list[MarketView]:
    from blockchain.models import PerpMarket

    rows = PerpMarket.objects.all().order_by('dex', 'asset_id')
    views = [view(m) for m in rows]
    return [v for v in views if v.openable] if openable_only else views


def by_coin(coin: str):
    from blockchain.models import PerpMarket

    return PerpMarket.objects.filter(coin=coin).first()


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


BASE_TAKER_RATE = Decimal('0.00045')  # tier 0, validator-operated perps


def _taker_fee_rate(entry: dict, dex: str) -> Decimal:
    """Tier-0 taker rate. HIP-3: deployer scale s multiplies the base by
    (s + 1) below 1 and by 2s from 1 up; growth mode cuts it by 90%."""
    if not dex:
        return BASE_TAKER_RATE
    raw = entry.get('deployerFeeScale', '1')
    if not isinstance(raw, str):
        raise hyperliquid.HyperliquidError('hyperliquid_bad_universe')
    try:
        scale = Decimal(raw)
    except ArithmeticError as exc:
        raise hyperliquid.HyperliquidError('hyperliquid_bad_universe') from exc
    if not scale.is_finite() or not 0 <= scale <= 10:
        raise hyperliquid.HyperliquidError('hyperliquid_bad_universe')
    rate = BASE_TAKER_RATE * ((scale + 1) if scale < 1 else (scale * 2))
    if entry.get('growthMode') == 'enabled':
        rate = rate / 10
    return rate.quantize(Decimal('0.00000001'))


def _parse_universe(entries: list, dex: str, dex_position: int, collateral: str, now) -> dict[str, dict]:
    out = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get('name'), str):
            raise hyperliquid.HyperliquidError('hyperliquid_bad_universe')
        coin = entry['name']
        if dex and not coin.startswith(f'{dex}:'):
            raise hyperliquid.HyperliquidError('hyperliquid_bad_universe')
        # Exact types only: coercing a malformed field ("false", 3.9) could
        # turn a bad read into a delisting or a wrong order size.
        sz, lev = entry.get('szDecimals'), entry.get('maxLeverage')
        flags = (entry.get('isDelisted', False), entry.get('onlyIsolated', False))
        if (not _is_int(sz) or not _is_int(lev) or not 0 <= sz <= 12 or not 0 <= lev <= 1000
                or not all(isinstance(flag, bool) for flag in flags)):
            raise hyperliquid.HyperliquidError('hyperliquid_bad_universe')
        out[coin] = {
            'taker_fee_rate': _taker_fee_rate(entry, dex),
            'dex': dex,
            # The index is the position in the universe, delisted entries included.
            'asset_id': asset_id(dex_position, index),
            'sz_decimals': sz,
            'max_leverage': lev,
            'only_isolated': flags[1],
            'collateral': collateral,
            'listed': not flags[0],
            'synced_at': now,
        }
    return out


def _collateral(tokens: dict[int, str], meta: dict) -> str:
    """The dex's collateral token name. An index missing from spotMeta is
    an unreadable answer, not a non-USDC dex: abort rather than delist."""
    index = meta.get('collateralToken')
    if not _is_int(index):
        raise hyperliquid.HyperliquidError('hyperliquid_bad_collateral')
    if index not in tokens:
        raise hyperliquid.HyperliquidError('hyperliquid_unknown_collateral')
    return tokens[index]


def sync_markets(*, session=None) -> dict:
    """Pull core + every USDC HIP-3 dex and upsert PerpMarket.

    Hyperliquid's universes are append-only: a delisted market stays at its
    index with isDelisted, so asset ids never move. The sync relies on that
    and treats any answer breaking it (a known market missing, an asset id
    changing, a dex vanishing) as a bad read and aborts before writing,
    never as a delisting. The only delistings are isDelisted flags and a dex
    whose collateral is confirmed to be no longer USDC."""
    from blockchain.models import PerpMarket

    now = timezone.now()
    tokens = hyperliquid.spot_token_names(session=session)
    seen: dict[str, dict] = {}
    non_usdc_dexs: set[str] = set()
    read_dexs: set[str] = {''}

    core = hyperliquid.meta('', session=session)
    core_collateral = _collateral(tokens, core)
    if core_collateral != TRADABLE_COLLATERAL:
        raise hyperliquid.HyperliquidError('hyperliquid_bad_collateral')  # core is always USDC
    seen.update(_parse_universe(core['universe'], '', 0, core_collateral, now))

    dexs = hyperliquid.info({'type': 'perpDexs'}, session=session)
    # Entry 0 is always core (null): without it every position, and so every
    # HIP-3 asset id, would shift.
    if not isinstance(dexs, list) or not dexs or dexs[0] is not None:
        raise hyperliquid.HyperliquidError('hyperliquid_bad_perp_dexs')
    for position, dex in enumerate(dexs):
        if position == 0:
            continue
        name = dex.get('name') if isinstance(dex, dict) else None
        if not isinstance(name, str) or not name or name in read_dexs:
            raise hyperliquid.HyperliquidError('hyperliquid_bad_perp_dexs')
        read_dexs.add(name)
        meta = hyperliquid.meta(name, session=session)
        collateral = _collateral(tokens, meta)
        if collateral != TRADABLE_COLLATERAL:
            non_usdc_dexs.add(name)
            continue
        seen.update(_parse_universe(meta['universe'], name, position, collateral, now))

    created = updated = delisted = 0
    with transaction.atomic():
        existing = {m.coin: m for m in PerpMarket.objects.select_for_update()}
        # Validate the whole snapshot against what we know before any write.
        for coin, row in existing.items():
            fields = seen.get(coin)
            if fields is None:
                if row.dex in non_usdc_dexs:
                    continue  # confirmed collateral change: delisted below
                logger.error('perps sync aborted: known market %s missing from Hyperliquid', coin)
                raise hyperliquid.HyperliquidError('hyperliquid_market_missing')
            if fields['asset_id'] != row.asset_id or fields['dex'] != row.dex:
                logger.error('perps sync aborted: %s asset id %s -> %s', coin, row.asset_id, fields['asset_id'])
                raise hyperliquid.HyperliquidError('hyperliquid_asset_id_changed')
        for coin, fields in seen.items():
            row = existing.get(coin)
            if row is None:
                PerpMarket.objects.create(coin=coin, first_seen_at=now, **fields)
                created += 1
                continue
            for key, value in fields.items():
                setattr(row, key, value)
            row.save()
            updated += 1
        for coin, row in existing.items():
            if coin not in seen and row.listed:
                # Its dex no longer uses USDC: not openable, still closeable.
                row.listed = False
                row.synced_at = now
                row.save(update_fields=['listed', 'synced_at'])
                delisted += 1
    logger.info('perps markets synced: %s new, %s updated, %s delisted', created, updated, delisted)
    return {'created': created, 'updated': updated, 'delisted': delisted}
