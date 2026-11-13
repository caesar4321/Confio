"""Set first_cusd_acquired_at for users who brought dollars in by a route that never armed it.

Until 2026-11-13 only USDC→cUSD conversions and received cUSD sends set the
field, so BSC users (whose money arrives as USDT -> Dollar+ or USDT -> cUSD
conversions, or as received Dollar+) never got the ICP poll, and so never the
rating prompt. This writes their earliest
inflow time; pendingModal then returns ICP the next time they open the app.

Dry run by default (prints counts only):
    myvenv/bin/python manage.py backfill_first_dollars_received [--since 2026-08-01]
Write:
    myvenv/bin/python manage.py backfill_first_dollars_received --apply [--since ...]
"""
from collections import Counter
from datetime import datetime

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from conversion.models import Conversion
from send.models import BALANCE_TOKEN_TYPES, SendTransaction
from usdc_transactions.signals import INCOMING_CONVERSION_TYPES
from users.models import User


def first_inflows():
    """user_id -> earliest time that user received dollars (personal context).

    Same rule as the live signals: a completed incoming conversion, or a
    received cUSD/Dollar+ send that is not a business payment or self-transfer.
    """
    first = {}

    def add(uid, when):
        if uid and when and (uid not in first or when < first[uid]):
            first[uid] = when

    for uid, at in Conversion.objects.filter(
        status='COMPLETED', conversion_type__in=INCOMING_CONVERSION_TYPES,
        actor_type='user', actor_user__isnull=False, is_deleted=False,
    ).values_list('actor_user_id', 'completed_at'):
        add(uid, at)
    for uid, sender, at in SendTransaction.objects.filter(
        status='CONFIRMED', token_type__in=BALANCE_TOKEN_TYPES,
        recipient_user__isnull=False, recipient_business__isnull=True,
    ).values_list('recipient_user_id', 'sender_user_id', 'created_at'):
        if sender != uid:
            add(uid, at)
    return first


class Command(BaseCommand):
    help = 'Backfill first_cusd_acquired_at from every dollar inflow route (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Write the timestamps.')
        parser.add_argument('--since', help='Only users whose first inflow is on/after YYYY-MM-DD.')

    def handle(self, *args, apply=False, since=None, **options):
        cutoff = None
        if since:
            cutoff = timezone.make_aware(datetime.strptime(since, '%Y-%m-%d'))

        inflows = first_inflows()
        missing = set(
            User.objects.filter(
                id__in=list(inflows), is_active=True, first_cusd_acquired_at__isnull=True,
            ).values_list('id', flat=True)
        )
        todo = {
            uid: when for uid, when in inflows.items()
            if uid in missing and (cutoff is None or when >= cutoff)
        }

        by_month = Counter(when.strftime('%Y-%m') for when in todo.values())
        for month in sorted(by_month):
            self.stdout.write(f'{month}  {by_month[month]}')
        self.stdout.write(f'users to backfill: {len(todo)}')

        if not apply:
            self.stdout.write('dry run: nothing written (pass --apply)')
            return

        written = 0
        for uid, when in todo.items():
            with transaction.atomic():
                # Re-check under lock: a live signal may have set it meanwhile.
                written += User.objects.select_for_update().filter(
                    pk=uid, first_cusd_acquired_at__isnull=True,
                ).update(first_cusd_acquired_at=when)
        self.stdout.write(self.style.SUCCESS(f'written: {written}'))
