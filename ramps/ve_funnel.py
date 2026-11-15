"""Product evidence for every top-up (Koywe's countries and the Venezuelan
Pago Móvil): who saw a price, and why a person left without topping up.
Analytics only: nothing here may fail or delay the quote it describes."""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone

logger = logging.getLogger(__name__)

TOPUP_RAIL = 've_pagomovil_topup'
MAX_LOGGED_USD = Decimal('99999999999999999.99')

# One tap after cancelling. Asked by app 5.3.7 only; kept so its answers still land.
CANCEL_REASONS = ('fee', 'account', 'limit', 'later', 'looking', 'other')

# One tap when the person leaves a top-up price without ordering, whatever the
# currency. The app shows the labels (in a shuffled order); the server keeps the
# keys. 'skipped' = asked, and closed it without answering.
EXIT_REASONS = ('looking', 'no_money', 'receive_less', 'limits', 'pay_method', 'trust', 'loan', 'other', 'skipped')
TOP_UP_RAIL_SUFFIX = '_topup'
# The app asks the moment a top-up screen closes, and the newest view is the
# one left. Counted from the last quote, not from leaving: a person may sit on
# a price (checking their bank) or leave the sheet open a while.
EXIT_WINDOW = timedelta(hours=2)


def _money(value) -> Decimal | None:
    try:
        amount = Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if amount.is_finite() and 0 <= amount <= MAX_LOGGED_USD else None


def record_quote_view(user, rail: str, usd_amount=None, net_usd=None, *,
                      fiat_amount=None, fiat_currency: str = '', outside_limits: bool = False) -> bool:
    """Count a quote the person was shown. Never raises: a quote that could
    not be counted is still a quote.

    outside_limits: the amount was refused for the rail's minimum or maximum
    (Koywe Bolivia's 350 BOB). Still a look at the price, and the one most
    worth asking about; such a quote may have no dollar amount, only fiat."""
    from ramps.models import RampQuoteView
    from users.activity_tracking import activity_day

    amount = _money(usd_amount) if usd_amount is not None else None
    fiat = _money(fiat_amount) if fiat_amount is not None else None
    if (amount is None and fiat is None) or not getattr(user, 'pk', None):
        return False
    net = _money(net_usd)
    currency = (fiat_currency or '')[:3].upper()
    now = timezone.now()
    try:
        # Its own savepoint: a failed insert must not poison the caller's transaction.
        with transaction.atomic():
            row, created = RampQuoteView.objects.get_or_create(
                user_id=user.pk, rail=rail, day=activity_day(now),
                defaults={'first_usd': amount, 'last_usd': amount, 'max_usd': amount, 'last_net_usd': net,
                          'last_fiat_amount': fiat, 'fiat_currency': currency if fiat is not None else '',
                          'last_outside_limits': outside_limits,
                          'country': (getattr(user, 'country', '') or '')[:2],
                          'first_seen_at': now, 'last_seen_at': now})
            if not created:
                changes = {'views': F('views') + 1, 'last_seen_at': now, 'last_outside_limits': outside_limits}
                if amount is not None:
                    # GREATEST/COALESCE: a day that began with a refused,
                    # fiat-only quote has no dollar amounts yet.
                    changes.update(first_usd=Coalesce(F('first_usd'), amount), last_usd=amount,
                                   max_usd=Coalesce(Greatest(F('max_usd'), amount), amount), last_net_usd=net)
                if fiat is not None:
                    changes.update(last_fiat_amount=fiat, fiat_currency=currency)
                RampQuoteView.objects.filter(pk=row.pk).update(**changes)
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


def record_exit_reason(user, reason: str) -> bool:
    """Why the person left the top-up price they were just shown. Kept on the
    latest top-up quote view of the last hours; the first real answer stays
    (a 'skipped' gives way to a later answer). False when there is no such
    view, the reason is unknown, or a top-up order came after that price (they
    did not leave it). Never needs the client to name a rail."""
    from ramps.models import RampQuoteView, RampTransaction

    if reason not in EXIT_REASONS or not getattr(user, 'pk', None):
        return False
    now = timezone.now()
    with transaction.atomic():
        row = (RampQuoteView.objects.select_for_update()
               .filter(user_id=user.pk, rail__endswith=TOP_UP_RAIL_SUFFIX, last_seen_at__gte=now - EXIT_WINDOW)
               .order_by('-last_seen_at').first())
        if row is None:
            return False
        # An order placed after the last price shown means that price was taken.
        # One that ended FAILED was not (a Face check backed out of, a QR the
        # provider refused, a preparation that failed): the person still left.
        if (RampTransaction.objects.filter(actor_user_id=user.pk, direction='on_ramp',
                                           created_at__gte=row.last_seen_at)
                .exclude(status='FAILED').exists()):
            return False
        if row.exit_reason and (row.exit_reason != 'skipped' or reason == 'skipped'):
            return True
        row.exit_reason = reason
        row.exit_reason_at = now
        row.save(update_fields=['exit_reason', 'exit_reason_at'])
    return True
