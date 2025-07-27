from django.core.management.base import BaseCommand
from django.db import transaction
from usdc_transactions.models import USDCDeposit, USDCWithdrawal
from conversion.models import Conversion
from usdc_transactions.signals import (
    create_unified_usdc_transaction_from_deposit,
    create_unified_usdc_transaction_from_withdrawal,
    create_unified_usdc_transaction_from_conversion
)


class Command(BaseCommand):
    help = 'Migrates existing USDC transactions to the UnifiedUSDCTransaction table'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Number of records to process in each batch'
        )
        parser.add_argument(
            '--type',
            type=str,
            choices=['deposit', 'withdrawal', 'conversion', 'all'],
            default='all',
            help='Type of transactions to migrate'
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        transaction_type = options['type']

        if transaction_type in ['deposit', 'all']:
            self.migrate_deposits(batch_size)
        
        if transaction_type in ['withdrawal', 'all']:
            self.migrate_withdrawals(batch_size)
        
        if transaction_type in ['conversion', 'all']:
            self.migrate_conversions(batch_size)

    def migrate_deposits(self, batch_size):
        """Migrate USDCDeposit records"""
        self.stdout.write('Migrating USDCDeposit records...')
        
        total = USDCDeposit.objects.count()
        processed = 0
        
        while processed < total:
            with transaction.atomic():
                deposits = USDCDeposit.objects.order_by('id')[processed:processed + batch_size]
                
                for deposit in deposits:
                    try:
                        create_unified_usdc_transaction_from_deposit(deposit)
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f'Error migrating USDCDeposit {deposit.id}: {e}')
                        )
                
                processed += len(deposits)
                self.stdout.write(f'Processed {processed}/{total} USDCDeposits')

    def migrate_withdrawals(self, batch_size):
        """Migrate USDCWithdrawal records"""
        self.stdout.write('Migrating USDCWithdrawal records...')
        
        total = USDCWithdrawal.objects.count()
        processed = 0
        
        while processed < total:
            with transaction.atomic():
                withdrawals = USDCWithdrawal.objects.order_by('id')[processed:processed + batch_size]
                
                for withdrawal in withdrawals:
                    try:
                        create_unified_usdc_transaction_from_withdrawal(withdrawal)
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f'Error migrating USDCWithdrawal {withdrawal.id}: {e}')
                        )
                
                processed += len(withdrawals)
                self.stdout.write(f'Processed {processed}/{total} USDCWithdrawals')

    def migrate_conversions(self, batch_size):
        """Migrate USDC-related Conversion records"""
        self.stdout.write('Migrating USDC-related Conversion records...')
        
        # Only USDC-related conversions
        total = Conversion.objects.filter(
            is_deleted=False,
            conversion_type__in=['usdc_to_cusd', 'cusd_to_usdc']
        ).count()
        processed = 0
        
        while processed < total:
            with transaction.atomic():
                conversions = Conversion.objects.filter(
                    is_deleted=False,
                    conversion_type__in=['usdc_to_cusd', 'cusd_to_usdc']
                ).order_by('id')[processed:processed + batch_size]
                
                for conv in conversions:
                    try:
                        create_unified_usdc_transaction_from_conversion(conv)
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f'Error migrating Conversion {conv.id}: {e}')
                        )
                
                processed += len(conversions)
                self.stdout.write(f'Processed {processed}/{total} USDC Conversions')
        
        self.stdout.write(self.style.SUCCESS('USDC migration completed!'))