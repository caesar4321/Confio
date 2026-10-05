"""Tu mes "Tus acciones": what the account's U.S. stocks did in one month.

    gain = value at month end − value at month start − bought + sold

Buys and sells are the exact settlements of Confío's own trades (the unified
row each confirmed stock batch owns), so putting money in never reads as a
gain and taking it out never reads as a loss. Units at any instant come from
the same ledger (the signed quote quantity of each trade); prices are Ondo's
own: the live market for "today", daily OHLC closes for a month boundary.
GM tokens are total-return (dividends reinvest into the price), so units
only change through trades and the price carries every return.

The ledger is trusted only when it explains the chain: every symbol's
all-time ledger units must match the wallet's live balance. A position that
arrived from (or left to) outside Confío breaks that, and the month gain is
then unknowable: the current month degrades to 'value_only' (today's value,
no gain) and a past month to None. Any missing price, scan or settlement is
None too — the card hides, never a guessed number.
"""
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

WAD = Decimal(10) ** 18
DAY_MS = 24 * 3600 * 1000
# A boundary price may come from the last close up to a week back (weekends,
# U.S. holidays, a halt) — never older.
PRICE_LOOKBACK = timedelta(days=7)
# Daily candles reach back one year ('1Y'); older months have no price.
OHLC_RANGE = '1Y'
UNITS_TOLERANCE = Decimal('0.000001')        # relative, ledger vs chain
# The receipt checker gives up after ~9 minutes (5×3s + 35×15s retries):
# past this a batch still 'signed'/'sent' is stuck (ops reconciles it), not
# settling, so it can't hold every card on "se está confirmando".
PENDING_MAX_AGE = timedelta(minutes=15)


class StockMonthUnavailable(Exception):
    """Something needed is unknown: hide the card."""


@dataclass
class Trade:
    symbol: str
    kind: str              # stock_buy | stock_sell
    units: Decimal
    usd: Decimal | None    # exact settlement; None when its history row is missing
    when: datetime


@dataclass
class Mover:
    ticker: str
    name: str
    change_pct: Decimal    # price change over the viewed month (start → end)


@dataclass
class StockMonth:
    state: str                         # 'gain' | 'value_only' | 'settling' | 'none'
    value_end: Decimal = Decimal('0')
    value_start: Decimal | None = None
    bought: Decimal | None = None
    sold: Decimal | None = None
    gain: Decimal | None = None
    gain_pct: Decimal | None = None    # gain / (value at start + bought)
    top: Mover | None = None
    holdings: int = 0                  # positions held at the end of the window


def _dec(value) -> Decimal | None:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return d if d.is_finite() else None


def _symbol_by_address() -> dict:
    from .gm_holdings import _fallback_registry, registry
    out = {}
    for source in (_fallback_registry() or {}, registry() or {}):
        for symbol, meta in source.items():
            address = str(meta.get('address') or '').lower()
            if address:
                out[address] = symbol
    return out


def confirmed_trades(bsc_address: str) -> list[Trade]:
    """Every confirmed Confío stock trade of this wallet, oldest first."""
    from django.core.cache import cache
    from django.db.models import Count, Max, Q
    from blockchain.models import SponsoredBatch

    confirmed = SponsoredBatch.objects.filter(
        user_bsc_address__iexact=bsc_address, kind__in=('stock_buy', 'stock_sell'), status='confirmed')
    # One cheap aggregate decides whether the decoded ledger is still valid:
    # a new confirmation, a batch edit, a history row added, re-synced (its
    # exact amount) or hidden all change this key. Unchanged → no decoding.
    sig = confirmed.aggregate(
        n=Count('id'), last=Max('id'), touched=Max('updated_at'),
        rows=Count('unified_transaction', filter=Q(unified_transaction__deleted_at__isnull=True)),
        rows_touched=Max('unified_transaction__updated_at'))
    if not sig['n']:
        return []
    stamp = lambda v: v.timestamp() if v else 0  # noqa: E731
    key = (f'gm_trades_v1:{bsc_address.lower()}:{sig["n"]}:{sig["last"]}:{stamp(sig["touched"])}:'
           f'{sig["rows"]}:{stamp(sig["rows_touched"])}')
    cached = cache.get(key)
    if cached is not None:
        return cached
    trades = _decode_trades(confirmed.select_related('unified_transaction').order_by('created_at', 'id'))
    if not any(t.symbol.startswith('?') for t in trades):
        # An unreadable trade may become readable (registry update): re-read it.
        cache.set(key, trades, 24 * 3600)
    return trades


def _decode_trades(batches) -> list[Trade]:
    from .sponsor_7702 import _decode_stock_call

    by_address = _symbol_by_address()
    trades = []
    for batch in batches:
        try:
            actions = [a for call in json.loads(batch.calls_json or '[]')
                       if (a := _decode_stock_call(call, historical=True)) is not None]
        except Exception:  # noqa: BLE001 — e.g. a retired router: unknown, not fatal
            actions = []
        symbol = by_address.get(actions[0]['asset']) if len(actions) == 1 else None
        if symbol is None or actions[0]['kind'] != batch.kind:
            # A trade we can't read: its units and dollars are unknown, so the
            # ledger can no longer explain the chain (value only, never a gain).
            logger.warning('stock month: unreadable stock batch %s', batch.id)
            trades.append(Trade(symbol=f'?{batch.id}', kind=batch.kind, units=Decimal('0'), usd=None,
                                when=batch.created_at))
            continue
        action = actions[0]
        row = getattr(batch, 'unified_transaction', None)
        usd = _dec(row.amount) if row is not None and row.deleted_at is None else None
        trades.append(Trade(symbol=symbol, kind=batch.kind, units=Decimal(action['quantity']) / WAD,
                            usd=usd, when=batch.created_at))
    return trades


def pending_trades(bsc_address: str) -> list[Trade]:
    """Confío trades on the wire but not final yet, decoded (units from the
    signed quote; no settlement yet). The client shows success on the
    receipt, before finality marks the batch confirmed, so in that window the
    chain may or may not hold the units while the ledger does not."""
    from django.utils import timezone as dj_tz
    from blockchain.models import SponsoredBatch
    return _decode_trades(SponsoredBatch.objects.filter(
        user_bsc_address__iexact=bsc_address, kind__in=('stock_buy', 'stock_sell'),
        status__in=('signed', 'sent'), created_at__gte=dj_tz.now() - PENDING_MAX_AGE,
    ).select_related('unified_transaction').order_by('created_at', 'id'))


def ledger_units(trades: list[Trade], before: datetime | None = None) -> dict:
    """{symbol: units} the ledger says the wallet held at `before` (all time when None)."""
    units: dict[str, Decimal] = {}
    for t in trades:
        if before is not None and t.when >= before:
            continue
        sign = 1 if t.kind == 'stock_buy' else -1
        units[t.symbol] = units.get(t.symbol, Decimal('0')) + sign * t.units
    return {s: u for s, u in units.items() if u != 0}


def ledger_explains_chain(ledger: dict, chain: dict) -> bool:
    for symbol in set(ledger) | set(chain):
        a, b = ledger.get(symbol, Decimal('0')), chain.get(symbol, Decimal('0'))
        if a < 0:
            return False
        if abs(a - b) > max(abs(a), abs(b)) * UNITS_TOLERANCE:
            return False
    return True


def close_before(symbol: str, when: datetime) -> Decimal | None:
    """The last daily close at or before `when` (within PRICE_LOOKBACK).
    A boundary more than a day old never changes: cached for hours, so Tu mes
    reads one cache entry instead of a year of candles per position."""
    from django.core.cache import cache
    from django.utils import timezone as dj_tz
    key = f'gm_close_v1:{symbol}:{int(when.timestamp())}'
    cached = cache.get(key)
    if cached is not None:
        return _dec(cached)
    try:
        price = _close_from_candles(symbol, when)
    except Exception:  # noqa: BLE001 — an Ondo/network failure is a missing price
        logger.warning('stock month: candles unavailable for %s', symbol, exc_info=True)
        return None
    if price is not None and dj_tz.now() - when > timedelta(days=1):
        cache.set(key, str(price), 6 * 3600)
    return price


def _close_from_candles(symbol: str, when: datetime) -> Decimal | None:
    from . import gm_api
    cutoff_ms = when.timestamp() * 1000
    best = None
    for c in gm_api.ohlc(symbol, OHLC_RANGE) or []:
        ts = float(c.get('timestamp') or 0)
        if ts and ts < 1e12:
            ts *= 1000                      # seconds → ms
        closed_at = ts + DAY_MS
        if closed_at <= cutoff_ms and (best is None or closed_at > best[0]):
            best = (closed_at, c.get('close'))
    if best is None or cutoff_ms - best[0] > PRICE_LOOKBACK.total_seconds() * 1000:
        return None
    price = _dec(best[1])
    return price if price is not None and price > 0 else None


_POOL = None
_POOL_LOCK = threading.Lock()


def _pool():
    """One long-lived pool per process: its threads keep their thread-local
    RPC keep-alive sessions (tasks._rpc_session) across requests, where a
    per-call pool's fresh threads would open a new TLS connection every time.
    Created lazily, so no thread exists before a pre-fork server forks."""
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:               # two first requests at once: still one pool
            if _POOL is None:
                from concurrent.futures import ThreadPoolExecutor
                _POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix='stock-month')
    return _POOL


def _prefetch(prices: dict, pairs: set) -> None:
    """Fill `prices` for every (symbol, boundary) at once: one Ondo candle
    request per symbol in parallel instead of one after another, so a cold
    cache still fits Tu mes's reveal window. A symbol's boundaries (a past
    month's start and end) share one task, so its candles are fetched once
    (the second read hits gm_api's cache) instead of twice concurrently."""
    by_symbol: dict = {}
    for symbol, when in pairs:
        if (symbol, when) not in prices:
            by_symbol.setdefault(symbol, []).append(when)
    if not by_symbol:
        return

    def fetch(symbol):
        return [((symbol, when), close_before(symbol, when)) for when in by_symbol[symbol]]

    for results in _pool().map(fetch, list(by_symbol)):
        for pair, price in results:
            prices[pair] = price


def _price(cache: dict, symbol: str, when: datetime) -> Decimal:
    key = (symbol, when)
    if key not in cache:
        cache[key] = close_before(symbol, when)
    if cache[key] is None:
        raise StockMonthUnavailable(f'no {symbol} close before {when.isoformat()}')
    return cache[key]


def stock_month(bsc_address: str, start: datetime, end: datetime, now: datetime) -> StockMonth | None:
    """The viewed month [start, end) of this wallet's stocks, or None (unknown).

    The current month (end > now) ends "now" at the live price; a past month
    ends at its last daily close."""
    from .gm_holdings import holdings_units, registry
    from .gm_tvl import _market_by_symbol

    if not bsc_address:
        return StockMonth(state='none')
    current = end > now
    try:
        # Registry first, on this thread: on a cold cache the scan and the
        # ledger decode would otherwise each fetch Ondo's address list.
        registry()
        # In-flight trades BEFORE the ledger: a batch confirming between the
        # two reads is then in one list or both, never in neither (read the
        # other way round, a trade confirming during the scan would be in no
        # list while the chain shows it: 'value_only' after the user's own
        # trade). Both lists holding it only reads as 'settling', which asks
        # again in seconds.
        in_flight = pending_trades(bsc_address)
        # The chain scan and the market are network waits independent of the
        # ledger (a DB read, kept on this thread's connection): overlap them.
        pool = _pool()
        # Fresh (≤30s), complete, or nothing: a total is never partial or stale.
        scan = pool.submit(holdings_units, bsc_address, require_complete=True)
        listing = pool.submit(_market_by_symbol)    # {symbol: price (> 0), ticker, name}
        trades = confirmed_trades(bsc_address)
        chain_raw = scan.result()
        market = listing.result()
        if chain_raw is None:
            return None                     # scan unknown, never "no stocks"
        chain = {s: d for s, u in chain_raw.items() if (d := _dec(u)) is not None and d > 0}
        # A trade on the wire is settling even when the ledger still matches
        # the chain: the scan can lag the receipt the app already showed (a
        # node a block behind), and a month result from the pre-trade chain
        # would stand as final, with nothing asking again.
        pending = current and bool(in_flight)
        # The chain may or may not show an in-flight trade yet: the ledger
        # explains it either way. A past month ends before any in-flight
        # trade (≤15 min old), so its own numbers never include one.
        explained = (ledger_explains_chain(ledger_units(trades), chain)
                     or (bool(in_flight) and ledger_explains_chain(ledger_units(trades + in_flight), chain)))
        if not current and any(t.when < end for t in in_flight):
            explained = False               # month just ended under a trade in flight
        # Units come from each trade's signed quote, so the ledger needs every
        # trade READABLE; dollars are needed only for this month's trades (an
        # old trade's missing history row must not blank every later month).
        in_month = [t for t in trades if start <= t.when < end]
        exact = (not pending and explained
                 and not any(t.symbol.startswith('?') for t in trades)
                 and all(t.usd is not None for t in in_month))

        def live_price(symbol):
            p = (market.get(symbol) or {}).get('price')
            if p is None or p <= 0:
                raise StockMonthUnavailable(f'no live price for {symbol}')
            return p

        prices: dict = {}
        if not exact:
            if not current:
                return None
            if pending:
                # A trade on the wire but not final (the app shows success on
                # the receipt): today's value is known, the month's result in
                # seconds. Never "from outside Confío", never a guessed gain.
                _prefetch(prices, {(s, start) for s in chain})
                value = sum((u * live_price(s) for s, u in chain.items()), Decimal('0'))
                return StockMonth(state='settling', value_end=value,
                                  top=_top_mover(chain, market, prices, start, live_price),
                                  holdings=len(chain))
            if not chain:
                if any(start <= t.when < end for t in trades):
                    # Sold out this month, but the history can't say for how
                    # much: worth US$0 today, never an invitation to buy.
                    return StockMonth(state='value_only')
                return StockMonth(state='none')
            _prefetch(prices, {(s, start) for s in chain})
            value = sum((u * live_price(s) for s, u in chain.items()), Decimal('0'))
            return StockMonth(state='value_only', value_end=value,
                              top=_top_mover(chain, market, prices, start, live_price),
                              holdings=len(chain))

        units_start = ledger_units(trades, before=start)
        units_end = chain if current else ledger_units(trades, before=end)
        if not units_start and not units_end and not in_month:
            # (A first trade on the wire the scan doesn't show yet is
            # 'settling' above: never an invitation to someone who just bought.)
            # A past month before the first purchase of someone who holds
            # stocks now: no card, never an invitation to buy what they own.
            return StockMonth(state='none') if current or not chain else None

        # Start prices for every position (value on the 1st, top mover);
        # end prices only for a past month (the current one ends live).
        _prefetch(prices, {(s, start) for s in set(units_start) | set(units_end)}
                  | (set() if current else {(s, end) for s in units_end}))
        value_start = sum((u * _price(prices, s, start) for s, u in units_start.items()), Decimal('0'))
        end_price = live_price if current else (lambda s: _price(prices, s, end))
        value_end = sum((u * end_price(s) for s, u in units_end.items()), Decimal('0'))
        bought = sum((t.usd for t in in_month if t.kind == 'stock_buy'), Decimal('0'))
        sold = sum((t.usd for t in in_month if t.kind == 'stock_sell'), Decimal('0'))
        gain = value_end - value_start - bought + sold
        base = value_start + bought
        return StockMonth(
            state='gain', value_end=value_end, value_start=value_start, bought=bought, sold=sold,
            gain=gain, gain_pct=(gain / base * 100) if base > 0 else None,
            top=_top_mover(units_end, market, prices, start, end_price),
            holdings=len(units_end))
    except StockMonthUnavailable as exc:
        logger.info('stock month unavailable for %s: %s', bsc_address, exc)
        return None


def _top_mover(units: dict, market: dict, prices: dict, start: datetime, end_price) -> Mover | None:
    """The held position whose price moved most over the month (either way).
    A position without a start price (listed mid-month) is skipped."""
    best = None
    for symbol in units:
        try:
            p0 = _price(prices, symbol, start)
            p1 = end_price(symbol)
        except StockMonthUnavailable:
            continue
        change = (p1 / p0 - 1) * 100
        if best is None or abs(change) > abs(best[1]):
            best = (symbol, change)
    if best is None:
        return None
    meta = market.get(best[0]) or {}
    from .schema import _display_name
    ticker = meta.get('ticker') or best[0].removesuffix('on')
    return Mover(ticker=ticker, name=_display_name(meta.get('name') or ticker), change_pct=best[1])
