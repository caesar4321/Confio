"""Mark Didit attempts that can no longer succeed as 'expired' instead of
'pending' (before security/didit.py mapped these statuses they stayed
'pending' forever and the app told the person "Estamos revisando tu
documento"). IdentityVerification.expired_reason keeps why:

- "Expired" / "Abandoned": the session ended without a decision. Never a row
  that was ever verified.
- "Kyc Expired": a verification whose identity document has passed its
  validity date; the person must verify again with a current document.

    manage.py expire_dead_didit_sessions            # dry run: counts only
    manage.py expire_dead_didit_sessions --apply
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from security.didit import DIDIT_DEAD_SESSION_STATUSES, DIDIT_DOCUMENT_EXPIRED_STATUSES
from security.models import IdentityVerification


class Command(BaseCommand):
    help = 'Mark Didit attempts that can no longer succeed as expired (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **opts):
        dead, document_expired = [], []
        for row in IdentityVerification.all_objects.filter(status='pending').only('id', 'risk_factors', 'verified_at'):
            raw = str(((row.risk_factors or {}).get('didit') or {}).get('raw_status') or '').strip().lower()
            if raw in DIDIT_DEAD_SESSION_STATUSES and row.verified_at is None:
                dead.append(row.id)
            elif raw in DIDIT_DOCUMENT_EXPIRED_STATUSES:
                document_expired.append(row.id)
        self.stdout.write(f'{len(dead)} sessions ended without a decision; '
                          f'{len(document_expired)} verifications whose document expired')
        if not opts['apply']:
            self.stdout.write('dry run: nothing changed (use --apply)')
            return
        with transaction.atomic():
            # Re-check under the update: a webhook may have decided one meanwhile.
            changed = IdentityVerification.all_objects.filter(
                id__in=dead, status='pending', verified_at__isnull=True).update(status='expired')
            changed += IdentityVerification.all_objects.filter(
                id__in=document_expired, status='pending').update(status='expired')
        self.stdout.write(f'marked {changed} as expired')
