"""Card rules (decision 35, spec 4.4 / 4.6 / 4.7).

A Card rule lets a card issuer's spender, allowlisted by the Safe in the
factory, pull up to `amountUsd` (gross of the 0.9% exit fee) per fixed period
of the frequency's minimum gap (1, 7, 14 or 28 days) from the rule's first
run. The relayer never runs it (executeRule reverts BadRule); the server only
mirrors it, tells the owner about each pull, and lets the owner create
(behind SMART_ACCOUNT_CARD_RULES_ENABLED) and stop it.

The mirror follows the contract's own arithmetic, event by event:
  - RuleCreated: period start = max(firstRunAt, block time), count 0;
  - RuleUpdated: period start = max(firstRunAt, block time), count KEPT;
  - CardPulled: a pull at or after start + gap moves the start to the period
    containing it (missed periods skipped) and resets the count; then the
    gross is added.
Display reads the current period lazily (current_period): a count whose
period ended is in effect zero, exactly as cardSpentUsd is stale on chain.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.conf import settings
from django.utils import timezone

from . import abi, chain

WAD = 10 ** 18
CENT = Decimal('0.01')


def creation_enabled() -> bool:
    """Owners may prepare (create or edit) a Card rule. Off until a card
    issuer exists; stopping a Card rule never depends on it."""
    return bool(getattr(settings, 'SMART_ACCOUNT_CARD_RULES_ENABLED', False))


def gap(frequency: str) -> timedelta:
    return timedelta(days=abi.MIN_GAP_DAYS[frequency])


def period_days(frequency: str) -> int:
    return abi.MIN_GAP_DAYS[frequency]


def first_period_start(block_time, chain_next_run_at, frequency: str, first_run_at: int | None = None):
    """The period start a createRule / updateRule stored, as the contract
    does: max(firstRunAt, block time). firstRunAt comes from the calldata
    Confío prepared; without it (a rule made outside Confío) it is inferred
    from the chain's current nextRunAt, which only pulls move, by whole
    periods from that start."""
    block_ts = int(block_time.timestamp())
    if first_run_at is not None:
        return chain.to_dt(max(int(first_run_at), block_ts))
    latest = int(chain_next_run_at or 0)
    step = int(gap(frequency).total_seconds())
    if latest <= block_ts or (latest - block_ts) % step == 0:
        # Started at the block (firstRunAt not in the future), possibly
        # moved on by pulls since.
        return chain.to_dt(block_ts)
    return chain.to_dt(latest)


def apply_pull(rule, block_time, gross: Decimal):
    """Mirror one cardPull on `rule` (not saved). Returns (period start,
    gross taken in that period after this pull)."""
    start = rule.next_run_at or block_time
    step = gap(rule.frequency)
    spent = Decimal(rule.card_spent_usd or 0)
    if block_time >= start + step:
        start = start + ((block_time - start) // step) * step
        spent = Decimal(0)
    spent += gross
    rule.next_run_at = start
    rule.card_spent_usd = spent
    return start, spent


def current_period(rule, now=None):
    """(start, end, gross taken) of the period running now, from the mirror.
    Before the first period starts, that first period with nothing taken."""
    now = now or timezone.now()
    start = rule.next_run_at
    if start is None:
        return None, None, Decimal(0)
    step = gap(rule.frequency)
    spent = Decimal(rule.card_spent_usd or 0)
    if now >= start + step:
        start = start + ((now - start) // step) * step
        spent = Decimal(0)
    return start, start + step, spent


def remaining_usd(cap, spent) -> Decimal:
    """Room left in a period, to the cent, never negative."""
    left = Decimal(cap) - Decimal(spent)
    return max(Decimal(0), left).quantize(CENT, rounding=ROUND_DOWN)


def money(value) -> str:
    return format(Decimal(value).quantize(CENT), 'f')


def spender_row(address: str):
    from .models import SmartAccountCardSpender
    return SmartAccountCardSpender.objects.filter(address=(address or '').lower()).first()


def spender_label(address: str) -> str:
    row = spender_row(address)
    return row.display_label if row is not None else 'Tu tarjeta'


def allowed_spender(address: str):
    """The mirrored spender row when the factory allows it and cards are not
    paused (the mirror's view of cardSpenderAllowed), else None."""
    from .models import SmartAccountCardPause
    row = spender_row(address)
    if row is None or not row.allowed or SmartAccountCardPause.is_paused():
        return None
    return row


def first_run_from_calls(calls, target: str, onchain_id: int | None = None) -> int | None:
    """firstRunAt of the createRule / updateRule in a prepared batch (the
    calldata the owner signed), or None."""
    for call in calls or []:
        if str(call.get('to') or '').lower() != (target or '').lower():
            continue
        try:
            name, args = abi.decode_call(call.get('data') or '')
        except ValueError:
            continue
        if name == 'createRule':
            return int(args[0][7])
        if name == 'updateRule' and (onchain_id is None or int(args[0]) == int(onchain_id)):
            return int(args[1][7])
    return None
