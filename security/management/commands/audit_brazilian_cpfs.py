from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from security.didit import (
    _authoritative_brazilian_cpf_from_database_validation,
    is_authoritative_brazilian_cpf_backfill,
)
from security.models import IdentityVerification, normalize_brazilian_cpf


class Command(BaseCommand):
    help = 'Audit Brazilian CPF validity and authoritative Didit registry coverage.'

    def handle(self, *args, **options):
        queryset = IdentityVerification.objects.filter(
            document_issuing_country='BRA',
        ).order_by('id')
        counts = {'valid': 0, 'authoritative': 0, 'legacy': 0, 'review': 0, 'invalid': 0}

        for verification in queryset.iterator():
            risk_factors = verification.risk_factors or {}
            if risk_factors.get('account_type') == 'business':
                continue
            backfill = ((risk_factors.get('didit') or {}).get('cpf_database_validation_backfill') or {})
            backfill_result = backfill.get('result') if isinstance(backfill, dict) else None
            if verification.status != 'verified' and backfill_result != 'review_required':
                continue

            cpf = normalize_brazilian_cpf(verification.document_number)
            if not cpf:
                counts['invalid'] += 1
                self.stdout.write(self.style.WARNING(
                    f'invalid user={verification.user_id} verification={verification.id}'
                ))
                continue

            counts['valid'] += 1
            session = ((risk_factors.get('didit') or {}).get('session') or {})
            _, session_cpf = _authoritative_brazilian_cpf_from_database_validation(session)
            if session_cpf == cpf or is_authoritative_brazilian_cpf_backfill(backfill, cpf=cpf):
                counts['authoritative'] += 1
            elif backfill_result == 'review_required':
                counts['review'] += 1
                self.stdout.write(self.style.WARNING(
                    f'review user={verification.user_id} verification={verification.id}'
                ))
            else:
                counts['legacy'] += 1
                self.stdout.write(self.style.WARNING(
                    f'legacy user={verification.user_id} verification={verification.id}'
                ))

        summary = ' '.join(f'{key}={value}' for key, value in counts.items())
        self.stdout.write(self.style.SUCCESS(f'Brazil CPF audit complete. {summary}'))
        if counts['invalid'] or counts['legacy'] or counts['review']:
            raise CommandError(
                'Brazil CPF audit found identities without authoritative full-match coverage; '
                'backfill or manual review required.'
            )
