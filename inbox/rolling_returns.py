"""Live results for the Liga and Rentabilidad, one engine for both: 24 h,
7 d and Mes (the profile's line beside the total is the 24 h). Bitcoin,
gold and Futuros trade around the clock, so 24 h and 7 d are the last
24 / 168 hours, never UTC days, and every range runs up to now.

Every SNAPSHOT_EVERY each investing wallet's sleeve is valued live and
stored (PortfolioValueSnapshot) when the ledger explains the chain and
nothing is on the wire. The result now is

    gain = value now - value at the range's start - money put in since

(buys minus sells, Futuros margin out minus proceeds in), and the % is that
over the money at work: the value it started with plus half of what came in
(the league's convention, so the % always has the dollars' sign).

The start: the snapshot taken 24 h / 7 d ago (7 d falls back to the proven
midnight before it while snapshots don't go back that far yet), or for Mes
the proven close of the month's eve (PortfolioDailySnapshot). Total starts
from nothing before the first trade: value now + everything sold -
everything bought, its % over everything bought.

Unknown is never a number: no snapshot or proven close at the start, one
taken when the money moved before it differs from what the ledger says now
(a trade confirmed or re-settled later), or anything the live value can't
state makes it None.
"""
from __future__ import annotations

import hashlib
import logging
import random
import time as time_module
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal

from django.utils import timezone

from .portfolio_returns import (DAY, MIN_BASE_USD, CachedBlockTimes, PriceBook, Retry, Untrusted, _flows, _is_shown,
                                day_start, live_value, trusted_ledger, utc_today, wallets_to_snapshot)

logger = logging.getLogger(__name__)

WINDOW = timedelta(hours=24)
WINDOWS = {'24h': WINDOW, '7d': timedelta(days=7)}
# The ranges this engine states.
LIVE_RANGES = ('24h', '7d', 'month', 'all')
SNAPSHOT_EVERY = timedelta(minutes=10)
# The starting snapshot may be this much older than 24 h ago (a run that
# skipped a wallet): a little over 24 h, never a guess.
START_TOLERANCE = timedelta(minutes=30)
KEEP = timedelta(days=8)       # a 7 d start, with room
Q6 = Decimal('0.000001')


@dataclass
class Rolling:
    gain: Decimal
    pct: Decimal
    # The money at work: value at the start plus half of what came in.
    capital: Decimal
    value_start: Decimal
    start_at: datetime
    as_of: datetime
    # (instant, cumulative percent since start_at), oldest first.
    points: list = field(default_factory=list)


def _capital(value_start: Decimal, flow: Decimal) -> Decimal:
    """A withdrawal was at work until it left: it never subtracts."""
    return value_start + max(flow, Decimal('0')) / 2


def _pct(gain: Decimal, capital: Decimal) -> Decimal:
    return gain / capital * 100 if capital >= MIN_BASE_USD else Decimal('0')


# Zero-flow markers (Futuros costs, fills, closes): a snapshot's Futuros
# equity is recomputed from the episodes as they stand now at the marks it
# was taken with (a funding payment synced after it counts before it), so
# only the money that moved before it must still be what the ledger says.
_MARKERS = ('perps_mark', 'perps_close')


def flow_signature(ledger, before: datetime) -> str:
    rows = sorted(f'{t.symbol}|{t.kind}|{t.units}|{t.usd}|{t.when.timestamp()}'
                  for t in ledger.all if t.when < before and t.kind not in _MARKERS)
    return hashlib.sha1('\n'.join(rows).encode()).hexdigest()


def _live_parts(ledger, now: datetime) -> tuple[Decimal, dict]:
    """(stocks + Bitcoin & gold now, {coin: Futuros mark now})."""
    other = live_value(replace(ledger, perps=[], perps_rows=[]), now)
    marks = {}
    if ledger.perps:
        from cusd_plus.perps_portfolio import live_marks

        try:
            marks = live_marks({e.coin for e in ledger.perps})
        except Exception as exc:  # noqa: BLE001
            raise Retry('perps marks unavailable') from exc
    return other, {coin: str(mark) for coin, mark in marks.items() if mark is not None}


def _perps_value(ledger, at: datetime, marks: dict) -> Decimal:
    from cusd_plus.perps_portfolio import equity_at

    def mark(coin):
        if marks.get(coin) is None:
            raise Retry(f'no mark for {coin}')
        return Decimal(marks[coin])

    return sum((equity_at(e, at, mark) for e in ledger.perps), Decimal('0'))


def _check_landing(ledger) -> None:
    """Futuros money back as dollars but not entered yet (proceeds landed,
    or a refunded opening): the ledger still values it at what left or the
    venue settled, not what arrived. Unknown until it enters, never the
    wrong number."""
    for ep in ledger.perps:
        state = getattr(ep, 'state', None)
        if state == 'landed' or (state == 'refunded' and getattr(ep, 'returned', None) is None):
            raise Retry('Futuros money landing')


def _snapshot_value(snap, ledger) -> Decimal:
    """What the sleeve was worth at the snapshot, Futuros re-valued on the
    episodes as the ledger has them now."""
    return snap.other_usd + _perps_value(ledger, snap.at, snap.perps_marks or {})


# --- snapshots ---------------------------------------------------------------

def snapshot_wallet(user, wallet: str, now: datetime, prices: PriceBook) -> bool:
    """Store the sleeve's value now. False when it can't be stated (the
    next run tries again)."""
    from .models import PortfolioValueSnapshot

    try:
        ledger = trusted_ledger(wallet, prices)
        if not ledger.all:
            return False
        _check_landing(ledger)
        other, marks = _live_parts(ledger, now)
        value = other + _perps_value(ledger, now, marks)
    except (Retry, Untrusted) as exc:
        logger.info('rolling: no snapshot for %s: %s', wallet, exc)
        return False
    PortfolioValueSnapshot.objects.create(user=user, wallet=wallet, at=now, value_usd=value.quantize(Q6),
                                          other_usd=other.quantize(Q6), perps_marks=marks,
                                          ledger_sig=flow_signature(ledger, now))
    return True


def snapshot_all(*, budget_seconds: float) -> dict:
    from .models import PortfolioValueSnapshot

    deadline = time_module.monotonic() + budget_seconds
    prices = PriceBook()     # fills the block-time cache profile reads use
    totals = {'written': 0, 'skipped': 0, 'errors': 0, 'deferred': 0}
    pairs = wallets_to_snapshot()
    random.shuffle(pairs)      # a slow wallet never starves the same ones every run
    for i, (user, wallet) in enumerate(pairs):
        if time_module.monotonic() > deadline:
            totals['deferred'] = len(pairs) - i
            break
        try:
            totals['written' if snapshot_wallet(user, wallet, timezone.now(), prices) else 'skipped'] += 1
        except Exception:  # noqa: BLE001 — one wallet never stops the rest
            logger.exception('rolling: snapshot failed for %s', wallet)
            totals['errors'] += 1
    PortfolioValueSnapshot.objects.filter(at__lt=timezone.now() - KEEP).delete()
    return totals


# --- the result ----------------------------------------------------------------

def _window_start(wallet: str, ledger, range_key: str, now: datetime) -> tuple[datetime, Decimal]:
    """(start instant, sleeve value then) for a range. Raises Retry when it
    can't be stated."""
    from .models import PortfolioDailySnapshot, PortfolioValueSnapshot

    today = utc_today(now)
    if range_key in WINDOWS:
        cutoff = now - WINDOWS[range_key]
        if all(t.when >= cutoff for t in ledger.all):
            return cutoff, Decimal('0')            # first trade inside the window
        base = (PortfolioValueSnapshot.objects
                .filter(wallet=wallet, at__lte=cutoff, at__gte=cutoff - START_TOLERANCE)
                .order_by('-at').first())
        if base is not None and base.ledger_sig == flow_signature(ledger, base.at):
            return base.at, _snapshot_value(base, ledger)
        if range_key == '24h':
            raise Retry('no snapshot 24 h ago')
        # Until snapshots go back far enough: from the midnight before.
        start = day_start(utc_today(cutoff))
    elif range_key == 'month':
        start = day_start(today.replace(day=1))
    else:
        raise ValueError(range_key)
    if all(t.when >= start for t in ledger.all):
        return start, Decimal('0')
    row = PortfolioDailySnapshot.objects.filter(wallet=wallet, day=start.date() - DAY).first()
    if not _is_shown(row, ledger) or row.value_end_usd is None:
        raise Retry(f'no proven close at {start.isoformat()}')
    return start, row.value_end_usd


def _points(wallet: str, ledger, range_key: str, start_at: datetime, value_start: Decimal, now: datetime) -> list:
    """(instant, cumulative %) through the range: every proven midnight in
    it, then the snapshots since (all of them over 24 h)."""
    from .models import PortfolioDailySnapshot, PortfolioValueSnapshot

    values = []
    since = start_at
    if range_key != '24h':
        for row in PortfolioDailySnapshot.objects.filter(
                wallet=wallet, day__gte=start_at.date(), day__lt=utc_today(now)).order_by('day'):
            end = day_start(row.day + DAY)
            if start_at < end < now and row.value_end_usd is not None and _is_shown(row, ledger):
                values.append((end, row.value_end_usd))
        since = max(start_at, day_start(utc_today(now)))
    for snap in PortfolioValueSnapshot.objects.filter(wallet=wallet, at__gt=since, at__lt=now).order_by('at'):
        if snap.ledger_sig == flow_signature(ledger, snap.at):
            values.append((snap.at, _snapshot_value(snap, ledger)))
    points = [(start_at, Decimal('0'))]
    for at, value in values:
        flow = _flows(ledger, start_at, at)
        points.append((at, _pct(value - value_start - flow, _capital(value_start, flow))))
    return points


def results(wallet: str, ranges, now: datetime | None = None, prices: PriceBook | None = None,
            with_points: bool = False) -> dict:
    """{range: Rolling or None} for one wallet, read once. Block times come
    from the cache only (a miss is unknown, never an RPC wait)."""
    now = now or timezone.now()
    prices = prices or CachedBlockTimes()
    out = {r: None for r in ranges}
    try:
        ledger = trusted_ledger(wallet, prices)
        if not ledger.all:
            return out
        _check_landing(ledger)
        value_end = live_value(ledger, now)
    except (Retry, Untrusted) as exc:
        logger.info('rolling: no result for %s: %s', wallet, exc)
        return out
    for range_key in ranges:
        if range_key == 'all':
            out['all'] = _total(ledger, value_end, now)
            continue
        try:
            start_at, value_start = _window_start(wallet, ledger, range_key, now)
            flow = _flows(ledger, start_at, now)
            points = _points(wallet, ledger, range_key, start_at, value_start, now) if with_points else []
        except (Retry, Untrusted) as exc:
            logger.info('rolling: no %s for %s: %s', range_key, wallet, exc)
            continue
        gain = value_end - value_start - flow
        capital = _capital(value_start, flow)
        pct = _pct(gain, capital)
        if with_points:
            points.append((now, pct))
        out[range_key] = Rolling(gain=gain, pct=pct, capital=capital, value_start=value_start, start_at=start_at,
                                 as_of=now, points=points)
    return out


def _total(ledger, value_end: Decimal, now: datetime) -> Rolling | None:
    """All time: nothing held before the first trade."""
    first = min(t.when for t in ledger.all)
    try:
        flow = _flows(ledger, first, now)
    except Untrusted:
        return None
    bought = sum((t.usd for t in ledger.all if t.kind.endswith('_buy') and t.when < now), Decimal('0'))
    gain = value_end - flow
    pct = gain / bought * 100 if bought >= MIN_BASE_USD else Decimal('0')
    return Rolling(gain=gain, pct=pct, capital=bought, value_start=Decimal('0'), start_at=first, as_of=now,
                   points=[(first, Decimal('0')), (now, pct)])


def rolling(wallet: str, now: datetime | None = None, prices: PriceBook | None = None,
            with_points: bool = False, range_key: str = '24h') -> Rolling | None:
    """One range (the last 24 hours by default), or None when it can't be
    stated exactly."""
    return results(wallet, [range_key], now, prices, with_points)[range_key]
