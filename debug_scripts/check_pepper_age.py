
import os
import django
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User, WalletDerivationPepper

def check_pepper_age(user_id):
    try:
        user = User.objects.get(id=user_id)
        print(f"Checking pepper for User {user.id} ({user.email})...")
        
        pepper_key = f"user_{user.id}_personal_0"
        
        try:
            deriv = WalletDerivationPepper.objects.get(account_key=pepper_key)
            print(f"Pepper Found: {deriv.account_key}")
            print(f"Created At: {deriv.created_at}")
            print(f"Updated At: {deriv.updated_at}")
            
            # Compare with Dec 2, 2025
            dec2 = timezone.datetime(2025, 12, 2, tzinfo=timezone.utc)
            if deriv.created_at > dec2:
                print("WARNING: Pepper was created AFTER Dec 2. Old pepper likely lost.")
            else:
                print("Pepper predates Dec 2. It *should* be the same.")
                
        except WalletDerivationPepper.DoesNotExist:
            print("No pepper found!")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_pepper_age(8)
