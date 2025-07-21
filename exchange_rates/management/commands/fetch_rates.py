from django.core.management.base import BaseCommand
from exchange_rates.services import exchange_rate_service


class Command(BaseCommand):
    help = 'Fetch exchange rates from all available sources'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source',
            type=str,
            help='Fetch from specific source only (dolartoday, yadio, exchangerate_api)',
        )

    def handle(self, *args, **options):
        source = options.get('source')
        
        if source:
            self.stdout.write(f'Fetching rates from {source}...')
            
            if source == 'dolartoday':
                success = exchange_rate_service.fetch_dolartoday_rates()
            elif source == 'yadio':
                success = exchange_rate_service.fetch_yadio_rates()
            elif source == 'exchangerate_api':
                success = exchange_rate_service.fetch_exchangerate_api_rates()
            else:
                self.stdout.write(
                    self.style.ERROR(f'Unknown source: {source}')
                )
                return
            
            if success:
                self.stdout.write(
                    self.style.SUCCESS(f'Successfully fetched rates from {source}')
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f'Failed to fetch rates from {source}')
                )
        else:
            self.stdout.write('Fetching rates from all sources...')
            
            results = exchange_rate_service.fetch_all_rates()
            
            for source_name, success in results.items():
                if success:
                    self.stdout.write(
                        self.style.SUCCESS(f'✓ {source_name}: Success')
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(f'✗ {source_name}: Failed')
                    )
            
            successful_count = sum(1 for success in results.values() if success)
            total_count = len(results)
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'\nCompleted: {successful_count}/{total_count} sources successful'
                )
            )