"""Tu mes "Oro y Bitcoin": what the account's crypto & gold did in one month.

    gain = value at month end − value at month start − bought + sold

The twin of stock_month.py, with the same rules:
- Buys and sells are Confío's own exact settlements (CryptoTrade, one row per
  confirmed swap, from its receipt): a buy is the dollars that left, the
  0.9% exit fee included; a sell the dollars that came back, after the entry
  fee. Same sides as the stocks card, so on both cards the fees read as part
  of the month's cost, never as a market move.
- Units at an instant come from that ledger; the ledger is trusted only when
  its all-time units explain the wallet's live balances (CryptoHoldings).
  A balance that arrived from (or left to) outside Confío makes the month
  unknowable: the current month degrades to 'value_only', a past one to None.
- Prices: "today" is the latest PancakeSwap snapshot (CryptoPricePoint, the
  price every crypto screen shows); a month boundary is OKX's last daily
  close before it (crypto_chart, display-only history: the snapshots are
  kept 8 days), at most PRICE_LOOKBACK old.
Anything unknown is None: the card hides, never a guessed number.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from .stock_month import (
    DAY_MS, PRICE_LOOKBACK, Trade, _apply, _dec, _in_pool_db, _pool, _unseen_by_scan,
    ledger_explains_chain, ledger_units,
)

logger = logging.getLogger(__name__)

OHLC_RANGE = '1Y'                      # daily closes, one year back
# Snapshots run every 15 minutes: an older "today" means the job stopped.
LIVE_PRICE_MAX_AGE = timedelta(hours=1)
# Spanish display names where the catalog's issuer name is not what people
# call the asset ("Tether Gold" is gold).
DISPLAY_NAMES = {'XAUT': 'Oro'}


class CryptoMonthUnavailable(Exception):
    """Something needed is unknown: hide the card."""


@dataclass
class AssetMove:
    symbol: str
    ticker: str
    name: str
    category: str
    change_pct: Decimal | None     # price change over the viewed month; None when a boundary is unknown


@dataclass
class CryptoMonth:
    state: str                         # 'gain' | 'value_only' | 'settling' | 'none'
    value_end: Decimal = Decimal('0')
    value_start: Decimal | None = None
    bought: Decimal | None = None
    sold: Decimal | None = None
    gain: Decimal | None = None
    gain_pct: Decimal | None = None    # gain / (value at start + bought)
    assets: list = field(default_factory=list)   # [AssetMove] held at the end of the window
    holdings: int = 0


def _token(symbol: str):
    from .crypto_catalog import by_symbol
    return by_symbol(symbol, include_unlisted=True)


def display_name(token) -> str:
    return DISPLAY_NAMES.get(token.symbol, token.name)


def confirmed_trades(bsc_address: str) -> list[Trade]:
    """Every confirmed Confío crypto/metal swap of this wallet, oldest first.
    A confirmed swap without its CryptoTrade row (receipt had no exact
    settlement event, or not synced yet) is unreadable: a '?' trade, so the
    ledger can never silently skip it."""
    from blockchain.models import CRYPTO_BATCH_KINDS, CryptoTrade, SponsoredBatch

    wallet = bsc_address.lower()
    rows = list(CryptoTrade.objects.filter(wallet=wallet, batch__status='confirmed')
                .select_related('batch').order_by('traded_at', 'batch_id'))
    trades = [Trade(symbol=r.symbol, kind=r.kind, units=r.units, usd=r.usd, when=r.traded_at,
                    block=r.batch.block_number) for r in rows]
    have = {r.batch_id for r in rows}
    for batch in SponsoredBatch.objects.filter(
            user_bsc_address__iexact=wallet, kind__in=CRYPTO_BATCH_KINDS,
            status='confirmed').exclude(id__in=have):
        logger.warning('crypto month: confirmed swap %s has no ledger row', batch.id)
        trades.append(Trade(symbol=f'?{batch.id}', kind=batch.kind, units=Decimal('0'), usd=None,
                            when=batch.created_at, block=batch.block_number))
    trades.sort(key=lambda t: t.when)
    return trades


def close_before(token, when: datetime) -> Decimal | None:
    """OKX's last daily close at or before `when` (within PRICE_LOOKBACK).
    A boundary more than a day old never changes: cached for hours."""
    from django.core.cache import cache
    from django.utils import timezone as dj_tz
    key = f'crypto_close_v1:{token.symbol}:{int(when.timestamp())}'
    cached = cache.get(key)
    if cached is not None:
        return _dec(cached)
    try:
        price = _close_from_candles(token, when)
    except Exception:  # noqa: BLE001 — an OKX/network failure is a missing price
        logger.warning('crypto month: candles unavailable for %s', token.symbol, exc_info=True)
        return None
    if price is not None and dj_tz.now() - when > timedelta(days=1):
        cache.set(key, str(price), 6 * 3600)
    return price


def _close_from_candles(token, when: datetime) -> Decimal | None:
    from . import crypto_chart
    cutoff_ms = when.timestamp() * 1000
    best = None
    for c in crypto_chart.ohlc(token, OHLC_RANGE) or []:
        if c.get('confirmed') is not True:
            continue                        # still forming (or cached while it was): not a close
        closed_at = float(c.get('timestamp') or 0) + DAY_MS     # daily candle: opens at its timestamp
        if closed_at <= cutoff_ms and (best is None or closed_at > best[0]):
            best = (closed_at, c.get('close'))
    if best is None or cutoff_ms - best[0] > PRICE_LOOKBACK.total_seconds() * 1000:
        return None
    price = _dec(best[1])
    return price if price is not None and price > 0 else None


def _prefetch(prices: dict, pairs: set) -> None:
    """Fill `prices` for every (symbol, boundary), one task per symbol in
    parallel (a symbol's two boundaries share its cached candles)."""
    by_symbol: dict = {}
    for symbol, when in pairs:
        if (symbol, when) not in prices:
            by_symbol.setdefault(symbol, []).append(when)
    if not by_symbol:
        return

    def fetch(symbol):
        token = _token(symbol)
        return [((symbol, when), close_before(token, when) if token else None) for when in by_symbol[symbol]]

    for results in _pool().map(fetch, list(by_symbol)):
        for pair, price in results:
            prices[pair] = price


def _price(prices: dict, symbol: str, when: datetime) -> Decimal:
    key = (symbol, when)
    if key not in prices:
        token = _token(symbol)
        prices[key] = close_before(token, when) if token else None
    if prices[key] is None:
        raise CryptoMonthUnavailable(f'no {symbol} close before {when.isoformat()}')
    return prices[key]


def _live_prices(now: datetime) -> dict:
    """{symbol: price} from the latest fresh snapshot of each listed token."""
    from .crypto_prices import market_rows
    out = {}
    for row in market_rows():
        at, price = row['priced_at'], row['price_usd']
        if price is not None and price > 0 and at is not None and now - at <= LIVE_PRICE_MAX_AGE:
            out[row['token'].symbol] = price
    return out


def _chain_units(raw: dict) -> dict:
    """{symbol: whole units} from base units; an off-catalog symbol is unknown."""
    out = {}
    for symbol, base in raw.items():
        token = _token(symbol)
        if token is None:
            raise CryptoMonthUnavailable(f'{symbol} is not in the catalog')
        if base:
            out[symbol] = Decimal(int(base)) / (Decimal(10) ** token.decimals)
    return out


def crypto_month(bsc_address: str, start: datetime, end: datetime, now: datetime) -> CryptoMonth | None:
    """The viewed month [start, end) of this wallet's crypto & gold, or None
    (unknown). The current month (end > now) ends "now" at the live price; a
    past month ends at its last daily close."""
    from .crypto_holdings import batches_in_flight, holdings_snapshot

    if not bsc_address:
        return CryptoMonth(state='none')
    current = end > now
    try:
        # In-flight swaps BEFORE the ledger: a swap confirming between the two
        # reads is then in one list or both, never in neither (stock_month).
        in_flight = list(batches_in_flight(bsc_address).values_list('created_at', flat=True))
        # Fresh or nothing: the stored row of a failed scan may predate coins
        # that moved in or out, which the ledger would then "explain".
        scan = _pool().submit(_in_pool_db, holdings_snapshot, bsc_address, allow_last_known=False)
        live_future = _pool().submit(_in_pool_db, _live_prices, now)
        trades = confirmed_trades(bsc_address)
        snapshot = scan.result()
        live = live_future.result()
        if snapshot is None:
            return None                     # scan unknown, never "no crypto"
        raw, block = snapshot
        chain = _chain_units(raw)
        # A confirmed swap newer than the node that served the scan (the RPC
        # pool rotates): the ledger must explain the chain as of what it saw.
        unseen = _unseen_by_scan(trades, {s: block for s in {t.symbol for t in trades}})
        unseen_ids = {id(t) for t in unseen}
        seen = [t for t in trades if id(t) not in unseen_ids]
        explained = ledger_explains_chain(ledger_units(seen), chain)
        lagging = bool(unseen)
        # A swap on the wire: the chain may or may not show it yet, and a buy's
        # units exist only in its receipt, so the month waits for finality.
        pending = current and (bool(in_flight) or lagging)
        if not current and any(when < end for when in in_flight):
            explained = False               # month just ended under a swap in flight
        in_month = [t for t in trades if start <= t.when < end]
        exact = (not pending and explained
                 and not any(t.symbol.startswith('?') for t in trades)
                 and all(t.usd is not None for t in in_month))

        def live_price(symbol):
            p = live.get(symbol)
            if p is None:
                from .crypto_catalog import tokens
                from .crypto_prices import price_usd
                token = _token(symbol)
                # A listed token without a fresh snapshot is unknown (the job
                # stopped); only a delisted one still held, which never has a
                # snapshot, is priced by one live quote.
                if token is None or any(t.symbol == symbol for t in tokens()):
                    raise CryptoMonthUnavailable(f'no fresh price for {symbol}')
                p = price_usd(token)
                if p is None or p <= 0:
                    raise CryptoMonthUnavailable(f'no live price for {symbol}')
                live[symbol] = p
            return p

        prices: dict = {}
        if not exact:
            if not current:
                return None
            if pending:
                held = _apply(chain, unseen) if lagging else chain
                if held is None:
                    held = {}                   # can't state today: the card shows no number
                _prefetch(prices, {(s, start) for s in held})
                value = sum((u * live_price(s) for s, u in held.items()), Decimal('0'))
                return CryptoMonth(state='settling', value_end=value,
                                   assets=_moves(held, prices, start, live_price), holdings=len(held))
            if not chain:
                if any(start <= t.when < end for t in trades):
                    return CryptoMonth(state='value_only')   # sold out, amount unknown: US$0 today
                return CryptoMonth(state='none')
            _prefetch(prices, {(s, start) for s in chain})
            value = sum((u * live_price(s) for s, u in chain.items()), Decimal('0'))
            return CryptoMonth(state='value_only', value_end=value,
                               assets=_moves(chain, prices, start, live_price), holdings=len(chain))

        units_start = ledger_units(trades, before=start)
        units_end = chain if current else ledger_units(trades, before=end)
        if not units_start and not units_end and not in_month:
            # Before the first purchase of someone who holds now: no card.
            return CryptoMonth(state='none') if current or not chain else None

        _prefetch(prices, {(s, start) for s in set(units_start) | set(units_end)}
                  | (set() if current else {(s, end) for s in units_end}))
        value_start = sum((u * _price(prices, s, start) for s, u in units_start.items()), Decimal('0'))
        end_price = live_price if current else (lambda s: _price(prices, s, end))
        value_end = sum((u * end_price(s) for s, u in units_end.items()), Decimal('0'))
        bought = sum((t.usd for t in in_month if t.kind == 'crypto_buy'), Decimal('0'))
        sold = sum((t.usd for t in in_month if t.kind == 'crypto_sell'), Decimal('0'))
        gain = value_end - value_start - bought + sold
        base = value_start + bought
        return CryptoMonth(
            state='gain', value_end=value_end, value_start=value_start, bought=bought, sold=sold,
            gain=gain, gain_pct=(gain / base * 100) if base > 0 else None,
            assets=_moves(units_end, prices, start, end_price), holdings=len(units_end))
    except CryptoMonthUnavailable as exc:
        logger.info('crypto month unavailable for %s: %s', bsc_address, exc)
        return None


def _moves(units: dict, prices: dict, start: datetime, end_price) -> list:
    """One row per held asset, Bitcoin before gold (catalog order), with its
    price change over the month; a missing boundary leaves the change None."""
    from .crypto_catalog import tokens
    order = {t.symbol: i for i, t in enumerate(tokens(include_unlisted=True))}
    out = []
    for symbol in sorted(units, key=lambda s: order.get(s, len(order))):
        token = _token(symbol)
        if token is None:
            continue
        try:
            change = (end_price(symbol) / _price(prices, symbol, start) - 1) * 100
        except CryptoMonthUnavailable:
            change = None
        out.append(AssetMove(symbol=symbol, ticker=token.ticker, name=display_name(token),
                             category=token.category, change_pct=change))
    return out
