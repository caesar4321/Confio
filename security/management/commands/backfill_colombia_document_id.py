from __future__ import annotations

from django.core.management.base import BaseCommand

from security.didit import DOCUMENT_TYPE_MAP
from security.models import IdentityVerification, normalize_document_number


class Command(BaseCommand):
    help = 'Backfill Colombia identity document_number from Didit personal_number.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show the rows that would be updated without saving changes.',
        )

    def handle(self, *args, **options):
        dry_run = bool(options.get('dry_run'))
        queryset = IdentityVerification.objects.filter(
            document_issuing_country='COL',
            status='verified',
        ).order_by('id')

        updated = 0
        skipped = 0

        for verification in queryset.iterator():
            session = ((verification.risk_factors or {}).get('didit') or {}).get('session') or {}
            id_verifications = session.get('id_verifications') or []
            id_verification = id_verifications[0] if isinstance(id_verifications, list) and id_verifications else {}
            personal_number = str(id_verification.get('personal_number') or session.get('personal_number') or '').strip()
            raw_document_type = str(id_verification.get('document_type') or session.get('document_type') or '').strip().lower()
            document_type = DOCUMENT_TYPE_MAP.get(raw_document_type, verification.document_type)

            if not personal_number:
                skipped += 1
                continue

            if verification.document_number == personal_number and verification.document_type == document_type:
                skipped += 1
                continue

            self.stdout.write(
                f'{"DRY RUN " if dry_run else ""}'
                f'user={verification.user_id} '
                f'verification={verification.id} '
                f'{verification.document_number!r}/{verification.document_type!r} -> '
                f'{personal_number!r}/{document_type!r}'
            )

            if not dry_run:
                verification.document_number = personal_number
                verification.document_number_normalized = normalize_document_number(personal_number)
                verification.document_type = document_type
                verification.save(update_fields=['document_number', 'document_number_normalized', 'document_type', 'updated_at'])

            updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'Colombia document backfill complete. updated={updated} skipped={skipped} dry_run={dry_run}'
        ))
