"""Community stock trading, for "Acciones en movimiento".

Public aggregates over every confirmed Confío stock trade: buys and sales
in dollars and counts (each trade's exact settlement, its unified history
row), how many people trade, a typical purchase, and the most traded
stocks. The same numbers Home's Acciones tile sums, broken down.

Privacy: every stated figure has at least MIN_TRADERS distinct wallets
behind it (the holdings block's floor): the whole snapshot, each side of
the buy/sale split (else the split is withheld, since one side would be
the total minus the other), the typical purchase, and each ranked stock.

Two scopes (2026-10-19): 'stocks' (what store builds' Acciones tile and
screen show) and 'all' (stocks + Bitcoin & gold, the new Inversiones tile
and Inversiones en movimiento). Each scope's snapshot serves both Home's
tile (gm_volume) and its breakdown, so they never disagree. It is rebuilt only when a confirmed stock trade was
added or changed (a cheap signature query), at most every FRESH_FOR, by
one worker at a time; others keep serving the last snapshot.
"""
import logging
import statistics
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from django.core.cache import cache

logger = logging.getLogger(__name__)

STOCK_KINDS = ('stock_buy', 'stock_sell')
CRYPTO_KINDS = ('crypto_buy', 'crypto_sell')
SCOPES = {'stocks': STOCK_KINDS, 'all': STOCK_KINDS + CRYPTO_KINDS}
CACHE_KEY = 'gm_trading_stats_v2'
CACHE_TTL = 24 * 3600          # the last snapshot, served while a refresh runs
FRESH_KEY = 'gm_trading_stats_fresh_v2'
FRESH_FOR = 300                # how often the signature is re-checked
LOCK_KEY = 'gm_trading_stats_lock_v2'


def _key(base: str, scope: str) -> str:
    # 'stocks' keeps the pre-scope keys so a deploy reuses the warm snapshot.
    return base if scope == 'stocks' else f'{base}_{scope}'
LOCK_FOR = 300
# Rebuilt at least this often even when no trade changed: a ranking built
# while the market registry was unreachable must not outlive the outage.
MAX_AGE = 3600
MIN_TRADERS = 3
MIN_BUYS_FOR_MEDIAN = 10
TOP_LIMIT = 8


@dataclass
class TopAsset:
    symbol: str
    ticker: str
    name: str
    trade_count: int
    trader_count: int
    kind: str = 'stock'  # 'stock' | 'crypto': which detail screen a row opens


@dataclass
class TradingStats:
    total_usd: float
    # Withheld (None) unless BOTH sides have MIN_TRADERS distinct wallets.
    buy_usd: float | None
    sell_usd: float | None
    buy_count: int
    sell_count: int
    trader_count: int
    median_buy_usd: float | None
    since: object | None
    top_assets: list = field(default_factory=list)
    computed_at: float = 0.0
    # Distinct wallets behind the crypto part of scope 'all'. Its total
    # minus the stock-only total IS the crypto volume, so 'all' is stated
    # only when that part has MIN_TRADERS wallets too (or none at all).
    crypto_trader_count: int = 0


def _dec(value) -> Decimal | None:
    from decimal import InvalidOperation

    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return d if d.is_finite() else None


def _names() -> dict:
    try:
        from . import gm_api

        out = {}
        for item in gm_api.all_market():
            pm = item.get('primaryMarket') or {}
            um = item.get('underlyingMarket') or {}
            symbol = pm.get('symbol')
            if symbol:
                ticker = um.get('ticker') or symbol.removesuffix('on')
                out[symbol] = (ticker, um.get('name') or ticker)
        return out
    except Exception:  # noqa: BLE001 — names are cosmetic
        logger.warning('gm trading stats: market names unavailable')
        return {}


def _crypto_names() -> dict:
    from . import crypto_catalog

    return {t.symbol: (t.ticker, t.name) for t in crypto_catalog.tokens(include_unlisted=True)}


def _symbols(batches) -> list:
    """Each batch's asset symbol ('?…' when unknown). Stock routes are
    decoded from the router call; crypto trades carry theirs in CryptoTrade."""
    from .stock_month import _decode_trades

    stock = [b for b in batches if b.kind in STOCK_KINDS]
    decoded = {b.id: t.symbol for b, t in zip(stock, _decode_trades(stock))}
    out = []
    for b in batches:
        if b.kind in STOCK_KINDS:
            out.append(decoded.get(b.id, '?'))
        else:
            trade = getattr(b, 'crypto_trade', None)
            out.append(trade.symbol if trade is not None else '?')
    return out


def compute(scope: str = 'stocks') -> TradingStats:
    from blockchain.models import SponsoredBatch

    kinds = SCOPES[scope]
    related = ('unified_transaction', 'crypto_trade') if scope != 'stocks' else ('unified_transaction',)
    batches = list(
        SponsoredBatch.objects.filter(kind__in=kinds, status='confirmed')
        .select_related(*related).order_by('created_at', 'id')
    )
    symbols = _symbols(batches)
    buy_usd = sell_usd = Decimal('0')
    buy_count = sell_count = 0
    buys = []
    wallets = set()
    buy_wallets = set()
    sell_wallets = set()
    per_asset: dict[str, dict] = {}
    crypto_wallets = set()
    since = None
    for batch, symbol in zip(batches, symbols):
        # Dollars from the settled history row itself, exactly what Home's
        # tile sums (gm_volume), even when the router call can't be decoded.
        row = getattr(batch, 'unified_transaction', None)
        usd = _dec(row.amount) if row is not None and row.deleted_at is None else None
        if usd is None:
            continue  # hidden or missing: not volume
        wallet = batch.user_bsc_address.lower()
        wallets.add(wallet)
        if batch.kind in CRYPTO_KINDS:
            crypto_wallets.add(wallet)
        since = since or batch.created_at
        if batch.kind.endswith('_buy'):
            buy_usd += usd
            buy_count += 1
            buys.append(usd)
            buy_wallets.add(wallet)
        else:
            sell_usd += usd
            sell_count += 1
            sell_wallets.add(wallet)
        if symbol.startswith('?'):
            continue  # undecodable: counted above, not ranked
        asset = per_asset.setdefault(symbol, {'count': 0, 'usd': Decimal('0'), 'wallets': set(),
                                              'kind': 'crypto' if batch.kind in CRYPTO_KINDS else 'stock'})
        asset['count'] += 1
        asset['usd'] += usd
        asset['wallets'].add(wallet)

    names = _names()
    crypto_names = _crypto_names() if scope != 'stocks' else {}
    ranked = sorted(
        (item for item in per_asset.items() if len(item[1]['wallets']) >= MIN_TRADERS),
        key=lambda item: (item[1]['count'], item[1]['usd']), reverse=True,
    )[:TOP_LIMIT]
    top = []
    for symbol, data in ranked:
        if data['kind'] == 'crypto':
            ticker, name = crypto_names.get(symbol, (symbol, symbol))
        else:
            ticker, name = names.get(symbol, (symbol.removesuffix('on'), symbol.removesuffix('on')))
        # Counts only: per-stock dollars would let anyone subtract their way
        # to the volume of a stock withheld below the floor.
        top.append(TopAsset(symbol=symbol, ticker=ticker, name=name, trade_count=data['count'],
                            trader_count=len(data['wallets']), kind=data['kind']))
    split_ok = len(buy_wallets) >= MIN_TRADERS and len(sell_wallets) >= MIN_TRADERS
    median = (float(statistics.median(buys))
              if len(buys) >= MIN_BUYS_FOR_MEDIAN and len(buy_wallets) >= MIN_TRADERS else None)
    return TradingStats(
        total_usd=float(buy_usd + sell_usd),
        buy_usd=float(buy_usd) if split_ok else None,
        sell_usd=float(sell_usd) if split_ok else None,
        buy_count=buy_count, sell_count=sell_count, trader_count=len(wallets),
        median_buy_usd=median, since=since, top_assets=top, computed_at=time.time(),
        crypto_trader_count=len(crypto_wallets),
    )


def publishable(stats: TradingStats | None, scope: str = 'stocks') -> bool:
    """May this snapshot's figures be stated at all? Never for one or two
    people: neither the whole, nor (scope 'all') the crypto part that the
    difference with the stock-only scope would reveal."""
    if stats is None or stats.trader_count < MIN_TRADERS:
        return False
    if scope != 'stocks' and 0 < getattr(stats, 'crypto_trader_count', 0) < MIN_TRADERS:
        return False
    return True


def _signature(scope: str = 'stocks'):
    """Changes whenever a confirmed trade in scope is added, edited, or its
    history row is added, re-synced or hidden."""
    from django.db.models import Count, Max, Q

    from blockchain.models import SponsoredBatch

    sig = SponsoredBatch.objects.filter(kind__in=SCOPES[scope], status='confirmed').aggregate(
        n=Count('id'), last=Max('id'), touched=Max('updated_at'),
        rows=Count('unified_transaction', filter=Q(unified_transaction__deleted_at__isnull=True)),
        rows_touched=Max('unified_transaction__updated_at'))
    stamp = lambda v: v.timestamp() if v else 0  # noqa: E731
    return (sig['n'], sig['last'], stamp(sig['touched']), sig['rows'], stamp(sig['rows_touched']))


def snapshot(scope: str = 'stocks') -> TradingStats | None:
    """The shared snapshot, unfiltered by the trader floor (Home's tile
    needs the total even below it); None when it can't be read."""
    cache_key, fresh_key, lock_key = (_key(k, scope) for k in (CACHE_KEY, FRESH_KEY, LOCK_KEY))
    cached = cache.get(cache_key)  # (signature, stats)
    if cached is not None and cache.get(fresh_key):
        return cached[1]
    token = uuid.uuid4().hex
    if not cache.add(lock_key, token, LOCK_FOR):
        # Another worker is building it: serve the last snapshot, or (cold)
        # nothing for a moment rather than a second full scan.
        return cached[1] if cached is not None else None
    try:
        sig = _signature(scope)
        if (cached is not None and cached[0] == sig
                and time.time() - cached[1].computed_at < MAX_AGE):
            stats = cached[1]  # nothing changed: no decoding
        else:
            stats = compute(scope)
        cache.set(cache_key, (sig, stats), CACHE_TTL)
        cache.set(fresh_key, 1, FRESH_FOR)
        return stats
    except Exception:  # noqa: BLE001
        logger.exception('gm trading stats unreadable')
        return cached[1] if cached is not None else None
    finally:
        # Only our own lock: a build that outlived LOCK_FOR must not release
        # the next holder's.
        if cache.get(lock_key) == token:
            cache.delete(lock_key)


def trading_stats(scope: str = 'stocks') -> TradingStats | None:
    """The public breakdown: None until MIN_TRADERS distinct wallets have
    traded, so even the total never describes one or two people."""
    stats = snapshot(scope)
    return stats if publishable(stats, scope) else None
