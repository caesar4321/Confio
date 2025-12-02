from django.core.management.base import BaseCommand
from payroll.models import PayrollItem
from users.models_unified import UnifiedTransactionTable

class Command(BaseCommand):
    help = 'Check payroll items and their unified transactions'

    def handle(self, *args, **options):
        # Get recent payroll items
        items = PayrollItem.objects.filter(
            deleted_at__isnull=True
        ).order_by('-created_at')[:10]
        
        self.stdout.write(f"\n=== Recent Payroll Items ===")
        for item in items:
            self.stdout.write(f"\nItem ID: {item.item_id}")
            self.stdout.write(f"Status: {item.status}")
            self.stdout.write(f"Amount: {item.net_amount} {item.token_type}")
            self.stdout.write(f"Tx Hash: {item.transaction_hash or 'None'}")
            self.stdout.write(f"Recipient: {item.recipient_user}")
            
            # Check if unified transaction exists
            unified = UnifiedTransactionTable.objects.filter(payroll_item=item).first()
            if unified:
                self.stdout.write(self.style.SUCCESS(f"✓ Unified transaction exists (ID: {unified.id})"))
                self.stdout.write(f"  Type: {unified.transaction_type}")
                self.stdout.write(f"  Status: {unified.status}")
                self.stdout.write(f"  From: {unified.sender_display_name}")
                self.stdout.write(f"  To: {unified.counterparty_display_name}")
            else:
                self.stdout.write(self.style.ERROR(f"✗ No unified transaction found"))
                
                # Try to create it manually
                if item.status in ['CONFIRMED', 'SUBMITTED']:
                    self.stdout.write("  Attempting to create unified transaction...")
                    from users.signals import create_unified_transaction_from_payroll
                    try:
                        result = create_unified_transaction_from_payroll(item)
                        if result:
                            self.stdout.write(self.style.SUCCESS(f"  ✓ Created unified transaction (ID: {result.id})"))
                        else:
                            self.stdout.write(self.style.ERROR("  ✗ Failed to create (returned None)"))
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"  ✗ Error: {e}"))
