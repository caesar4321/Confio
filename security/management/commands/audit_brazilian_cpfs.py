from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from security.models import IdentityVerification, normalize_brazilian_cpf


class Command(BaseCommand):
    help = 'Audit verified Brazilian identities and fail if any stored CPF is invalid.'

    def handle(self, *args, **options):
        queryset = IdentityVerification.objects.filter(
            document_issuing_country='BRA',
            status='verified',
            risk_factors__account_type__isnull=True,
        ).order_by('id')
        counts = {'valid': 0, 'invalid': 0}

        for verification in queryset.iterator():
            if normalize_brazilian_cpf(verification.document_number):
                counts['valid'] += 1
                continue

            counts['invalid'] += 1
            self.stdout.write(self.style.WARNING(
                f'invalid user={verification.user_id} verification={verification.id}'
            ))

        summary = ' '.join(f'{key}={value}' for key, value in counts.items())
        self.stdout.write(self.style.SUCCESS(f'Brazil CPF audit complete. {summary}'))
        if counts['invalid']:
            raise CommandError(
                f'Brazil CPF audit found {counts["invalid"]} invalid verified identities; manual review required.'
            )
