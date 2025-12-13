import os
import django
from django.conf import settings

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User, Account

def reset_status(user_id):
    try:
        user = User.objects.get(id=user_id)
        print(f"Resetting User ID: {user_id} ({user.email})")
        
        accounts = Account.objects.filter(user=user)
        for acc in accounts:
            if acc.account_type == 'personal' and acc.account_index == 0:
                print(f"  - Converting Account {acc.id} from Migrated to NOT Migrated")
                print(f"  - Old Status: {acc.is_keyless_migrated}")
                print(f"  - Old Address: {acc.algorand_address}")
                
                # Reset Status
                acc.is_keyless_migrated = False
                # Do NOT clear address (keep V2 as active target, checkNeedsMigration will still detect V1 balance via logs)
                # If we clear address, it will be harder to debug if V2 logic resumes.
                # Actually, checkNeedsMigration calculates V1 address independently.
                # If we want the user to "restart" migration, we should let them see the modal.
                # Modal appears if is_keyless_migrated=False.
                
                acc.save(update_fields=['is_keyless_migrated'])
                print(f"  - New Status: {acc.is_keyless_migrated}")

    except User.DoesNotExist:
        print(f"User {user_id} not found")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # User 8 is Julian
    reset_status(8)
