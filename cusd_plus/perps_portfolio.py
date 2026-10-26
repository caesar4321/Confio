"""Futuros in Comunidad: the investor profile, the all-time Total and the
Liga (inbox/member_portfolio.py, inbox/portfolio_returns.py).

A position enters the sleeve when its margin leaves Confío dollars and
leaves it when its proceeds come back in, both exact from their history rows
(the perimeter fee included, so costs lower the return). In between it is
worth its equity on Hyperliquid:

    open:   credited margin + size × (price − entry)
    closed: credited margin + realized P&L − venue fees + funding (as settled)
    after a liquidation with nothing to return: 0

Each episode is also a pair of ledger rows ('perps_buy' / 'perps_sell', one
unit) so the period engine's flows and signatures cover it like any trade.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.utils import timezone

logger = logging.getLogger(__name__)

SYMBOL_PREFIX = 'perp:'
IN_FLIGHT_MAX_AGE = timedelta(minutes=35)


class PerpsLedgerUnknown(Exception):
    """A confirmed perps batch has no exact settlement yet."""


@dataclass
class Episode:
    position_id: int
    coin: str
    ticker: str
    side: str
    leverage: int
    state: str
    put_in: list                       # [(when, usd, block)] margin out of Confío dollars
    returned: tuple | None             # (when, usd, block) proceeds back in, or None
    credited: Decimal | None
    entry_px: Decimal | None
    size_signed: Decimal | None
    closed_at: object | None
    settled_equity: Decimal | None
    liquidated: bool
    # Margin added on the venue after the open: [(when, usd)], so a past day
    # is valued with the margin it had THEN.
    credit_events: list = field(default_factory=list)
    credited_initial: Decimal | None = None
    # Partial closes: [(when, signed size from then, realized P&L so far)].
    size_events: list = field(default_factory=list)
    # Top-ups Relay refunded (USDT back to dollars): [(when, usd, None)].
    refunds: list = field(default_factory=list)
    # When the order filled: market exposure starts here, not at funding.
    filled_at: object | None = None
    # Open-position costs, dated: [(when, funding paid so far, fees so far)].
    cost_events: list = field(default_factory=list)
    # Top-ups between leaving dollars and joining the margin (or coming back):
    # [(from, until or None, usd, arrived, applied)], so the money is never
    # missing meanwhile. arrived: on the member's Hyperliquid balance (not in
    # transit); applied: it joined the margin (so a close's settled value
    # already holds it).
    pending_topups: list = field(default_factory=list)

    @property
    def symbol(self) -> str:
        return f'{SYMBOL_PREFIX}{self.position_id}'

    @property
    def label(self) -> str:
        side = 'Largo' if self.side == 'long' else 'Corto'
        return f'{self.ticker} · {side} {self.leverage}x'

    @property
    def invested(self) -> Decimal:
        return sum((row[1] for row in self.put_in), Decimal(0))

    @property
    def refunded(self) -> Decimal:
        """Top-ups Relay sent back (they returned to dollars on their own)."""
        return sum((row[1] for row in self.refunds), Decimal(0))

    @property
    def opened_at(self):
        return self.put_in[0][0]


def _history_usd(batch) -> Decimal | None:
    from django.core.exceptions import ObjectDoesNotExist

    try:
        row = batch.unified_transaction
    except ObjectDoesNotExist:
        return None
    if row is None or row.deleted_at is not None or row.status != 'CONFIRMED':
        return None
    try:
        return Decimal(str(row.amount))
    except (ArithmeticError, TypeError, ValueError):
        return None


def _after_entry_fee(usd: Decimal) -> Decimal:
    """Refunded USDT re-enters Confío dollars through the ordinary entry
    (the sweep), paying the perimeter fee like any return."""
    try:
        from .crypto_policy import live_fee_bps
        bps = live_fee_bps()
    except Exception:  # noqa: BLE001 — the configured perimeter fee
        bps = 90
    return usd - (usd * bps / Decimal(10_000))


def episodes(wallet: str) -> list[Episode]:
    """Every position whose margin actually left Confío dollars."""
    from blockchain.models import PerpPosition

    from . import perps_catalog

    out = []
    rows = (PerpPosition.objects.filter(wallet=(wallet or '').lower(), open_batch__status='confirmed')
            .exclude(state='failed')
            .select_related('market', 'open_batch__unified_transaction', 'return_batch__unified_transaction')
            .prefetch_related('margin_changes__batch__unified_transaction').order_by('created_at'))
    for p in rows:
        usd = _history_usd(p.open_batch)
        if usd is None:
            raise PerpsLedgerUnknown(f'position {p.id} open has no settlement row')
        put_in = [(p.open_batch.created_at, usd, p.open_batch.block_number)]
        refunds = []
        pending = []
        ambiguous = False
        applied_at = {}
        for event in (p.flow or {}).get('credit_events') or []:
            if event.get('change_id') is not None:
                try:
                    applied_at[int(event['change_id'])] = datetime.fromisoformat(event['at'])
                except (KeyError, TypeError, ValueError):
                    raise PerpsLedgerUnknown(f'position {p.id} has an unreadable margin event')
        for change in p.margin_changes.all():
            if change.direction != 'add' or change.batch is None or change.batch.status != 'confirmed':
                continue
            add = _history_usd(change.batch)
            if add is None:
                raise PerpsLedgerUnknown(f'margin change {change.id} has no settlement row')
            put_in.append((change.batch.created_at, add, change.batch.block_number))
            in_flight_usd = Decimal(str((change.flow or {}).get('credited') or add))
            if change.state == 'done' and not (change.flow or {}).get('unapplied'):
                pending.append((change.batch.created_at, applied_at.get(change.id, change.updated_at),
                                in_flight_usd, False, True))
            elif change.state == 'refunded':
                pending.append((change.batch.created_at, change.updated_at, in_flight_usd, False, False))
            elif change.state == 'bridging':
                pending.append((change.batch.created_at, None, in_flight_usd, False, False))
            elif (change.flow or {}).get('ambiguous'):
                # Applied or not before the close, unknowable: counted with the
                # position until the close, then held by the venue's own
                # balance at the return (settled below).
                ambiguous = True
                pending.append((change.batch.created_at, None, in_flight_usd, True, True))
            elif change.state == 'funded' or (change.flow or {}).get('unapplied'):
                # Arrived, never applied: still this position's money, dated by
                # its own batch (never folded into the close's settled value).
                pending.append((change.batch.created_at, None, in_flight_usd, True, False))
            if change.state == 'refunded':
                # The USDT that actually came back (Relay keeps its refund gas),
                # net of the entry fee it pays going back into dollars.
                back = _after_entry_fee(Decimal(int((change.flow or {}).get('refund_wei') or 0)) / Decimal(10 ** 18))
                refunds.append((change.updated_at, back, None))
        flow = p.flow or {}
        returned = None
        if p.state == 'cancelled':
            # A refund the member kept: the USDT went back to dollars.
            refunded_at = flow.get('refunded_at')
            when = (datetime.fromtimestamp(int(refunded_at), tz=dt_timezone.utc) if refunded_at
                    else p.updated_at)
            back = _after_entry_fee(Decimal(int(flow.get('refund_wei') or 0)) / Decimal(10 ** 18))
            returned = (when, back, None)
        elif p.return_batch is not None and p.return_batch.status == 'confirmed':
            back = p.returned_usd
            if back is None:
                raise PerpsLedgerUnknown(f'position {p.id} return has no settled share')
            returned = (p.return_batch.created_at, Decimal(back), p.return_batch.block_number)
        elif p.state == 'done':
            # A liquidation with nothing to bring home ends here.
            returned = (p.done_at or p.closed_at or p.updated_at, Decimal(0), None)
        settled = None
        if p.closed_at is not None and p.credited_usdc is not None:
            settled = (Decimal(p.credited_usdc) + Decimal(p.realized_pnl or 0)
                       - Decimal(p.venue_fees or 0) + Decimal(p.funding or 0))
            if settled < 0:
                settled = Decimal(0)
        if ambiguous and p.closed_at is not None:
            truth = flow.get('venue_free_at_return')
            if truth is None:
                raise PerpsLedgerUnknown(f'position {p.id} top-up outcome is settled at its return')
            settled = Decimal(str(truth))
        size = None
        initial_size = flow.get('size_initial') or p.size
        if initial_size is not None:
            # The size at the fill: partial closes move it later (size_events).
            size = Decimal(str(initial_size)) * (1 if p.side == 'long' else -1)
        events = []
        for event in flow.get('credit_events') or []:
            try:
                events.append((datetime.fromisoformat(event['at']), Decimal(str(event['usd']))))
            except (KeyError, TypeError, ValueError, ArithmeticError):
                raise PerpsLedgerUnknown(f'position {p.id} has an unreadable margin event')
        initial = flow.get('credited_initial')
        costs = []
        for event in flow.get('cost_events') or []:
            try:
                costs.append((datetime.fromisoformat(event['at']), Decimal(str(event['funding_paid'])),
                              Decimal(str(event['fees']))))
            except (KeyError, TypeError, ValueError, ArithmeticError):
                raise PerpsLedgerUnknown(f'position {p.id} has an unreadable cost event')
        sizes = []
        sign = 1 if p.side == 'long' else -1
        for event in flow.get('size_events') or []:
            try:
                sizes.append((datetime.fromisoformat(event['at']), Decimal(str(event['size'])) * sign,
                              Decimal(str(event['realized'])),
                              Decimal(str(event['entry'])) if event.get('entry') is not None else None))
            except (KeyError, TypeError, ValueError, ArithmeticError):
                raise PerpsLedgerUnknown(f'position {p.id} has an unreadable size event')
        out.append(Episode(
            position_id=p.id, coin=p.market.coin, ticker=perps_catalog.ticker_of(p.market.coin),
            side=p.side, leverage=p.leverage, state=p.state, put_in=sorted(put_in, key=lambda r: r[0]),
            returned=returned, credited=Decimal(p.credited_usdc) if p.credited_usdc is not None else None,
            entry_px=Decimal(p.entry_avg_px) if p.entry_avg_px is not None else None,
            size_signed=size, closed_at=p.closed_at, settled_equity=settled, liquidated=bool(p.liquidation),
            credit_events=sorted(events, key=lambda e: e[0]),
            credited_initial=Decimal(str(initial)) if initial else None,
            # Stable by time: fills in the same millisecond keep their own order.
            size_events=sorted(sizes, key=lambda e: e[0]), refunds=refunds,
            filled_at=(datetime.fromtimestamp(int(flow['entry_fill_ms']) / 1000, tz=dt_timezone.utc)
                       if flow.get('entry_fill_ms') else p.opened_at),
            cost_events=costs, pending_topups=pending,
        ))
    return out


def ledger_trades(episodes_: list[Episode]) -> list:
    """The episodes as period-engine rows (cusd_plus/stock_month.Trade)."""
    from .stock_month import Trade

    rows = []
    for ep in episodes_:
        for i, (when, usd, block) in enumerate(ep.put_in):
            rows.append(Trade(symbol=ep.symbol, kind='perps_buy', units=Decimal(1 if i == 0 else 0),
                              usd=usd, when=when, block=block))
        if ep.closed_at is not None:
            # Zero-flow marker: a close re-settles the days it touches, and so
            # does any later correction of its settled value (it is carried here).
            rows.append(Trade(symbol=ep.symbol, kind='perps_close',
                              units=(ep.settled_equity if ep.settled_equity is not None else Decimal(-1)),
                              usd=Decimal(0), when=ep.closed_at))
        for when, usd, _ in ep.refunds:
            rows.append(Trade(symbol=ep.symbol, kind='perps_sell', units=Decimal(0), usd=usd, when=when))
        # Zero-flow markers: anything that changes a past day's valuation
        # (fill, top-up applied, partial close) changes the signature too.
        if ep.entry_px is not None and ep.size_signed is not None:
            rows.append(Trade(symbol=ep.symbol, kind='perps_mark', units=abs(ep.size_signed) + ep.entry_px,
                              usd=Decimal(0), when=ep.filled_at or ep.opened_at))
        if ep.credited_initial is not None or ep.credited is not None:
            # What the bridge credited values every day from the deposit on:
            # a settlement after a snapshot must change the signature too.
            rows.append(Trade(symbol=ep.symbol, kind='perps_mark',
                              units=(ep.credited_initial if ep.credited_initial is not None else ep.credited)
                              + Decimal('0.000001'), usd=Decimal(0), when=ep.opened_at))
        for start, until, usd, arrived, applied in ep.pending_topups:
            # A top-up's in-flight value, its end and whether it joined the
            # margin all value past days: any change must change the signature.
            rows.append(Trade(symbol=ep.symbol, kind='perps_mark',
                              units=usd + (1 if arrived else 0) + (2 if applied else 0),
                              usd=Decimal(0), when=start))
            if until is not None:
                rows.append(Trade(symbol=ep.symbol, kind='perps_mark', units=usd, usd=Decimal(0), when=until))
        for when, funding_paid, fees in ep.cost_events:
            rows.append(Trade(symbol=ep.symbol, kind='perps_mark', units=abs(funding_paid) + abs(fees),
                              usd=Decimal(0), when=when))
        for when, usd in ep.credit_events:
            rows.append(Trade(symbol=ep.symbol, kind='perps_mark', units=usd, usd=Decimal(0), when=when))
        for index, (when, size, realized, entry) in enumerate(ep.size_events):
            # Each part of the event is its own mark (size, realized, entry as of
            # the fill): any correction changes the signature and reopens its days.
            for name, part in (('size', abs(size)), ('realized', realized), ('entry', entry or Decimal(0))):
                # The event's place in order too: two fills in one millisecond stay distinct.
                rows.append(Trade(symbol=f'{ep.symbol}#{index}#{name}', kind='perps_mark', units=part, usd=Decimal(0),
                                  when=when))
        if ep.returned is not None:
            rows.append(Trade(symbol=ep.symbol, kind='perps_sell', units=Decimal(1),
                              usd=ep.returned[1], when=ep.returned[0], block=ep.returned[2]))
    return sorted(rows, key=lambda t: t.when)


def equity_at(ep: Episode, when, price_at) -> Decimal:
    """The episode's worth at `when` (0 outside it). `price_at(coin)` is the
    price to mark an open position with; it may raise to defer the day.

    Every event counts half-open, as the ledger's flows and signature do: an
    event at time t shapes valuations strictly after t, so one at exactly
    midnight belongs to the new day on both sides of the return calculation."""
    if when <= ep.opened_at:
        return Decimal(0)
    if ep.returned is not None and when > ep.returned[0]:
        return Decimal(0)
    if ep.closed_at is not None and when > ep.closed_at:
        settled = ep.settled_equity if ep.settled_equity is not None else Decimal(0)
        # Settled already holds every top-up that joined the margin, however
        # late its acknowledgement: only the never-applied ones add here.
        return settled + topups_in_flight(ep, when, exclude_applied=True)
    if (ep.credited is None or ep.entry_px is None or ep.size_signed is None
            or ep.filled_at is None or when <= ep.filled_at):
        # Bridging or not yet filled: what it is credited (or the dollars that left).
        if ep.credited is not None and (ep.filled_at is None or when <= ep.filled_at):
            return credited_at(ep, when)
        return sum((row[1] for row in ep.put_in if row[0] < when), Decimal(0))
    size, realized, entry = ep.size_signed, Decimal(0), ep.entry_px
    for at, event_size, event_realized, event_entry in ep.size_events:
        if at < when:
            size, realized = event_size, event_realized
            # The entry as of that fill (a limit entry filling in parts);
            # older events carry none and keep the position's entry.
            entry = event_entry if event_entry is not None else entry
    paid = fees = Decimal(0)
    for at, funding_paid, fees_so_far in ep.cost_events:
        # Half-open, as the ledger signature: a cost at exactly midnight is the
        # new day's (one event per UTC day keeps the day's last).
        if at < when:
            paid, fees = funding_paid, fees_so_far
    base = credited_at(ep, when) + realized - paid - fees + topups_in_flight(ep, when)
    if size == 0:
        return max(base, Decimal(0))
    return max(base + size * (price_at(ep.coin) - entry), Decimal(0))


def topups_in_flight(ep: Episode, when, exclude_applied: bool = False) -> Decimal:
    return sum((usd for start, until, usd, _arrived, applied in ep.pending_topups
                if start < when and (until is None or when <= until)
                and not (exclude_applied and applied)), Decimal(0))


def topups_now(ep: Episode, in_transit_only: bool = False, exclude_applied: bool = False) -> Decimal:
    """Top-ups not applied yet, right now: in transit (Relay), or also those
    already on the member's Hyperliquid balance."""
    return sum((usd for _start, until, usd, arrived, applied in ep.pending_topups
                if until is None and not (in_transit_only and arrived)
                and not (exclude_applied and applied)), Decimal(0))


def credited_at(ep: Episode, when) -> Decimal:
    """The isolated margin the position had at `when`."""
    if ep.credited_initial is None:
        return ep.credited or Decimal(0)
    return ep.credited_initial + sum((usd for at, usd in ep.credit_events if at < when), Decimal(0))


def batches_in_flight(wallet: str):
    from blockchain.models import PERPS_BATCH_KINDS, SponsoredBatch

    return SponsoredBatch.objects.filter(
        user_bsc_address__iexact=wallet, kind__in=PERPS_BATCH_KINDS, status__in=('signed', 'sent'),
        created_at__gte=timezone.now() - IN_FLIGHT_MAX_AGE)


@dataclass
class PerpsPart:
    total: Decimal | None
    open_positions: list | None
    closed: list = field(default_factory=list)       # (symbol, bought, sold, pnl, when)
    holds: list = field(default_factory=list)
    open_holds: list = field(default_factory=list)
    trades: list | None = field(default_factory=list)
    labels: dict = field(default_factory=dict)       # symbol -> display label
    landed_usd: Decimal = Decimal(0)                 # proceeds on BSC waiting for their entry


def live_part(wallet: str, now=None) -> PerpsPart:
    """Futuros for one profile: open positions valued live on Hyperliquid,
    closed episodes with their exact result. Proceeds that already landed as
    USDT on BSC are part of the member's dollars, never counted twice."""
    from . import hyperliquid
    from inbox.member_portfolio import OpenPosition

    now = now or timezone.now()
    try:
        eps = episodes(wallet)
    except PerpsLedgerUnknown:
        logger.info('portfolio: perps ledger not settled for %s', wallet)
        return PerpsPart(total=None, open_positions=None, trades=None)
    if not eps:
        return PerpsPart(total=Decimal(0), open_positions=[], trades=[])
    live, free = {}, {}
    dexes = {ep.coin.split(':')[0] if ':' in ep.coin else '' for ep in eps if ep.returned is None}
    try:
        withdrawable = {}
        for dex in sorted(dexes | ({''} if dexes else set())):
            state = hyperliquid.clearinghouse_state(wallet, dex)
            withdrawable[dex] = Decimal(str(state.get('withdrawable') or '0'))
            for entry in state['assetPositions']:
                pos = entry.get('position') or {}
                if pos.get('coin'):
                    live[pos['coin']] = pos
        for ep in eps:
            if ep.returned is None:
                dex = ep.coin.split(':')[0] if ':' in ep.coin else ''
                free[ep.coin] = withdrawable.get('', Decimal(0)) + (withdrawable.get(dex, Decimal(0)) if dex else 0)
    except hyperliquid.HyperliquidError:
        logger.warning('portfolio: Hyperliquid unreadable for %s', wallet)
        return PerpsPart(total=None, open_positions=None, trades=ledger_trades(eps))

    from blockchain.models import PerpPosition

    states = dict(PerpPosition.objects.filter(pk__in=[e.position_id for e in eps]).values_list('id', 'flow'))
    total = Decimal(0)
    in_transit = False
    landed = Decimal(0)
    positions, closed, holds, open_holds, labels = [], [], [], [], {}
    for ep in eps:
        labels[ep.symbol] = ep.label
        if ep.returned is not None:
            when, back, _ = ep.returned
            back = back + ep.refunded
            closed.append((ep.symbol, ep.invested, back, back - ep.invested, when))
            holds.append(int((when - ep.opened_at).total_seconds()))
            continue
        pos = live.get(ep.coin)
        if ep.state == 'bridging' or topups_now(ep, in_transit_only=True) > 0:
            # Money with Relay: once delivered (or refunded) it also shows in a
            # balance before the reconciler sees it — this moment's total is
            # not known, never counted twice.
            in_transit = True
        if ep.state == 'open' and pos is not None:
            # Its isolated margin plus whatever is free on the account: one
            # live position per member, so the rest (released margin, an
            # unapplied top-up, an unfilled part) is this position's too.
            # A top-up still with Relay may or may not already show on the
            # venue: while it is, the position's value and result are unknown.
            transit = topups_now(ep, in_transit_only=True)
            value = Decimal(str(pos.get('marginUsed') or '0')) + free.get(ep.coin, Decimal(0))
            size = Decimal(str(pos.get('szi') or '0'))
            # Refunded top-ups came back to dollars: part of the result, not a loss.
            pnl = None if transit > 0 else value + ep.refunded - ep.invested
            positions.append(OpenPosition(
                symbol=ep.symbol, ticker=ep.ticker, name=ep.label, units=abs(size), value_usd=value,
                invested_usd=ep.invested,
                avg_entry_usd=Decimal(str(pos['entryPx'])) if pos.get('entryPx') else None,
                pnl_usd=pnl,
                pnl_pct=pnl / ep.invested * 100 if pnl is not None and ep.invested > 0 else None,
            ))
            open_holds.append(int((now - ep.opened_at).total_seconds()))
            total += value
            continue
        flow = states.get(ep.position_id) or {}
        if ep.state == 'refunded':
            # Relay returned the USDT: it is on BSC (in the member's dollars).
            landed += Decimal(int(flow.get('refund_wei') or flow.get('deposit_wei') or 0)) / Decimal(10 ** 18)
            continue
        if ep.state == 'landed':
            # Already USDT in the member's dollars (counted there); the
            # sleeve's own result counts it until it enters (landed_usd).
            landed += Decimal(int(flow.get('landed_wei') or 0)) / Decimal(10 ** 18)
            continue
        if ep.state == 'returning':
            # On its way to BSC: once it lands it is also the member's USDT
            # (counted with the dollars) before the reconciler sees it, so
            # this moment's total is not known — never counted twice.
            in_transit = True
        elif ep.settled_equity is not None:
            # Settled holds every applied (or ambiguous, venue-settled) top-up.
            total += ep.settled_equity + topups_now(ep, exclude_applied=True)
        elif ep.credited is not None:
            total += ep.credited + topups_now(ep, exclude_applied=True)
        else:
            total += ep.invested
    if in_transit:
        total = None
    return PerpsPart(total=total, open_positions=positions, closed=closed, holds=holds, open_holds=open_holds,
                     trades=ledger_trades(eps), labels=labels, landed_usd=landed)


def live_marks(coins) -> dict:
    """coin -> live mark price (display cache, 15 s)."""
    from . import perps_market_data

    dexes = {c.split(':')[0] if ':' in c else '' for c in coins}
    ctx = perps_market_data.all_contexts(dexes)
    return {c: (ctx.get(c) or {}).get('mark_px') for c in coins}
