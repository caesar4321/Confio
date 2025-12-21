
import os
import django
from django.forms.models import model_to_dict

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User

def dump_user():
    try:
        user = User.objects.get(id=2696)
        print(f"User ID: {user.id}")
        
        # Print all fields
        data = model_to_dict(user)
        for k, v in data.items():
            print(f"{k}: {v}")
            
        print("-" * 20)
        print(f"Firebase UID: {user.firebase_uid}")
        print(f"Username: {user.username}")
        print(f"Email: {user.email}")
        
    except User.DoesNotExist:
        print("User not found")

if __name__ == "__main__":
    dump_user()
