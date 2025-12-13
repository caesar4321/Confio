
import sys
import os
import django
from django.conf import settings

# Setup Django environment
# Add project root to python path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User, Account

def reset_status_by_address(target_address):
    print(f"Searching for account with address: {target_address}")
    
    try:
        # Filter for personal account 0 matching the address
        accounts = Account.objects.filter(
            algorand_address=target_address,
            account_type='personal',
            account_index=0
        )
        
        if not accounts.exists():
            print(f"❌ No account found with address: {target_address}")
            return

        for acc in accounts:
            user = acc.user
            print(f"✅ Found User: {user.id} ({user.email})")
            print(f"   Account ID: {acc.id}")
            print(f"   Current Status: is_keyless_migrated={acc.is_keyless_migrated}")
            
            if acc.is_keyless_migrated:
                acc.is_keyless_migrated = False
                acc.save(update_fields=['is_keyless_migrated'])
                print(f"   🔄 Reset Status to: False (Ready for Migration Test)")
            else:
                print(f"   ℹ️ Status is already False.")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    TARGET_ADDRESS = "P7WYM6SDBLV5UWM6AWFD4ZCNH7DZE3EICBZOAOORAUHDBVQ44RRS6ZLZZU"
    reset_status_by_address(TARGET_ADDRESS)
