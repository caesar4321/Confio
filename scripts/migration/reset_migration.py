
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User, Account

def reset_migration():
    try:
        user = User.objects.get(id=2696)
        print(f"User: {user.username} (ID: {user.id})")
        
        accounts = Account.objects.filter(user=user)
        for acc in accounts:
            print(f"Resetting Account {acc.account_index}...")
            print(f"  Old Status: is_keyless_migrated={acc.is_keyless_migrated}")
            print(f"  Old Address: {acc.algorand_address}")
            
            acc.is_keyless_migrated = False
            # Should we clear the address?
            # If we don't, the app might see an address and assume it's done?
            # Or the app checks `is_keyless_migrated`?
            # If we clear it, ensure we don't lose the V2 address ref if the app needs it?
            # But the App *generates* the address.
            # Safest is to keep address for now, usually the "Migration Needed" check depends on the flag.
            # If I clear the address, the backend might spawn a new one later?
            
            # The user said: "setting the user account's migrated flag to False and trigger the migration again."
            # They didn't explicitly say "Clear the address".
            # But if the address is "MDNNU..." (The V2 one), and we want it to re-migrate...
            # The app likely checks: "Do I have V1 keys? Am I migrated? No? -> Run Migration -> save new address."
            # If I leave the V2 address, it might just overwrite it.
            
            acc.save(update_fields=['is_keyless_migrated'])
            print(f"  New Status: is_keyless_migrated={acc.is_keyless_migrated}")
            
    except User.DoesNotExist:
        print("User not found")

if __name__ == "__main__":
    reset_migration()
