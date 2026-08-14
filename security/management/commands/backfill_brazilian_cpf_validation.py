from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from security.didit import (
    DiditAPIError,
    _authoritative_brazilian_cpf_from_database_validation,
    classify_brazilian_cpf_database_validation,
    validate_brazilian_cpf_with_didit,
)
from security.models import IdentityVerification, normalize_brazilian_cpf


TERMINAL_RESULTS = {'full_match', 'review_required'}


def _stored_backfill(verification: IdentityVerification) -> dict:
    didit = (verification.risk_factors or {}).get('didit') or {}
    value = didit.get('cpf_database_validation_backfill') or {}
    return value if isinstance(value, dict) else {}


def _has_authoritative_session_cpf(verification: IdentityVerification, cpf: str) -> bool:
    session = ((verification.risk_factors or {}).get('didit') or {}).get('session') or {}
    present, authoritative_cpf = _authoritative_brazilian_cpf_from_database_validation(session)
    return present and authoritative_cpf == cpf


class Command(BaseCommand):
    help = 'Backfill authoritative Didit bra_cpf validation for legacy verified Brazilian identities.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Perform paid Didit lookups and persist their results.',
        )

    def handle(self, *args, **options):
        apply = bool(options.get('apply'))
        queryset = IdentityVerification.objects.filter(
            document_issuing_country='BRA',
            status='verified',
        ).order_by('id')
        counts = {
            'eligible': 0,
            'matched': 0,
            'review': 0,
            'retryable': 0,
            'invalid': 0,
            'skipped': 0,
        }

        for verification in queryset.iterator():
            if (verification.risk_factors or {}).get('account_type') == 'business':
                counts['skipped'] += 1
                continue
            cpf = normalize_brazilian_cpf(verification.document_number)
            if not cpf:
                counts['invalid'] += 1
                self.stdout.write(self.style.WARNING(
                    f'invalid user={verification.user_id} verification={verification.id}'
                ))
                continue
            if _has_authoritative_session_cpf(verification, cpf):
                counts['skipped'] += 1
                continue
            if _stored_backfill(verification).get('result') in TERMINAL_RESULTS:
                counts['skipped'] += 1
                continue

            counts['eligible'] += 1
            self.stdout.write(
                f'{"APPLY" if apply else "PLAN"} '
                f'user={verification.user_id} verification={verification.id}'
            )
            if not apply:
                continue

            try:
                response = validate_brazilian_cpf_with_didit(
                    cpf=cpf,
                    date_of_birth=verification.verified_date_of_birth,
                    vendor_data=f'confio-user-{verification.user_id}',
                )
                result, evidence = classify_brazilian_cpf_database_validation(
                    response,
                    expected_cpf=cpf,
                )
            except DiditAPIError as exc:
                counts['retryable'] += 1
                self.stderr.write(self.style.WARNING(
                    f'retryable user={verification.user_id} verification={verification.id}: {exc}'
                ))
                continue

            if result == 'retryable':
                counts['retryable'] += 1
                self.stderr.write(self.style.WARNING(
                    f'retryable user={verification.user_id} verification={verification.id} '
                    f'outcome={evidence["outcome_code"] or "MALFORMED"}'
                ))
                continue

            checked_at = timezone.now().isoformat()
            with transaction.atomic():
                locked = IdentityVerification.objects.select_for_update().get(pk=verification.pk)
                if _stored_backfill(locked).get('result') in TERMINAL_RESULTS:
                    counts['skipped'] += 1
                    continue
                if (
                    normalize_brazilian_cpf(locked.document_number) != cpf
                    or locked.verified_date_of_birth != verification.verified_date_of_birth
                    or locked.status != 'verified'
                ):
                    counts['retryable'] += 1
                    self.stderr.write(self.style.WARNING(
                        f'retryable user={verification.user_id} verification={verification.id}: '
                        'identity changed during lookup'
                    ))
                    continue
                risk_factors = dict(locked.risk_factors or {})
                didit = dict(risk_factors.get('didit') or {})
                didit['cpf_database_validation_backfill'] = {
                    **evidence,
                    'result': result,
                    'checked_at': checked_at,
                }
                risk_factors['didit'] = didit
                risk_factors['brazilian_cpf_validation'] = {
                    'source': 'didit_bra_cpf_backfill',
                    'result': result,
                    'request_id': evidence['request_id'],
                    'checked_at': checked_at,
                }
                update_fields = ['risk_factors', 'updated_at']
                if result == 'review_required':
                    risk_factors['requires_review'] = True
                    locked.status = 'pending'
                    update_fields.append('status')
                    counts['review'] += 1
                else:
                    counts['matched'] += 1
                locked.risk_factors = risk_factors
                locked.save(update_fields=update_fields)

        summary = ' '.join(f'{key}={value}' for key, value in counts.items())
        self.stdout.write(self.style.SUCCESS(
            f'Brazil CPF validation backfill complete. apply={apply} {summary}'
        ))
        if counts['invalid'] or counts['retryable'] or counts['review']:
            raise CommandError('Brazil CPF validation backfill requires follow-up; see counts above.')
