from django.core.management.base import BaseCommand
from django.db import transaction
from send.models import SendTransaction
from payments.models import PaymentTransaction
from p2p_exchange.models import P2PTrade
from conversion.models import Conversion
from users.signals import (
    create_unified_transaction_from_send,
    create_unified_transaction_from_payment,
    create_unified_transaction_from_p2p_trade,
    create_unified_transaction_from_conversion
)


class Command(BaseCommand):
    help = 'Migrates existing transactions to the UnifiedTransaction table'

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
            choices=['send', 'payment', 'p2p', 'conversion', 'all'],
            default='all',
            help='Type of transactions to migrate'
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        transaction_type = options['type']

        if transaction_type in ['send', 'all']:
            self.migrate_send_transactions(batch_size)
        
        if transaction_type in ['payment', 'all']:
            self.migrate_payment_transactions(batch_size)
        
        if transaction_type in ['p2p', 'all']:
            self.migrate_p2p_trades(batch_size)
        
        if transaction_type in ['conversion', 'all']:
            self.migrate_conversions(batch_size)

    def migrate_send_transactions(self, batch_size):
        """Migrate SendTransaction records"""
        self.stdout.write('Migrating SendTransaction records...')
        
        total = SendTransaction.objects.filter(deleted_at__isnull=True).count()
        processed = 0
        
        while processed < total:
            with transaction.atomic():
                transactions = SendTransaction.objects.filter(
                    deleted_at__isnull=True
                ).order_by('id')[processed:processed + batch_size]
                
                for tx in transactions:
                    try:
                        create_unified_transaction_from_send(tx)
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f'Error migrating SendTransaction {tx.id}: {e}')
                        )
                
                processed += len(transactions)
                self.stdout.write(f'Processed {processed}/{total} SendTransactions')

    def migrate_payment_transactions(self, batch_size):
        """Migrate PaymentTransaction records"""
        self.stdout.write('Migrating PaymentTransaction records...')
        
        total = PaymentTransaction.objects.filter(deleted_at__isnull=True).count()
        processed = 0
        
        while processed < total:
            with transaction.atomic():
                transactions = PaymentTransaction.objects.filter(
                    deleted_at__isnull=True
                ).order_by('id')[processed:processed + batch_size]
                
                for tx in transactions:
                    try:
                        create_unified_transaction_from_payment(tx)
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f'Error migrating PaymentTransaction {tx.id}: {e}')
                        )
                
                processed += len(transactions)
                self.stdout.write(f'Processed {processed}/{total} PaymentTransactions')

    def migrate_p2p_trades(self, batch_size):
        """Migrate P2PTrade records"""
        self.stdout.write('Migrating P2PTrade records...')
        
        # Only migrate completed/released trades
        total = P2PTrade.objects.filter(
            deleted_at__isnull=True,
            status__in=['CRYPTO_RELEASED', 'COMPLETED']
        ).count()
        processed = 0
        
        while processed < total:
            with transaction.atomic():
                trades = P2PTrade.objects.filter(
                    deleted_at__isnull=True,
                    status__in=['CRYPTO_RELEASED', 'COMPLETED']
                ).order_by('id')[processed:processed + batch_size]
                
                for trade in trades:
                    try:
                        create_unified_transaction_from_p2p_trade(trade)
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f'Error migrating P2PTrade {trade.id}: {e}')
                        )
                
                processed += len(trades)
                self.stdout.write(f'Processed {processed}/{total} P2PTrades')

    def migrate_conversions(self, batch_size):
        """Migrate Conversion records"""
        self.stdout.write('Migrating Conversion records...')
        
        total = Conversion.objects.filter(is_deleted=False).count()
        processed = 0
        
        while processed < total:
            with transaction.atomic():
                conversions = Conversion.objects.filter(
                    is_deleted=False
                ).order_by('id')[processed:processed + batch_size]
                
                for conv in conversions:
                    try:
                        create_unified_transaction_from_conversion(conv)
                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f'Error migrating Conversion {conv.id}: {e}')
                        )
                
                processed += len(conversions)
                self.stdout.write(f'Processed {processed}/{total} Conversions')
        
        self.stdout.write(self.style.SUCCESS('Migration completed!'))