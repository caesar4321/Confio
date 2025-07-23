from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, Min
from p2p_exchange.models import P2PPaymentMethod, P2POffer
from users.models import BankInfo
from collections import defaultdict


class Command(BaseCommand):
    help = 'Find and consolidate ALL duplicate payment methods'

    def handle(self, *args, **options):
        # Find all potential duplicates based on display_name and country_code
        self.stdout.write("Finding duplicate payment methods...\n")
        
        # Group payment methods by display_name and country_code
        duplicates_map = defaultdict(list)
        
        all_methods = P2PPaymentMethod.objects.all().order_by('id')
        for method in all_methods:
            key = (method.display_name, method.country_code)
            duplicates_map[key].append(method)
        
        # Filter to only groups with duplicates
        duplicate_groups = {k: v for k, v in duplicates_map.items() if len(v) > 1}
        
        if not duplicate_groups:
            self.stdout.write(self.style.SUCCESS("No duplicate payment methods found!"))
            return
        
        self.stdout.write(f"Found {len(duplicate_groups)} groups of duplicates:\n")
        
        consolidation_plan = []
        
        for (display_name, country_code), methods in duplicate_groups.items():
            self.stdout.write(f"\n{display_name} ({country_code or 'Global'}):")
            
            # Sort by ID to keep the oldest one (usually the one most likely to be in use)
            methods.sort(key=lambda x: x.id)
            
            # Check usage in offers and bank accounts
            for method in methods:
                offer_count = method.offers.count()
                bank_count = BankInfo.objects.filter(payment_method=method).count()
                self.stdout.write(
                    f"  - ID {method.id} ({method.name}): "
                    f"{offer_count} offers, {bank_count} bank accounts"
                )
            
            # Determine which one to keep (prefer the one with most usage)
            keep_method = max(methods, key=lambda m: (
                m.offers.count() + BankInfo.objects.filter(payment_method=m).count(),
                -m.id  # If tied, prefer older ID
            ))
            
            remove_methods = [m for m in methods if m.id != keep_method.id]
            
            self.stdout.write(f"  → Will keep ID {keep_method.id} and remove {[m.id for m in remove_methods]}")
            
            consolidation_plan.append({
                'display_name': display_name,
                'keep': keep_method,
                'remove': remove_methods
            })
        
        # Ask for confirmation
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"Will consolidate {len(consolidation_plan)} groups of duplicates.")
        
        # Auto-confirm for now
        self.stdout.write("\nProceeding with consolidation...")
        
        # Perform consolidation
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write("Starting consolidation...\n")
        
        with transaction.atomic():
            for group in consolidation_plan:
                try:
                    keep_pm = group['keep']
                    
                    self.stdout.write(f"\nConsolidating {group['display_name']}:")
                    self.stdout.write(f"  Keeping: ID {keep_pm.id} ({keep_pm.name})")
                    
                    for remove_pm in group['remove']:
                        self.stdout.write(f"  Processing: ID {remove_pm.id} ({remove_pm.name})")
                        
                        # Update BankInfo records
                        updated_bank_infos = BankInfo.objects.filter(
                            payment_method_id=remove_pm.id
                        ).update(payment_method_id=keep_pm.id)
                        
                        if updated_bank_infos:
                            self.stdout.write(f"    - Updated {updated_bank_infos} BankInfo records")
                        
                        # Update offers
                        offers_with_dup = P2POffer.objects.filter(
                            payment_methods__id=remove_pm.id
                        )
                        for offer in offers_with_dup:
                            offer.payment_methods.remove(remove_pm)
                            if keep_pm not in offer.payment_methods.all():
                                offer.payment_methods.add(keep_pm)
                            self.stdout.write(f"    - Updated offer {offer.id}")
                        
                        # Delete the duplicate
                        remove_pm.delete()
                        self.stdout.write(f"    - Deleted payment method {remove_pm.id}")
                    
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Consolidated {group['display_name']}"))
                    
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  ✗ Error consolidating {group['display_name']}: {e}"))
                    raise
        
        # Verification
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write("Verification:\n")
        
        # Check for remaining duplicates
        remaining_duplicates = defaultdict(list)
        for method in P2PPaymentMethod.objects.all():
            key = (method.display_name, method.country_code)
            remaining_duplicates[key].append(method)
        
        duplicate_count = sum(1 for methods in remaining_duplicates.values() if len(methods) > 1)
        
        if duplicate_count == 0:
            self.stdout.write(self.style.SUCCESS("✓ No duplicate payment methods remaining!"))
        else:
            self.stdout.write(self.style.ERROR(f"✗ Still have {duplicate_count} duplicate groups"))
        
        # Summary
        total_methods = P2PPaymentMethod.objects.count()
        self.stdout.write(f"\nTotal payment methods: {total_methods}")
        self.stdout.write(self.style.SUCCESS("\n✓ Consolidation complete!"))