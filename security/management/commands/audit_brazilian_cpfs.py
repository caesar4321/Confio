from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from security.didit import resolve_brazilian_cpf_for_verification
from security.models import IdentityVerification, normalize_brazilian_cpf


class Command(BaseCommand):
    help = 'Audit verified Brazilian identities and safely recover CPF from matching Didit attempts.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fix',
            action='store_true',
            help='Apply only unambiguous, collision-free CPF recoveries.',
        )

    def handle(self, *args, **options):
        apply_fixes = bool(options.get('fix'))
        queryset = IdentityVerification.objects.filter(
            document_issuing_country='BRA',
            status='verified',
            risk_factors__account_type__isnull=True,
        ).order_by('id')
        counts = {'valid': 0, 'recoverable': 0, 'fixed': 0, 'unresolved': 0}

        for verification in queryset.iterator():
            if normalize_brazilian_cpf(verification.document_number):
                counts['valid'] += 1
                continue

            cpf, source_ids = resolve_brazilian_cpf_for_verification(verification)
            if not cpf:
                counts['unresolved'] += 1
                self.stdout.write(self.style.WARNING(
                    f'unresolved user={verification.user_id} verification={verification.id}'
                ))
                continue

            counts['recoverable'] += 1
            self.stdout.write(
                f'{"FIX " if apply_fixes else "RECOVERABLE "}'
                f'user={verification.user_id} verification={verification.id} sources={source_ids}'
            )
            if not apply_fixes:
                continue

            with transaction.atomic():
                locked = IdentityVerification.objects.select_for_update().get(pk=verification.pk)
                if normalize_brazilian_cpf(locked.document_number):
                    continue
                locked.document_number = cpf
                risk_factors = dict(locked.risk_factors or {})
                risk_factors['document_number_recovery'] = {
                    'source': 'matching_didit_attempts',
                    'source_verification_ids': source_ids,
                    'recovered_at': timezone.now().isoformat(),
                    'reason': 'verified_brazil_identity_missing_valid_cpf',
                }
                locked.risk_factors = risk_factors
                locked.save(update_fields=[
                    'document_number',
                    'document_number_normalized',
                    'risk_factors',
                    'updated_at',
                ])
                counts['fixed'] += 1

        summary = ' '.join(f'{key}={value}' for key, value in counts.items())
        self.stdout.write(self.style.SUCCESS(f'Brazil CPF audit complete. {summary} fix={apply_fixes}'))
        if counts['unresolved']:
            raise CommandError(
                f'Brazil CPF audit found {counts["unresolved"]} unresolved verified identities; manual review required.'
            )
