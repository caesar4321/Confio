from django.core.management.base import BaseCommand
from payroll.models import PayrollItem
from blockchain.algorand_client import AlgorandClient


class Command(BaseCommand):
    help = 'Fix payroll items stuck in SUBMITTED status'

    def handle(self, *args, **options):
        client = AlgorandClient()
        
        # Find all SUBMITTED items
        submitted_items = PayrollItem.objects.filter(
            deleted_at__isnull=True,
            status='SUBMITTED'
        )
        
        self.stdout.write(f"Found {submitted_items.count()} items in SUBMITTED status")
        
        confirmed_count = 0
        failed_count = 0
        
        for item in submitted_items:
            if not item.transaction_hash:
                self.stdout.write(f"  {item.item_id}: No transaction hash, skipping")
                continue
                
            try:
                info = client.algod.pending_transaction_info(item.transaction_hash)
                confirmed_round = info.get('confirmed-round', 0)
                
                if confirmed_round > 0:
                    # Transaction is confirmed
                    item.status = 'CONFIRMED'
                    item.save()
                    confirmed_count += 1
                    self.stdout.write(self.style.SUCCESS(
                        f"  ✓ {item.item_id}: Confirmed in round {confirmed_round}"
                    ))
                else:
                    self.stdout.write(f"  {item.item_id}: Still pending")
                    
            except Exception as e:
                error_msg = str(e)
                if 'could not find the transaction' in error_msg:
                    # Transaction is too old or failed
                    item.status = 'FAILED'
                    item.error_message = 'Transaction not found in pool (too old or failed)'
                    item.save()
                    failed_count += 1
                    self.stdout.write(self.style.WARNING(
                        f"  ✗ {item.item_id}: Marked as FAILED (transaction not found)"
                    ))
                else:
                    self.stdout.write(self.style.ERROR(
                        f"  ✗ {item.item_id}: Error - {error_msg}"
                    ))
        
        self.stdout.write(self.style.SUCCESS(
            f"\nCompleted: {confirmed_count} confirmed, {failed_count} failed"
        ))
