
import os
import django
from django.forms.models import model_to_dict

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User, Account

def check_status():
    try:
        user = User.objects.get(id=2696)
        print(f"User: {user.username} (ID: {user.id})")
        
        accounts = Account.objects.filter(user=user)
        for acc in accounts:
            print(f"Account {acc.account_index} ({acc.account_type}):")
            print(f"  Address: {acc.algorand_address}")
            print(f"  Is Keyless Migrated: {acc.is_keyless_migrated}")
            
    except User.DoesNotExist:
        print("User not found")

if __name__ == "__main__":
    check_status()
