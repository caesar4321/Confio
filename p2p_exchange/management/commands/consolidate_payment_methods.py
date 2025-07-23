from django.core.management.base import BaseCommand
from django.db import transaction
from p2p_exchange.models import P2PPaymentMethod, P2POffer
from users.models import BankInfo


class Command(BaseCommand):
    help = 'Consolidate duplicate payment methods'

    def handle(self, *args, **options):
        duplicates = [
            {
                'name': 'HSBC Argentina',
                'keep_id': 144,  # The one used in offers
                'remove_id': 213,  # The duplicate
            },
            {
                'name': 'ICBC Argentina',
                'keep_id': 145,  # The one used in offers
                'remove_id': 216,  # The duplicate
            },
        ]
        
        with transaction.atomic():
            for dup in duplicates:
                try:
                    keep_pm = P2PPaymentMethod.objects.get(id=dup['keep_id'])
                    remove_pm = P2PPaymentMethod.objects.get(id=dup['remove_id'])
                    
                    self.stdout.write(f"\nConsolidating {dup['name']}:")
                    self.stdout.write(f"  Keeping: ID {keep_pm.id} ({keep_pm.name})")
                    self.stdout.write(f"  Removing: ID {remove_pm.id} ({remove_pm.name})")
                    
                    # Update BankInfo records to use the kept payment method
                    updated_bank_infos = BankInfo.objects.filter(
                        payment_method_id=remove_pm.id
                    ).update(payment_method_id=keep_pm.id)
                    
                    self.stdout.write(f"  Updated {updated_bank_infos} BankInfo records")
                    
                    # Update any offers that might use the duplicate
                    # (though in this case, offers already use the correct IDs)
                    offers_with_dup = P2POffer.objects.filter(
                        payment_methods__id=remove_pm.id
                    )
                    for offer in offers_with_dup:
                        offer.payment_methods.remove(remove_pm)
                        offer.payment_methods.add(keep_pm)
                        self.stdout.write(f"  Updated offer {offer.id}")
                    
                    # Now safe to delete the duplicate
                    remove_pm.delete()
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Consolidated {dup['name']}"))
                    
                except P2PPaymentMethod.DoesNotExist as e:
                    self.stdout.write(self.style.ERROR(f"  ✗ Payment method not found: {e}"))
                    continue
        
        # Verify consolidation
        self.stdout.write("\n" + "="*50)
        self.stdout.write("Verification:")
        
        # Check remaining payment methods
        hsbc_count = P2PPaymentMethod.objects.filter(display_name__icontains='HSBC Argentina').count()
        icbc_count = P2PPaymentMethod.objects.filter(display_name__icontains='ICBC Argentina').count()
        
        self.stdout.write(f"HSBC Argentina payment methods: {hsbc_count}")
        self.stdout.write(f"ICBC Argentina payment methods: {icbc_count}")
        
        # Check BankInfo records
        hsbc_bankinfo = BankInfo.objects.filter(payment_method_id=144).count()
        icbc_bankinfo = BankInfo.objects.filter(payment_method_id=145).count()
        
        self.stdout.write(f"\nBankInfo records:")
        self.stdout.write(f"  HSBC Argentina (ID 144): {hsbc_bankinfo}")
        self.stdout.write(f"  ICBC Argentina (ID 145): {icbc_bankinfo}")
        
        self.stdout.write(self.style.SUCCESS("\n✓ Consolidation complete!"))