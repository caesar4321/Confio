"""Copy the KYC selfie of already-verified users into the verification bucket.

Didit media links are short-lived, so each decision is re-fetched for fresh
URLs. Idempotent: users with an active reference are skipped.

    myvenv/bin/python manage.py backfill_face_references --dry-run
    myvenv/bin/python manage.py backfill_face_references --limit 50
"""
import time

from django.core.management.base import BaseCommand, CommandError

from security.didit import _didit_request
from security.face_step_up import FaceStepUpError, store_face_reference_from_didit
from security.models import FaceReference, IdentityVerification


class Command(BaseCommand):
    help = 'Store face references for verified users that do not have one yet.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--limit', type=int, default=0)

    def handle(self, *args, dry_run=False, limit=0, **options):
        if limit < 0:
            raise CommandError('--limit must be non-negative')
        has_reference = set(FaceReference.objects.filter(
            is_active=True, identity_verification__status='verified').values_list('user_id', flat=True))
        todo = []
        uncovered = set()
        for verification in IdentityVerification.all_documents.filter(status='verified').order_by('-verified_at', '-pk'):
            if verification.user_id in has_reference:
                continue
            factors = verification.risk_factors or {}
            if factors.get('account_type') == 'business':
                continue
            uncovered.add(verification.user_id)
            session_id = (factors.get('didit') or {}).get('session_id')
            if session_id:
                todo.append((verification, session_id))
                has_reference.add(verification.user_id)
        missing_session = uncovered - {verification.user_id for verification, _ in todo}
        self.stdout.write(f'{len(missing_session)} verified users without a reference or usable Didit session')
        if limit:
            todo = todo[:limit]
        self.stdout.write(f'{len(todo)} verified users without a face reference')
        if dry_run:
            return
        stored = failed = 0
        for verification, session_id in todo:
            try:
                decision = _didit_request('GET', f'/v3/session/{session_id}/decision/')
                if store_face_reference_from_didit(verification, decision):
                    stored += 1
                else:
                    failed += 1
            except FaceStepUpError as exc:
                failed += 1
                self.stderr.write(f'verification {verification.pk}: {exc}')
            except Exception as exc:
                # Never print the message: it may embed a signed media URL.
                failed += 1
                self.stderr.write(f'verification {verification.pk}: {type(exc).__name__}')
            time.sleep(0.3)
        self.stdout.write(f'stored {stored}, failed {failed}')
