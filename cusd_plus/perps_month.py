"""Tu mes "Futuros": what the account's Futuros did in one month.

    gain = value at month end − value at month start − margin put in + money back

The twin of stock_month.py / crypto_month.py, in the member's own money:
- "Margin put in" is the dollars that left for Futuros this month (the 0.9%
  exit included), "money back" the dollars that came home (after the 0.9%
  entry) or a refunded top-up. Never the leveraged exposure: a 10x position
  on $100 moved $100 of the member's money, not $1,000.
- Values come from the same episodes and valuation Liga uses
  (perps_portfolio.episodes / equity_at, half-open in time): a past month
  boundary at the perp's daily close, the current month at the live mark.
- Anything unknown is None (the card hides, never a guessed number); money
  on the wire (a bridge, a return) makes the current month 'settling'.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)


@dataclass
class PerpsMonth:
    state: str                         # 'gain' | 'settling' | 'none'
    value_end: Decimal = Decimal('0')
    value_start: Decimal | None = None
    bought: Decimal | None = None      # margin put in this month (the member's dollars)
    sold: Decimal | None = None        # dollars back this month
    gain: Decimal | None = None
    gain_pct: Decimal | None = None    # gain / (value at start + margin put in)
    positions: int = 0                 # positions holding money at the end of the window


IN_TRANSIT_STATES = ('bridging', 'returning')


def perps_month(bsc_address: str, start: datetime, end: datetime, now: datetime) -> PerpsMonth | None:
    """The viewed month [start, end) of this wallet's Futuros, or None (unknown)."""
    from inbox.portfolio_returns import PriceBook, Retry, _settled_episode

    from .perps_portfolio import PerpsLedgerUnknown, batches_in_flight, episodes, equity_at, live_marks

    if not bsc_address:
        return PerpsMonth(state='none')
    current = end > now
    try:
        from blockchain.models import PerpMarginChange

        # Money on the wire: a batch not yet final (even a first open, before
        # any episode exists) or a confirmed top-up still on the bridge.
        in_flight = (batches_in_flight(bsc_address).exists()
                     or PerpMarginChange.objects.filter(position__wallet=bsc_address.lower(),
                                                        state='bridging').exists())
        eps = episodes(bsc_address)
        if current and in_flight:
            return PerpsMonth(state='settling')
        if not eps:
            return PerpsMonth(state='none')
        prices = PriceBook()
        eps = [_local_settled(_settled_episode(ep, prices), prices, (start, end)) for ep in eps]
        if current and any(ep.state in IN_TRANSIT_STATES for ep in eps):
            return PerpsMonth(state='settling')
        touched = [ep for ep in eps
                   if ep.opened_at < end and (ep.returned is None or ep.returned[0] >= start)]
        if not touched:
            return PerpsMonth(state='none')

        def close_at(when):
            return lambda coin: _close_before(prices, coin, when, now)

        if current:
            marks = live_marks({ep.coin for ep in touched})

            def end_price(coin):
                if marks.get(coin) is None:
                    raise Retry(f'no live mark for {coin}')
                return marks[coin]
            end_at = now
        else:
            end_price = close_at(end)
            end_at = end
        value_start = sum((equity_at(ep, start, close_at(start)) for ep in touched), Decimal('0'))
        value_end = sum((equity_at(ep, end_at, end_price) for ep in touched), Decimal('0'))
        margin_in = sum((usd for ep in touched for when, usd, _ in ep.put_in if start <= when < end),
                        Decimal('0'))
        back = Decimal('0')
        for ep in touched:
            if ep.returned is not None and start <= ep.returned[0] < end:
                back += ep.returned[1]
            back += sum((usd for when, usd, _ in ep.refunds if start <= when < end), Decimal('0'))
        gain = value_end - value_start - margin_in + back
        base = value_start + margin_in
        positions = sum(1 for ep in touched if equity_at(ep, end_at, end_price) > 0)
        return PerpsMonth(state='gain', value_end=value_end, value_start=value_start, bought=margin_in,
                          sold=back, gain=gain, gain_pct=(gain / base * 100) if base > 0 else None,
                          positions=positions)
    except (PerpsLedgerUnknown, Retry) as exc:
        logger.info('perps month unavailable for %s: %s', bsc_address, exc)
        return None


def _close_before(prices, coin: str, boundary: datetime, now: datetime) -> Decimal:
    """The perp's last completed daily close at or before a month boundary.
    The boundary is the member's local midnight (Bolivia: 04:00 UTC) while
    candles close at 00:00 UTC, so an exact match is the exception; perps
    trade every day, so that close is never more than a day old."""
    from inbox.portfolio_returns import DAY, Retry

    series = prices._series('perp', coin)
    if series is None:
        raise Retry(f'no candles for {coin}')
    before = [row for row in series if row[0] <= now and row[0] <= boundary]
    if not before or boundary - before[-1][0] > DAY:
        raise Retry(f'no close for {coin} before {boundary.isoformat()}')
    return before[-1][1]


def _local_settled(ep, prices, boundaries):
    """_settled_episode corrects a batch recorded just before UTC midnight;
    the month's boundaries are local midnights, so a batch recorded just
    before one of them is moved to when its block landed too (Oct 31 23:59
    in Bolivia, landed Nov 1 00:01, is November's)."""
    from dataclasses import replace

    from inbox.portfolio_returns import NEAR_MIDNIGHT, Retry

    def settled(when, block):
        if not any(timedelta(0) <= b - when <= NEAR_MIDNIGHT for b in boundaries):
            return when
        if block is None:
            raise Retry('confirmed perps batch without a block')
        landed = prices.block_time(block)
        if landed is None:
            raise Retry(f'no time for block {block}')
        return landed

    moved = {when: settled(when, block) for when, _usd, block in ep.put_in}
    put_in = sorted(((moved[when], usd, block) for when, usd, block in ep.put_in), key=lambda r: r[0])
    pending = [(moved.get(start, start), until, usd, arrived, applied)
               for start, until, usd, arrived, applied in ep.pending_topups]
    returned = ep.returned
    if returned is not None and returned[2] is not None:
        returned = (settled(returned[0], returned[2]), returned[1], returned[2])
    return replace(ep, put_in=put_in, returned=returned, pending_topups=pending)
