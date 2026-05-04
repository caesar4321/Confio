"""Helpers for linking USDCDeposit rows to Koywe RampTransactions.

Koywe sends crypto on-chain without populating any FK on the resulting
USDCDeposit, so the blockchain watcher creates an orphan deposit. We match
them up after the fact based on actor_user_id + actor_address + amount within
a small tolerance and a recent time window.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.db import transaction

from ramps.models import RampTransaction
from usdc_transactions.models import USDCDeposit


KOYWE_LINK_WINDOW = timedelta(hours=6)
KOYWE_AMOUNT_TOLERANCE_RATIO = Decimal('0.05')


def _candidate_amount(deposit_amount: Decimal, ramp: RampTransaction) -> Optional[Decimal]:
    """Return the absolute amount delta if any ramp amount field matches within tolerance."""
    tolerance = deposit_amount * KOYWE_AMOUNT_TOLERANCE_RATIO
    best_delta: Optional[Decimal] = None
    for amount in (ramp.final_amount, ramp.crypto_amount_actual, ramp.crypto_amount_estimated):
        if amount is None:
            continue
        delta = abs(Decimal(amount) - deposit_amount)
        if delta <= tolerance and (best_delta is None or delta < best_delta):
            best_delta = delta
    return best_delta


@transaction.atomic
def link_koywe_deposit_to_ramp(deposit: USDCDeposit) -> Optional[RampTransaction]:
    """Find an unlinked Koywe ramp matching this deposit and attach the FK.

    Returns the linked ramp on success, None when no match was found.
    Safe to call repeatedly; no-ops if the deposit is already linked.
    """
    if deposit.ramp_transaction_id:
        return None
    if not deposit.actor_user_id or not deposit.actor_address:
        return None
    if deposit.amount is None or Decimal(deposit.amount) <= 0:
        return None

    pivot = deposit.completed_at or deposit.updated_at or deposit.created_at
    if not pivot:
        return None

    target = Decimal(deposit.amount)
    candidates = list(
        RampTransaction.objects.filter(
            provider='koywe',
            direction='on_ramp',
            actor_user_id=deposit.actor_user_id,
            actor_address=deposit.actor_address,
            usdc_deposit__isnull=True,
            created_at__gte=pivot - KOYWE_LINK_WINDOW,
            created_at__lte=pivot + KOYWE_LINK_WINDOW,
        ).exclude(status='FAILED').order_by('-created_at')
    )

    best: Optional[RampTransaction] = None
    best_delta: Optional[Decimal] = None
    for ramp in candidates:
        delta = _candidate_amount(target, ramp)
        if delta is None:
            continue
        if best_delta is None or delta < best_delta:
            best = ramp
            best_delta = delta
    if best is None:
        return None

    update_fields = ['usdc_deposit', 'updated_at']
    best.usdc_deposit = deposit
    if best.status == 'PENDING':
        best.status = 'PROCESSING'
        best.status_detail = 'deposit_confirmed_conversion_pending'
        update_fields.extend(['status', 'status_detail'])
    best.save(update_fields=update_fields)
    return best


@transaction.atomic
def link_koywe_ramp_to_deposit(ramp: RampTransaction) -> Optional[USDCDeposit]:
    """Reverse direction: when a Koywe ramp updates and still has no deposit,
    look for an unlinked USDCDeposit that matches.

    Returns the linked deposit on success, None when no match was found.
    """
    if ramp.usdc_deposit_id:
        return None
    if ramp.provider != 'koywe' or ramp.direction != 'on_ramp':
        return None
    if not ramp.actor_user_id or not ramp.actor_address:
        return None

    target = None
    for amount in (ramp.final_amount, ramp.crypto_amount_actual, ramp.crypto_amount_estimated):
        if amount is not None:
            target = Decimal(amount)
            break
    if target is None or target <= 0:
        return None

    pivot = ramp.completed_at or ramp.updated_at or ramp.created_at
    if not pivot:
        return None

    tolerance = target * KOYWE_AMOUNT_TOLERANCE_RATIO
    candidates = list(
        USDCDeposit.objects.filter(
            actor_user_id=ramp.actor_user_id,
            actor_address=ramp.actor_address,
            status='COMPLETED',
            is_deleted=False,
            ramp_transaction__isnull=True,
            created_at__gte=pivot - KOYWE_LINK_WINDOW,
            created_at__lte=pivot + KOYWE_LINK_WINDOW,
        ).order_by('-created_at')
    )

    best: Optional[USDCDeposit] = None
    best_delta: Optional[Decimal] = None
    for dep in candidates:
        if dep.amount is None:
            continue
        delta = abs(Decimal(dep.amount) - target)
        if delta <= tolerance and (best_delta is None or delta < best_delta):
            best = dep
            best_delta = delta
    if best is None:
        return None

    update_fields = ['usdc_deposit', 'updated_at']
    ramp.usdc_deposit = best
    if ramp.status == 'PENDING':
        ramp.status = 'PROCESSING'
        ramp.status_detail = 'deposit_confirmed_conversion_pending'
        update_fields.extend(['status', 'status_detail'])
    ramp.save(update_fields=update_fields)
    return best
