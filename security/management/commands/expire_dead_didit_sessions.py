"""Mark Didit sessions that ended without a decision (Didit said "Expired" or
"Abandoned") as 'expired' instead of 'pending'. Before security/didit.py
mapped those statuses, they stayed 'pending' forever and the app told the
person "Estamos revisando tu documento".

Never touches a row that was ever verified (verified_at set) or Didit's
"Kyc Expired" (an approval that aged out; handled separately).

    manage.py expire_dead_didit_sessions            # dry run: counts only
    manage.py expire_dead_didit_sessions --apply
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from security.didit import DIDIT_DEAD_SESSION_STATUSES
from security.models import IdentityVerification


class Command(BaseCommand):
    help = 'Mark Didit sessions that ended without a decision as expired (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **opts):
        rows = []
        for row in IdentityVerification.all_objects.filter(status='pending', verified_at__isnull=True).only(
                'id', 'risk_factors'):
            raw = str(((row.risk_factors or {}).get('didit') or {}).get('raw_status') or '').strip().lower()
            if raw in DIDIT_DEAD_SESSION_STATUSES:
                rows.append(row.id)
        self.stdout.write(f'{len(rows)} pending Didit sessions ended without a decision')
        if not opts['apply']:
            self.stdout.write('dry run: nothing changed (use --apply)')
            return
        with transaction.atomic():
            # Re-check the status under the update: a webhook may have decided one meanwhile.
            changed = IdentityVerification.all_objects.filter(
                id__in=rows, status='pending', verified_at__isnull=True).update(status='expired')
        self.stdout.write(f'marked {changed} as expired')
