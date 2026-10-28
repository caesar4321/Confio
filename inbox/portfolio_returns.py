"""A member's investment returns over 24h / 7d / 30d (Perfil inversor, Liga).

The sleeve is what the member invested in through Confío: U.S. stocks (Ondo
GM tokens) and Bitcoin & gold. Dollar balances are cash, not performance, so
a deposit can never read as a gain.

Every position in the sleeve arrives through a Confío trade while the ledger
explains the chain, so the units held at ANY past instant are the ledger's
units then, and a past day is fully determined by the ledger plus that day's
closes. That makes the 30-day backfill and the nightly run the same
computation (sync_wallet), and a re-run idempotent.

A day (00:00 to 24:00 UTC):

    V0 = units at 00:00 x the close at 00:00
    V1 = units at 24:00 x the close at 24:00
    F  = buys - sells settled that day (what the member paid / got; fees
         are a cost, so they lower the return)
    r  = (V1 - V0 - F) / (V0 + F / 2)    Modified Dietz, flows at mid-day
         0 when that base is under US$1 (nothing invested to speak of)

A period chain-links its days, Π(1 + r) - 1, plus today's partial day at
live prices. 24h is today's partial day alone.

The close at a boundary is the last completed daily candle at or before it,
final only when a candle closes exactly there or the gap is explained: a
market-wide closure (the broad-market references have no candle in it
either), or, for a stock, a gap its own feed moved past and still shows
after SETTLED_GAP (no one traded it that day). A candle running late is
retried, never frozen into a proven day.

Trust: the ledger must explain the chain now (same rule as Tu mes,
cusd_plus/stock_month.py) and never sell what it didn't hold at any point.
Units from outside Confío, an unreadable trade, a trade without its
settlement row or a close that never arrived make the day unknown: stored
as untrusted (null return), shown as "--", never ranked. Conditions that
resolve on their own (a trade on the wire, a failed scan or price feed, a
candle not published yet) write nothing, so the next run retries.

Each proven day stores a signature of the ledger up to its end: a trade
confirmed or re-settled later reopens exactly the days it touches.
"""
from __future__ import annotations

import hashlib
import logging
import random
import time as time_module
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.utils import timezone

logger = logging.getLogger(__name__)

RANGES = {'24h': 0, '7d': 7, '30d': 30}
BACKFILL_DAYS = 30
MIN_BASE_USD = Decimal('1')
# Relative to the units a symbol's trades moved: a buy's quote and the
# matching sell-all may differ by this much, which is zero, never a holding.
UNITS_TOLERANCE = Decimal('0.000001')
# A missing close older than this, with the feed never moving past it, is
# unknown for good (delisted, feed gap) instead of retried forever.
PRICE_GRACE = timedelta(days=3)
CARRY_MAX = timedelta(days=7)
# A stock's own gap this old, with its feed past it, is a day nobody traded.
SETTLED_GAP = timedelta(days=2)
# A weekend day this long over, with the broad-market feed already past it,
# is final for a token that has no candle of its own: nobody traded it.
# Without this, thin tokens (PBRon, KLACon…) waited for Monday's trade and
# every holder fell out of the league all weekend.
WEEKEND_SETTLE = timedelta(hours=6)
# A trade recorded this close before midnight may have settled after it:
# its day comes from its block's own timestamp. Covers both in-flight
# windows (stocks 15 min, crypto 35 min).
NEAR_MIDNIGHT = timedelta(minutes=40)
STOCK_OHLC_RANGE = '3M'     # daily candles, enough for a 30-day backfill
# Broad-market tokens that tell a market closure from a symbol's feed gap.
MARKET_REFERENCES = ('SPYon', 'IVVon', 'QQQon')
# How old a stock candle answer can be: gm_api.ohlc caches 300 s from when
# the response ARRIVED, and a slow response (15 s per read, no total cap)
# may have been sampled well before that. Generous on purpose: it only
# delays the first minutes after midnight, and the nightly run is at 00:40.
STOCK_CANDLE_MAX_AGE = timedelta(minutes=10)
CRYPTO_OHLC_RANGE = '1Y'
DAY = timedelta(days=1)

# Reasons a day is unknown for good (stored, null return).
OUTSIDE_UNITS = 'outside_units'
UNREADABLE_TRADE = 'unreadable_trade'
MISSING_SETTLEMENT = 'missing_settlement'
PRICE_MISSING = 'price_missing'
OFF_CATALOG = 'off_catalog'


class Retry(Exception):
    """Unknown for now: write nothing, the next run asks again."""


class Untrusted(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Ledger:
    stocks: list
    crypto: list
    # Futuros: episodes (cusd_plus/perps_portfolio.Episode) and their ledger
    # rows (margin out = perps_buy, proceeds in = perps_sell, close marker).
    perps: list = field(default_factory=list)
    perps_rows: list = field(default_factory=list)

    @property
    def all(self) -> list:
        return self.stocks + self.crypto + self.perps_rows

    def first_day(self) -> date | None:
        trades = self.all
        return min(t.when for t in trades).astimezone(dt_timezone.utc).date() if trades else None

    def signature(self, before: datetime) -> str:
        """What the ledger says up to `before`: changes exactly when a trade
        in that span is added, re-settled or re-dated."""
        rows = sorted(f'{t.symbol}|{t.kind}|{t.units}|{t.usd}|{t.when.timestamp()}'
                      for t in self.all if t.when < before)
        return hashlib.sha1('\n'.join(rows).encode()).hexdigest()


@dataclass
class Day:
    day: date
    value_start: Decimal
    value_end: Decimal
    net_flow: Decimal
    gain: Decimal
    daily_return: Decimal


@dataclass
class PeriodReturn:
    range_key: str
    pct: Decimal | None              # percent, e.g. 8.0 for +8%
    gain_usd: Decimal | None
    as_of: datetime | None
    # (instant, cumulative percent since the period start), oldest first
    points: list = field(default_factory=list)


def day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=dt_timezone.utc)


def utc_today(now: datetime) -> date:
    return now.astimezone(dt_timezone.utc).date()


def dietz(value_start: Decimal, value_end: Decimal, net_flow: Decimal) -> tuple[Decimal, Decimal]:
    """(gain, return) of one day."""
    gain = value_end - value_start - net_flow
    base = value_start + net_flow / 2
    return gain, (gain / base if base >= MIN_BASE_USD else Decimal('0'))


# --- prices -----------------------------------------------------------------

class PriceBook:
    """Daily closes and block times for one run: each symbol's candles are
    fetched once (a failure too, so a dead feed costs one timeout per run,
    not one per day per wallet)."""

    def __init__(self):
        self._candles: dict = {}
        self._block_times: dict = {}
        # Set when a close came from the untraded-weekend rule: the day it
        # priced is stored provisional and recomputed until settled.
        self.provisional = False

    def _series(self, kind: str, symbol: str) -> list | None:
        key = (kind, symbol)
        if key not in self._candles:
            try:
                self._candles[key] = self._fetch(kind, symbol)
            except Untrusted:
                raise
            except Exception:  # noqa: BLE001 — feed down: retry next run
                logger.warning('returns: candles unavailable for %s', symbol, exc_info=True)
                self._candles[key] = None
        return self._candles[key]

    @staticmethod
    def _fetch(kind: str, symbol: str) -> list:
        """[(closed_at, price)] of completed daily candles, oldest first.
        Ondo's feed marks no candle as final and its cached answer can be up
        to STOCK_CANDLE_MAX_AGE old, so a stock candle counts only if it had closed
        before the oldest moment that answer can date from: a forming
        candle read just before midnight never becomes a close just after.
        OKX marks its own (confirmed)."""
        from cusd_plus import crypto_chart, crypto_month, gm_api
        from cusd_plus.stock_month import _dec

        out = []
        cutoff = None
        if kind == 'perp':
            # Hyperliquid's own daily candles (UTC days, the venue's marks).
            from cusd_plus import hyperliquid

            end = int(timezone.now().timestamp() * 1000)
            for c in hyperliquid.candles(symbol, '1d', end - 400 * 86_400_000, end):
                price = _dec(c.get('c')) if isinstance(c, dict) else None
                start = c.get('t') if isinstance(c, dict) else None
                if price is None or price <= 0 or not isinstance(start, int):
                    continue
                closed_at = datetime.fromtimestamp(start / 1000, tz=dt_timezone.utc) + DAY
                if closed_at <= timezone.now():
                    out.append((closed_at, price))
            out.sort(key=lambda row: row[0])
            return out
        if kind == 'stock':
            cutoff = timezone.now() - STOCK_CANDLE_MAX_AGE
            rows = gm_api.ohlc(symbol, STOCK_OHLC_RANGE) or []
        else:
            token = crypto_month._token(symbol)
            if token is None:
                raise Untrusted(OFF_CATALOG)
            rows = [c for c in crypto_chart.ohlc(token, CRYPTO_OHLC_RANGE) or [] if c.get('confirmed') is True]
        for c in rows:
            ts = float(c.get('timestamp') or 0)
            if not ts:
                continue
            if ts < 1e12:
                ts *= 1000                  # seconds → ms
            price = _dec(c.get('close'))
            closed_at = datetime.fromtimestamp(ts / 1000, tz=dt_timezone.utc) + DAY
            if price is not None and price > 0 and (cutoff is None or closed_at <= cutoff):
                out.append((closed_at, price))
        out.sort(key=lambda row: row[0])
        return out

    def close(self, kind: str, symbol: str, boundary: datetime, now: datetime) -> Decimal:
        series = self._series(kind, symbol)
        if series is None:
            raise Retry(f'no candles for {symbol}')
        completed = [row for row in series if row[0] <= now]
        before = [row for row in completed if row[0] <= boundary]
        if before:
            closed_at, price = before[-1]
            if closed_at == boundary:
                return price
            # Bitcoin & gold trade every day: a gap is never a closure. A
            # stock's last close carries across a market-wide closure, or
            # across a day its own feed skipped for good: Ondo publishes no
            # candle for a token nobody traded (PBRon on weekends while
            # AAPLon and the references trade), and a gap its own feed has
            # moved past and still shows after SETTLED_GAP is a no-trade
            # day, not a candle running late.
            if (kind == 'stock' and boundary - closed_at <= CARRY_MAX
                    and any(row[0] > boundary for row in completed)
                    and (self._market_closed(symbol, closed_at, boundary, now)
                         or now - boundary > SETTLED_GAP)):
                return price
            # Only within PRICE_GRACE: a token that never trades again falls
            # through to Untrusted below instead of staying provisional forever.
            if (kind == 'stock' and boundary - closed_at <= CARRY_MAX and now - boundary <= PRICE_GRACE
                    and self._untraded_weekend(symbol, closed_at, boundary, now)):
                # Good enough to show, not proof: the token's own candle may
                # still be on its way, so the day stays open (sync_wallet).
                self.provisional = True
                return price
        if now - boundary > PRICE_GRACE:
            raise Untrusted(PRICE_MISSING)
        raise Retry(f'close for {symbol} at {boundary.isoformat()} not final yet')

    def _untraded_weekend(self, symbol: str, last_close: datetime, boundary: datetime, now: datetime) -> bool:
        """Every missing day is a Saturday or Sunday (UTC), it ended at least
        WEEKEND_SETTLE ago, and a broad-market reference already has its
        candle for the last of them: the feed published that day, so this
        token's missing candle means nobody traded it, not that it's late."""
        if now - boundary < WEEKEND_SETTLE:
            return False
        day = last_close
        while day < boundary:
            # A candle closing at `day` + 1 covers the UTC day starting at `day`.
            if day.weekday() < 5:
                return False
            day += DAY
        for ref in MARKET_REFERENCES:
            if ref == symbol:
                continue
            try:
                series = self._series('stock', ref)
            except Untrusted:
                continue
            if any(at >= boundary for at, _ in (series or []) if at <= now):
                return True
        return False

    def _market_closed(self, symbol: str, last_close: datetime, boundary: datetime, now: datetime) -> bool:
        """The U.S. market had no session between last_close and boundary
        (weekend, holiday): every readable broad-market reference whose feed
        has moved past the boundary has no candle in that gap either, and at
        least one does. One reference that traded in the gap proves the
        market was open. The symbol itself never counts: its own gap proves
        nothing."""
        vouched = False
        for ref in MARKET_REFERENCES:
            if ref == symbol:
                continue
            try:
                series = self._series('stock', ref)
            except Untrusted:
                continue
            completed = [row[0] for row in series or [] if row[0] <= now]
            if any(last_close < at <= boundary for at in completed):
                return False                # it traded in the gap, lagging feed or not
            if any(at > boundary for at in completed):
                vouched = True
        return vouched

    def block_time(self, block: int) -> datetime | None:
        from django.core.cache import cache

        from cusd_plus.fee_ledger import block_time
        from cusd_plus.tasks import _rpc

        when = _cached_block_time(block)
        if when is not None:
            return when
        when = block_time(_rpc, block, self._block_times)
        if when is not None:
            try:
                cache.set(_block_time_key(block), when.timestamp(), timeout=None)
            except Exception:  # noqa: BLE001
                pass
        return when


class CachedBlockTimes(PriceBook):
    """Block times from the cache only (a miss is unknown, never an RPC
    wait): for reads inside a request."""

    def block_time(self, block: int) -> datetime | None:
        return _cached_block_time(block)


# A block's time never changes: once read (every nightly run reads each
# near-midnight trade's), a profile view needs no RPC for it.
def _block_time_key(block: int) -> str:
    return f'returns:block_time:{block}'


def _cached_block_time(block: int) -> datetime | None:
    from django.core.cache import cache

    try:
        stamp = cache.get(_block_time_key(block))
    except Exception:  # noqa: BLE001
        return None
    return None if stamp is None else datetime.fromtimestamp(stamp, tz=dt_timezone.utc)


# --- ledger and trust -------------------------------------------------------

def _settled_at(when, block, prices: PriceBook):
    """The true UTC time of a chain row: a batch recorded just before
    midnight may have landed after it."""
    utc = when.astimezone(dt_timezone.utc)
    midnight = day_start(utc.date() + DAY)
    if midnight - utc > NEAR_MIDNIGHT:
        return when
    if block is None:
        raise Retry('confirmed trade without a block')
    landed = prices.block_time(block)
    if landed is None:
        raise Retry(f'no time for block {block}')
    return landed


def _settled_when(trade, prices: PriceBook):
    when = _settled_at(trade.when, trade.block, prices)
    return trade if when is trade.when else replace(trade, when=when)


def _settled_episode(ep, prices: PriceBook):
    """An episode valued on the same clock as its cash flows: dollars out
    and back in at the time their blocks landed."""
    moved = {when: _settled_at(when, block, prices) for when, _usd, block in ep.put_in}
    put_in = [(moved[when], usd, block) for when, usd, block in ep.put_in]
    # A top-up in flight starts when its batch landed, like its cash flow.
    pending = [(moved.get(start, start), until, usd, arrived, applied)
               for start, until, usd, arrived, applied in ep.pending_topups]
    returned = ep.returned
    if returned is not None and returned[2] is not None:
        returned = (_settled_at(returned[0], returned[2], prices), returned[1], returned[2])
    return replace(ep, put_in=sorted(put_in, key=lambda r: r[0]), returned=returned, pending_topups=pending)


def _walk_units(trades: list, before: datetime | None = None) -> dict:
    """{symbol: units} held after the trades (those before `before`), in
    time order. Never sold more than Confío's ledger held at that moment:
    a sale of units that came from outside (and left again) would otherwise
    net out. A sale that overshoots the position by no more than the
    tolerance of the units involved (a quote's rounding on a sell-all) ends
    it at exactly zero; a positive residual is kept as the units it is."""
    units: dict = {}
    for t in sorted(trades, key=lambda t: t.when):
        if before is not None and t.when >= before:
            continue
        held = units.get(t.symbol, Decimal('0'))
        if t.kind.endswith('_buy'):
            units[t.symbol] = held + t.units
            continue
        left = held - t.units
        if left < 0 and -left <= max(held, t.units) * UNITS_TOLERANCE:
            left = Decimal('0')
        if left < 0:
            raise Untrusted(OUTSIDE_UNITS)
        units[t.symbol] = left
    return {s: u for s, u in units.items() if u > 0}


def _check_running_units(trades: list) -> None:
    _walk_units(trades)


def load_ledger(wallet: str, prices: PriceBook) -> Ledger:
    from cusd_plus import crypto_month, perps_portfolio, stock_month

    try:
        stocks = stock_month.confirmed_trades(wallet)
        crypto = crypto_month.confirmed_trades(wallet)
        perps = perps_portfolio.episodes(wallet)
    except perps_portfolio.PerpsLedgerUnknown as exc:
        raise Retry('perps settlement pending') from exc
    except Exception as exc:  # noqa: BLE001 — a DB/registry blip is not a verdict
        raise Retry('ledger unreadable') from exc
    if any(t.symbol.startswith('?') for t in stocks + crypto):
        raise Untrusted(UNREADABLE_TRADE)
    # Chain rows take their block's time near midnight, on the episodes
    # themselves (valuation and cash flows share one clock); venue facts
    # (close, fill/cost/size markers, refunds) have no block and keep theirs.
    perps = [_settled_episode(ep, prices) for ep in perps]
    perps_rows = list(perps_portfolio.ledger_trades(perps))
    ledger = Ledger(stocks=sorted((_settled_when(t, prices) for t in stocks), key=lambda t: t.when),
                    crypto=sorted((_settled_when(t, prices) for t in crypto), key=lambda t: t.when),
                    perps=perps, perps_rows=sorted(perps_rows, key=lambda t: t.when))
    _check_running_units(ledger.stocks)
    _check_running_units(ledger.crypto)
    return ledger


def in_flight(wallet: str) -> bool:
    """A stock trade or crypto swap on the wire, each by its own window."""
    from cusd_plus.crypto_holdings import batches_in_flight
    from cusd_plus.gm_holdings import stock_batches_in_flight
    from cusd_plus.perps_portfolio import batches_in_flight as perps_in_flight

    return (stock_batches_in_flight(wallet).exists() or batches_in_flight(wallet).exists()
            or perps_in_flight(wallet).exists())


def check_chain(wallet: str, ledger: Ledger) -> None:
    """Raise unless the ledger explains every unit the wallet holds now.
    Confirmed trades a lagging node hasn't seen yet (the RPC pool rotates)
    are a Retry, never a verdict. Run in_flight() BEFORE loading the
    ledger: a trade confirming in between is then in one or the other."""
    from cusd_plus import crypto_month
    from cusd_plus.crypto_holdings import holdings_snapshot
    from cusd_plus.gm_holdings import STALE_AFTER, complete_holdings
    from cusd_plus.stock_month import _dec, _unseen_by_scan, ledger_explains_chain

    try:
        scan = complete_holdings(wallet, max_age=STALE_AFTER)
        crypto_scan = holdings_snapshot(wallet, allow_last_known=False)
    except Exception as exc:  # noqa: BLE001
        raise Retry('holdings unreadable') from exc
    if scan is None or crypto_scan is None:
        raise Retry('holdings unreadable')
    chain_raw, blocks = scan
    chain = {s: d for s, u in chain_raw.items() if (d := _dec(u)) is not None and d > 0}
    if _unseen_by_scan(ledger.stocks, blocks):
        raise Retry('scan behind a confirmed trade')
    # The same normalized units valuation uses (a sell-all's rounding
    # overshoot is zero, not a negative balance).
    if not ledger_explains_chain(_walk_units(ledger.stocks), chain):
        raise Untrusted(OUTSIDE_UNITS)
    raw, block = crypto_scan
    try:
        crypto_chain = crypto_month._chain_units(raw)
    except crypto_month.CryptoMonthUnavailable as exc:
        raise Untrusted(OFF_CATALOG) from exc
    if block is not None and any(t.block is not None and t.block > block for t in ledger.crypto):
        raise Retry('crypto scan behind a confirmed swap')
    if not ledger_explains_chain(_walk_units(ledger.crypto), crypto_chain):
        raise Untrusted(OUTSIDE_UNITS)


def trusted_ledger(wallet: str, prices: PriceBook) -> Ledger:
    """The wallet's ledger, proven against the chain now."""
    if in_flight(wallet):
        raise Retry('trade on the wire')
    ledger = load_ledger(wallet, prices)
    check_chain(wallet, ledger)
    return ledger


# --- valuation --------------------------------------------------------------

def held_at(trades: list, when: datetime) -> dict:
    """{symbol: units} the ledger held at `when`; real holdings, however
    small, are kept."""
    return _walk_units(trades, before=when)


def value_at(ledger: Ledger, when: datetime, now: datetime, prices: PriceBook) -> Decimal:
    from cusd_plus.perps_portfolio import equity_at

    total = Decimal('0')
    for kind, trades in (('stock', ledger.stocks), ('crypto', ledger.crypto)):
        for symbol, units in held_at(trades, when).items():
            total += units * prices.close(kind, symbol, when, now)
    for episode in ledger.perps:
        total += equity_at(episode, when, lambda coin: prices.close('perp', coin, when, now))
    return total


def _flows(ledger: Ledger, start: datetime, end: datetime) -> Decimal:
    flow = Decimal('0')
    for t in ledger.all:
        if start <= t.when < end:
            if t.usd is None:
                raise Untrusted(MISSING_SETTLEMENT)
            flow += t.usd if t.kind.endswith('_buy') else -t.usd
    return flow


def compute_day(ledger: Ledger, day: date, now: datetime, prices: PriceBook) -> Day:
    start, end = day_start(day), day_start(day + DAY)
    if end > now:
        raise ValueError(f'{day} has not ended')
    value_start = value_at(ledger, start, now, prices)
    value_end = value_at(ledger, end, now, prices)
    flow = _flows(ledger, start, end)
    gain, ret = dietz(value_start, value_end, flow)
    return Day(day=day, value_start=value_start, value_end=value_end, net_flow=flow, gain=gain,
               daily_return=ret)


def live_value(ledger: Ledger, now: datetime) -> Decimal:
    """The sleeve now: ledger units (the chain check vouches for them) at
    live prices. Retry when any live price is unknown."""
    from cusd_plus import crypto_month

    from .member_portfolio import _market

    total = Decimal('0')
    stocks = held_at(ledger.stocks, now)
    if stocks:
        try:
            market = _market()
        except Exception as exc:  # noqa: BLE001
            raise Retry('market unavailable') from exc
        for symbol, units in stocks.items():
            price = (market.get(symbol) or {}).get('price')
            if price is None or price <= 0:
                raise Retry(f'no live price for {symbol}')
            total += units * price
    crypto = held_at(ledger.crypto, now)
    if crypto:
        try:
            live = crypto_month._live_prices(now)
        except Exception as exc:  # noqa: BLE001
            raise Retry('crypto prices unavailable') from exc
        for symbol, units in crypto.items():
            price = live.get(symbol)
            if price is None:
                raise Retry(f'no live price for {symbol}')
            total += units * price
    if ledger.perps:
        from cusd_plus.perps_portfolio import equity_at, live_marks

        try:
            marks = live_marks({e.coin for e in ledger.perps})
        except Exception as exc:  # noqa: BLE001
            raise Retry('perps marks unavailable') from exc

        def mark(coin):
            if marks.get(coin) is None:
                raise Retry(f'no live mark for {coin}')
            return marks[coin]

        for episode in ledger.perps:
            total += equity_at(episode, now, mark)
    return total


def today_partial(wallet: str, now: datetime, prices: PriceBook | None = None) -> Day | None:
    """Today from 00:00 UTC to now, or None when it can't be stated (no
    investments, or anything unknown)."""
    prices = prices or PriceBook()
    try:
        ledger = trusted_ledger(wallet, prices)
        if not ledger.all:
            return None
        start = day_start(utc_today(now))
        value_start = value_at(ledger, start, now, prices)
        value_end = live_value(ledger, now)
        flow = _flows(ledger, start, now)
    except (Retry, Untrusted) as exc:
        logger.info('returns: no partial day for %s: %s', wallet, exc)
        return None
    gain, ret = dietz(value_start, value_end, flow)
    return Day(day=start.date(), value_start=value_start, value_end=value_end, net_flow=flow, gain=gain,
               daily_return=ret)


# --- storage ----------------------------------------------------------------

def _row_values(day: Day | None, sig: str, reason: str = '') -> dict:
    if day is None:
        return {'value_start_usd': None, 'value_end_usd': None, 'net_flow_usd': None, 'gain_usd': None,
                'daily_return': None, 'ledger_trusted': False, 'untrusted_reason': reason, 'ledger_sig': sig}
    q6, q10 = Decimal('0.000001'), Decimal('0.0000000001')
    return {'value_start_usd': day.value_start.quantize(q6), 'value_end_usd': day.value_end.quantize(q6),
            'net_flow_usd': day.net_flow.quantize(q6), 'gain_usd': day.gain.quantize(q6),
            'daily_return': day.daily_return.quantize(q10), 'ledger_trusted': True, 'untrusted_reason': '',
            'ledger_sig': sig}


def _store(user, wallet: str, day: date, values: dict, existing) -> bool:
    """Write the row unless it already says exactly this. True if written."""
    from .models import PortfolioDailySnapshot

    if existing is not None and all(getattr(existing, k) == v for k, v in values.items()):
        return False
    PortfolioDailySnapshot.objects.update_or_create(wallet=wallet, day=day, defaults={'user': user, **values})
    return True


def provisional_sig(sig: str) -> str:
    """A hex ledger signature never contains 'p': ending it with one can't
    match any real signature, so _is_final keeps the day open (and the
    column's 40 characters still fit)."""
    return f'{(sig or "")[:39]}p'


def _is_shown(row, ledger: Ledger | None) -> bool:
    """Good to display: final, or provisional on the same ledger (a weekend
    close carried until the token's own feed settles it)."""
    if row is None or not row.ledger_trusted or ledger is None:
        return False
    sig = ledger.signature(day_start(row.day + DAY))
    return row.ledger_sig in (sig, provisional_sig(sig))


def _is_final(row, ledger: Ledger | None) -> bool:
    return (row is not None and row.ledger_trusted and ledger is not None
            and row.ledger_sig == ledger.signature(day_start(row.day + DAY)))


def sync_wallet(user, wallet: str, *, days: int = BACKFILL_DAYS, now: datetime | None = None,
                recompute: bool = False, prices: PriceBook | None = None) -> dict:
    """Fill the last `days` complete UTC days for one wallet. A proven day
    is final while the ledger up to its end is unchanged (unless
    `recompute`); unknown days are retried each run. Days before the first
    trade get no row (nothing was invested). Returns counts."""
    from .models import PortfolioDailySnapshot

    now = now or timezone.now()
    prices = prices or PriceBook()
    wallet = wallet.lower()
    today = utc_today(now)
    counts = {'written': 0, 'unchanged': 0, 'retry': 0}
    wanted = [today - timedelta(days=n) for n in range(days, 0, -1)]
    ledger, reason = None, ''
    try:
        if in_flight(wallet):
            raise Retry('trade on the wire')
        ledger = load_ledger(wallet, prices)
    except Retry as exc:
        logger.info('returns: retry %s: %s', wallet, exc)
        counts['retry'] += 1
        return counts
    except Untrusted as exc:
        reason = exc.reason            # every open day is unknown
    if ledger is not None:
        first = ledger.first_day()
        if first is None:
            return counts
        wanted = [d for d in wanted if d >= first]
    existing = {r.day: r for r in PortfolioDailySnapshot.objects.filter(wallet=wallet, day__in=wanted)}
    todo = [d for d in wanted if recompute or not _is_final(existing.get(d), ledger)]
    counts['unchanged'] = len(wanted) - len(todo)
    if not todo:
        return counts
    if ledger is not None:
        try:
            check_chain(wallet, ledger)
        except Retry as exc:
            logger.info('returns: retry %s: %s', wallet, exc)
            counts['retry'] += 1
            return counts
        except Untrusted as exc:
            reason = exc.reason

    for day in todo:
        sig = ledger.signature(day_start(day + DAY)) if ledger is not None else ''
        if reason:
            values = _row_values(None, sig, reason)
        else:
            try:
                prices.provisional = False
                computed = compute_day(ledger, day, now, prices)
                if prices.provisional:
                    # Shown now, never final: every run recomputes it until a
                    # close the token's own feed proves replaces the carry.
                    sig = provisional_sig(sig)
                values = _row_values(computed, sig)
            except Retry as exc:
                logger.info('returns: retry %s %s: %s', wallet, day, exc)
                counts['retry'] += 1
                continue
            except Untrusted as exc:
                values = _row_values(None, sig, exc.reason)
        if _store(user, wallet, day, values, existing.get(day)):
            counts['written'] += 1
        else:
            counts['unchanged'] += 1
    return counts


def wallets_to_snapshot():
    """(user, wallet) for every personal account that ever traded stocks or
    Bitcoin & gold in Confío."""
    from blockchain.models import CRYPTO_BATCH_KINDS, SponsoredBatch
    from users.models import Account

    wallets = set(
        w.lower() for w in SponsoredBatch.objects.filter(
            kind__in=('stock_buy', 'stock_sell', *CRYPTO_BATCH_KINDS, 'perps_open'), status='confirmed')
        .values_list('user_bsc_address', flat=True).distinct() if w)
    if not wallets:
        return []
    accounts = (Account.objects.filter(account_type='personal', deleted_at__isnull=True)
                .exclude(bsc_address__isnull=True).exclude(bsc_address='')
                .select_related('user'))
    return [(a.user, a.bsc_address.lower()) for a in accounts.iterator() if a.bsc_address.lower() in wallets]


def sync_all(*, budget_seconds: float, days: int = BACKFILL_DAYS, recompute: bool = False,
             wallet: str = '', log=None) -> dict:
    """Every investing wallet, in random order, until the time budget runs
    out (the next hourly run picks up the rest: a slow wallet never starves
    the same ones every night). One PriceBook for the whole run."""
    deadline = time_module.monotonic() + budget_seconds
    prices = PriceBook()
    totals = {'wallets': 0, 'written': 0, 'unchanged': 0, 'retry': 0, 'errors': 0, 'deferred': 0}
    pairs = [p for p in wallets_to_snapshot() if not wallet or p[1] == wallet.lower()]
    random.shuffle(pairs)
    for i, (user, w) in enumerate(pairs):
        if time_module.monotonic() > deadline:
            totals['deferred'] = len(pairs) - i
            break
        totals['wallets'] += 1
        try:
            counts = sync_wallet(user, w, days=days, recompute=recompute, prices=prices)
        except Exception:  # noqa: BLE001 — one wallet never stops the rest
            logger.exception('returns: snapshot failed for %s', w)
            totals['errors'] += 1
            continue
        for key, value in counts.items():
            totals[key] += value
        if log:
            log(f'{w}: {counts}')
    return totals


# --- periods ----------------------------------------------------------------

def period_return(user, range_key: str, now: datetime | None = None) -> PeriodReturn | None:
    """The member's return over a range, or None when they have no wallet.
    pct/gain are None when they have no investments or any day of the range
    is unknown (including a day the nightly run hasn't proven yet)."""
    from .member_portfolio import personal_wallet
    from .models import PortfolioDailySnapshot

    n_days = RANGES[range_key]
    now = now or timezone.now()
    wallet = personal_wallet(user)
    if not wallet:
        return None
    unknown = PeriodReturn(range_key=range_key, pct=None, gain_usd=None, as_of=None)
    if range_key == '24h':
        # The last 24 hours, not a UTC day: Bitcoin, gold and Futuros never close.
        from .rolling_returns import rolling

        result = rolling(wallet, now, with_points=True)
        if result is None:
            return unknown
        return PeriodReturn(range_key=range_key, pct=result.pct, gain_usd=result.gain, as_of=result.as_of,
                            points=result.points)
    prices = PriceBook()
    try:
        ledger = load_ledger(wallet, prices)
    except (Retry, Untrusted):
        return unknown
    first = ledger.first_day()
    if first is None:
        return unknown
    today = utc_today(now)
    window = [today - timedelta(days=n) for n in range(n_days, 0, -1)]
    rows = {r.day: r for r in PortfolioDailySnapshot.objects.filter(wallet=wallet, day__in=window)}

    days: list = []   # (end instant, return, gain)
    for day in window:
        if day < first:
            days.append((day_start(day + DAY), Decimal('0'), Decimal('0')))   # not invested yet
            continue
        row = rows.get(day)
        if not _is_shown(row, ledger) or row.daily_return is None:
            return unknown
        days.append((day_start(day + DAY), row.daily_return, row.gain_usd))

    as_of = day_start(today)
    partial = today_partial(wallet, now, prices)
    if partial is not None:
        days.append((now, partial.daily_return, partial.gain))
        as_of = now
    elif n_days == 0:
        return unknown

    growth, gain = Decimal('1'), Decimal('0')
    points = [(day_start(window[0]) if window else day_start(today), Decimal('0'))]
    for end, ret, day_gain in days:
        growth *= 1 + ret
        gain += day_gain
        points.append((end, (growth - 1) * 100))
    return PeriodReturn(range_key=range_key, pct=(growth - 1) * 100, gain_usd=gain, as_of=as_of, points=points)
