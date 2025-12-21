import os
import django
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User, Account

def check_status(user_id):
    try:
        user = User.objects.get(pk=user_id)
        print(f"Checking User ID: {user.id} ({user.username})")
        accounts = Account.objects.filter(user=user)
        for acc in accounts:
            print(f"  Account [{acc.account_type} {acc.account_index}]: is_keyless_migrated = {acc.is_keyless_migrated}")
            print(f"  Address: {acc.algorand_address}")
            
    except User.DoesNotExist:
        print(f"User {user_id} not found")

if __name__ == "__main__":
    check_status(5)
