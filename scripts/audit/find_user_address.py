import os
import django
from django.conf import settings

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

from users.models import Account

def find_user():
    # Try username or partial match on name
    users = User.objects.filter(username__icontains='julianmoonluna')
    if not users.exists():
        users = User.objects.filter(first_name__icontains='Julian', last_name__icontains='Moon')
    
    for u in users:
        print(f"User: {u.username} ({u.first_name} {u.last_name})")
        accounts = Account.objects.filter(user=u)
        for acc in accounts:
            print(f"  Account ({acc.account_type}): {acc.algorand_address}")

if __name__ == "__main__":
    find_user()
