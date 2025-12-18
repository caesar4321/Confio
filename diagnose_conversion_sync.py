
import os
import django
import sys

# Setup Django environment
sys.path.append('/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from conversion.models import Conversion
from usdc_transactions.models_unified import UnifiedUSDCTransactionTable
from usdc_transactions.signals import create_unified_usdc_transaction_from_conversion

def diagnose():
    try:
        # User provided internal_id prefix ff4e4e8d
        internal_id_prefix = 'ff4e4e8d'
        print(f"Searching for Conversion starting with {internal_id_prefix}...")
        
        conv = Conversion.objects.filter(internal_id__startswith=internal_id_prefix).first()
        if not conv:
            print("Conversion not found!")
            return

        print(f"Found Conversion: {conv.internal_id}")
        print(f"Conversion Status: {conv.status}")
        
        # Check linked unified transaction
        unified = UnifiedUSDCTransactionTable.objects.filter(conversion=conv).first()
        if not unified:
            print("Unified Transaction NOT FOUND via relation!")
            # Try finding by transaction_id
            unified_by_id = UnifiedUSDCTransactionTable.objects.filter(transaction_id=conv.internal_id).first()
            if unified_by_id:
                print("Unified Transaction FOUND via transaction_id match, but 'conversion' FK is NULL or mismatched!")
                print(f"Unified Status: {unified_by_id.status}")
                if unified_by_id.conversion is None:
                    print("ERROR: 'conversion' FK is None")
                elif unified_by_id.conversion != conv:
                    print(f"ERROR: 'conversion' FK points to {unified_by_id.conversion.id} instead of {conv.id}")
            else:
                print("Unified Transaction NOT FOUND via transaction_id either!")
        else:
            print("Unified Transaction FOUND via relation.")
            print(f"Unified Status: {unified.status}")
            if unified.status != conv.status:
                print("MISMATCH DETECTED!")
                
                # Attempt manual sync
                print("Attempting manual sync via create_unified_usdc_transaction_from_conversion...")
                try:
                    res = create_unified_usdc_transaction_from_conversion(conv)
                    print(f"Sync result: {res}")
                    
                    # Re-fetch
                    unified.refresh_from_db()
                    print(f"Unified Status after sync: {unified.status}")
                except Exception as e:
                    print(f"Sync FAILED with error: {e}")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    diagnose()
