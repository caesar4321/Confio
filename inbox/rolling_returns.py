"""The rolling 24 h result: Liga's "24 h", the profile's line beside the
total and Rentabilidad > 24 h. Bitcoin, gold and Futuros trade around the
clock, so this is the last 24 hours, never a UTC day.

Every SNAPSHOT_EVERY each investing wallet's sleeve is valued live and
stored (PortfolioValueSnapshot) when the ledger explains the chain and
nothing is on the wire. The result now is

    gain = value now - value at the snapshot 24 h ago - money put in since

(buys minus sells, Futuros margin out minus proceeds in), and the % is that
over the money at work: the value it started with plus half of what came in
(the league's convention, so the % always has the dollars' sign).

Unknown is never a number: no snapshot near 24 h ago, one taken when the
money moved before it differs from what the ledger says now (a trade
confirmed or re-settled later), or anything the live value can't state
makes it None.
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

from .portfolio_returns import (MIN_BASE_USD, CachedBlockTimes, PriceBook, Retry, Untrusted, _flows, live_value,
                                trusted_ledger, wallets_to_snapshot)

logger = logging.getLogger(__name__)

WINDOW = timedelta(hours=24)
SNAPSHOT_EVERY = timedelta(minutes=10)
# The starting snapshot may be this much older than 24 h ago (a run that
# skipped a wallet): a little over 24 h, never a guess.
START_TOLERANCE = timedelta(minutes=30)
KEEP = timedelta(days=3)
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

def rolling(wallet: str, now: datetime | None = None, prices: PriceBook | None = None,
            with_points: bool = False) -> Rolling | None:
    """The last 24 hours, or None when it can't be stated exactly. Block
    times come from the cache only (a miss is unknown, never an RPC wait)."""
    from .models import PortfolioValueSnapshot

    now = now or timezone.now()
    prices = prices or CachedBlockTimes()
    cutoff = now - WINDOW
    try:
        ledger = trusted_ledger(wallet, prices)
        if not ledger.all:
            return None
        if all(t.when >= cutoff for t in ledger.all):
            # First trade inside the window: it started from nothing.
            start_at, value_start = cutoff, Decimal('0')
        else:
            base = (PortfolioValueSnapshot.objects
                    .filter(wallet=wallet, at__lte=cutoff, at__gte=cutoff - START_TOLERANCE)
                    .order_by('-at').first())
            if base is None or base.ledger_sig != flow_signature(ledger, base.at):
                return None
            start_at, value_start = base.at, _snapshot_value(base, ledger)
        value_end = live_value(ledger, now)
        flow = _flows(ledger, start_at, now)
        points = []
        if with_points:
            points.append((start_at, Decimal('0')))
            for snap in (PortfolioValueSnapshot.objects.filter(wallet=wallet, at__gt=start_at, at__lt=now)
                         .order_by('at')):
                if snap.ledger_sig != flow_signature(ledger, snap.at):
                    continue
                flow_then = _flows(ledger, start_at, snap.at)
                points.append((snap.at, _pct(_snapshot_value(snap, ledger) - value_start - flow_then,
                                             _capital(value_start, flow_then))))
    except (Retry, Untrusted) as exc:
        logger.info('rolling: no 24 h for %s: %s', wallet, exc)
        return None
    gain = value_end - value_start - flow
    capital = _capital(value_start, flow)
    pct = _pct(gain, capital)
    if with_points:
        points.append((now, pct))
    return Rolling(gain=gain, pct=pct, capital=capital, value_start=value_start, start_at=start_at, as_of=now,
                   points=points)
