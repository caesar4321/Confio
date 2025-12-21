
import os
import django
import sys

sys.path.append('/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models_unified import UnifiedTransactionTable
from conversion.models import Conversion
from django.db import transaction

def check_conversion_sync():
    print("Checking for inconsistent Conversion <-> UnifiedTransactionTable records...")
    
    # 1. Conversions that are COMPLETED but Unified has no hash
    total_mismatch = 0
    
    unified_qs = UnifiedTransactionTable.objects.filter(
        transaction_type='conversion', 
        transaction_hash=''
    ).select_related('conversion')
    
    print(f"Found {unified_qs.count()} UnifiedTransactions with empty hash.")
    
    for uni in unified_qs:
        conv = uni.conversion
        if not conv:
            print(f"  Unified {uni.id}: No linked conversion.")
            continue
            
        has_hash = conv.to_transaction_hash or conv.from_transaction_hash
        # Check if status indicates completion
        should_have_hash = conv.status in ['COMPLETED', 'SUBMITTED']
        
        if has_hash:
            print(f"  MISMATCH: Unified {uni.id} (Internal: {uni.internal_id}) has empty hash, but Conversion {conv.id} has '{has_hash}'")
            print(f"    Conversion Status: {conv.status}")
            total_mismatch += 1
            
            # Attempt auto-fix
            print(f"    FIXING Unified {uni.id}...")
            uni.transaction_hash = has_hash
            uni.status = conv.status # Sync status too
            uni.save()
            
        elif should_have_hash:
             print(f"  WEIRD: Unified {uni.id} has empty hash, Conversion {conv.id} is {conv.status} but also has empty hash!")

    print(f"Total inconsistencies found: {total_mismatch}")

if __name__ == '__main__':
    check_conversion_sync()
