from django.core.management.base import BaseCommand

from ramps.tasks import KOYWE_SUPPORTED_COUNTRIES, sync_koywe_bank_info


class Command(BaseCommand):
    help = 'Sync Koywe bank info for all supported countries into the local DB'

    def add_arguments(self, parser):
        parser.add_argument(
            '--country',
            type=str,
            help='Sync only this country (ISO alpha-3, e.g. COL)',
        )

    def handle(self, *args, **options):
        country = options.get('country')
        if country:
            from ramps.koywe_client import KoyweClient, KoyweError
            from ramps.models import KoyweBankInfo

            client = KoyweClient()
            if not client.is_configured:
                self.stderr.write('Koywe client not configured')
                return

            alpha3 = country.upper()
            try:
                banks = client.get_bank_info(country_code=alpha3)
            except KoyweError as exc:
                self.stderr.write(f'Failed to fetch bank info for {alpha3}: {exc}')
                return

            count = 0
            for bank in banks:
                bank_code = bank.get('bankCode') or ''
                name = bank.get('name') or ''
                if not bank_code or not name:
                    continue
                KoyweBankInfo.objects.update_or_create(
                    bank_code=bank_code,
                    country_code=alpha3,
                    defaults={
                        'name': name,
                        'institution_name': bank.get('institutionName') or '',
                        'is_active': True,
                    },
                )
                count += 1
            self.stdout.write(self.style.SUCCESS(f'Synced {count} banks for {alpha3}'))
        else:
            result = sync_koywe_bank_info()
            self.stdout.write(self.style.SUCCESS(result))
