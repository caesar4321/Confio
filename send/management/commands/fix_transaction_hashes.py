from django.core.management.base import BaseCommand
from send.models import SendTransaction
import time
import uuid


class Command(BaseCommand):
    help = 'Fix duplicate or empty transaction hashes in send transactions'

    def handle(self, *args, **options):
        self.stdout.write('Fixing transaction hashes in send transactions...')
        
        # Get all send transactions with empty or duplicate transaction hashes
        problematic_transactions = SendTransaction.objects.filter(
            transaction_hash__isnull=True
        ) | SendTransaction.objects.filter(
            transaction_hash=''
        )
        
        fixed_count = 0
        
        for transaction in problematic_transactions:
            # Generate a unique transaction hash
            microsecond_timestamp = int(time.time() * 1000000)
            unique_id = str(uuid.uuid4())[:8]
            transaction.transaction_hash = f"test_send_tx_{transaction.id}_{microsecond_timestamp}_{unique_id}"
            transaction.save()
            fixed_count += 1
            
            # Small delay to ensure unique timestamps
            time.sleep(0.001)
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully fixed {fixed_count} send transaction hashes')
        )
        
        # Also check for any duplicate transaction hashes
        from django.db.models import Count
        duplicates = SendTransaction.objects.values('transaction_hash').annotate(
            count=Count('transaction_hash')
        ).filter(count__gt=1, transaction_hash__isnull=False).exclude(transaction_hash='')
        
        if duplicates.exists():
            self.stdout.write('Found duplicate transaction hashes, fixing...')
            for duplicate in duplicates:
                hash_value = duplicate['transaction_hash']
                transactions_with_hash = SendTransaction.objects.filter(
                    transaction_hash=hash_value
                ).order_by('id')
                
                # Keep the first one, fix the rest
                for i, transaction in enumerate(transactions_with_hash[1:], 1):
                    microsecond_timestamp = int(time.time() * 1000000)
                    unique_id = str(uuid.uuid4())[:8]
                    transaction.transaction_hash = f"test_send_tx_{transaction.id}_{microsecond_timestamp}_{unique_id}"
                    transaction.save()
                    fixed_count += 1
                    time.sleep(0.001)
        
        self.stdout.write(
            self.style.SUCCESS(f'Total fixed: {fixed_count} transaction hashes')
        ) 