"""Product evidence for the Venezuelan top-up: who saw a price, and why a
person cancelled. Analytics only: nothing here may fail or delay the quote or
the cancellation it describes."""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.utils import timezone

logger = logging.getLogger(__name__)

TOPUP_RAIL = 've_pagomovil_topup'
MAX_LOGGED_USD = Decimal('99999999999999999.99')

# One tap after cancelling. The app shows the labels; the server keeps the keys.
CANCEL_REASONS = ('fee', 'account', 'limit', 'later', 'looking', 'other')


def _money(value) -> Decimal | None:
    try:
        amount = Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount.is_finite() and 0 <= amount <= MAX_LOGGED_USD else None


def record_quote_view(user, rail: str, usd_amount, net_usd=None) -> bool:
    """Count a quote the person was shown. Never raises: a quote that could
    not be counted is still a quote."""
    from ramps.models import RampQuoteView
    from users.activity_tracking import activity_day

    amount = _money(usd_amount)
    if amount is None or not getattr(user, 'pk', None):
        return False
    net = _money(net_usd)
    now = timezone.now()
    try:
        # Its own savepoint: a failed insert must not poison the caller's transaction.
        with transaction.atomic():
            row, created = RampQuoteView.objects.get_or_create(
                user_id=user.pk, rail=rail, day=activity_day(now),
                defaults={'first_usd': amount, 'last_usd': amount, 'max_usd': amount, 'last_net_usd': net,
                          'country': (getattr(user, 'country', '') or '')[:2],
                          'first_seen_at': now, 'last_seen_at': now})
            if not created:
                RampQuoteView.objects.filter(pk=row.pk).update(
                    views=F('views') + 1, last_usd=amount, max_usd=Greatest(F('max_usd'), amount),
                    last_net_usd=net, last_seen_at=now)
        return True
    except Exception:  # noqa: BLE001 — analytics never fails the quote
        logger.warning('Could not record a quote view', exc_info=True)
        return False


def record_cancel_reason(ramp, reason: str) -> bool:
    """Keep the first reason a person gave for cancelling their own order.
    False when the order was not cancelled by them or the reason is unknown."""
    from ramps.models import RampTransaction

    if reason not in CANCEL_REASONS:
        return False
    with transaction.atomic():
        current = RampTransaction.objects.select_for_update().get(pk=ramp.pk)
        if current.status != 'FAILED' or current.status_detail != 'cancelled_by_user':
            return False
        metadata = dict(current.metadata or {})
        if metadata.get('cancel_reason'):
            return True
        metadata['cancel_reason'] = {'reason': reason, 'at': timezone.now().isoformat()}
        current.metadata = metadata
        current.save(update_fields=['metadata', 'updated_at'])
    return True
