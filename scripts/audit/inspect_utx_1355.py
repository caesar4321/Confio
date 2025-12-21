import os
import django
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from users.models_unified import UnifiedTransactionTable

def inspect_tx():
    try:
        utx = UnifiedTransactionTable.objects.get(id=1355)
        print(f"UnifiedTransaction {utx.id}:")
        print(f"  Type: {utx.transaction_type}")
        
        has_rel = utx.presale_purchase is not None
        print(f"  Has PresalePurchase: {has_rel}")
        
        if has_rel:
            pp = utx.presale_purchase
            print(f"  PresalePurchase ID: {pp.id}")
            print(f"  PresalePurchase Internal ID: {pp.internal_id}")
            
        print(f"  Property internal_id: {utx.internal_id}")

    except UnifiedTransactionTable.DoesNotExist:
        print("UnifiedTransaction 1355 not found")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_tx()
