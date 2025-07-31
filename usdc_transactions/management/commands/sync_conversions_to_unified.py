from django.core.management.base import BaseCommand
from django.db import transaction
from conversion.models import Conversion
from usdc_transactions.signals import create_unified_usdc_transaction_from_conversion


class Command(BaseCommand):
    help = 'Sync existing USDC-related conversions to unified USDC transaction table'

    def handle(self, *args, **options):
        self.stdout.write('Starting sync of USDC conversions to unified table...')
        
        # Get all USDC-related conversions that aren't deleted
        conversions = Conversion.objects.filter(
            conversion_type__in=['usdc_to_cusd', 'cusd_to_usdc'],
            is_deleted=False
        )
        
        total = conversions.count()
        self.stdout.write(f'Found {total} USDC-related conversions to sync')
        
        success_count = 0
        error_count = 0
        
        with transaction.atomic():
            for conversion in conversions:
                try:
                    result = create_unified_usdc_transaction_from_conversion(conversion)
                    if result:
                        success_count += 1
                        self.stdout.write(f'✓ Synced conversion {conversion.conversion_id}')
                    else:
                        error_count += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f'✗ Failed to sync conversion {conversion.conversion_id}'
                            )
                        )
                except Exception as e:
                    error_count += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f'✗ Error syncing conversion {conversion.conversion_id}: {e}'
                        )
                    )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\nSync completed: {success_count} successful, {error_count} errors'
            )
        )