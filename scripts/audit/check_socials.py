
import os
import django
import sys

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User
from social_django.models import UserSocialAuth

def check_socials():
    user_id = 2696
    try:
        user = User.objects.get(id=user_id)
        print(f"User: {user.email} (ID: {user.id})")
        
        socials = UserSocialAuth.objects.filter(user=user)
        print(f"Found {socials.count()} social auth records:")
        
        for sa in socials:
            print(f"  Provider: {sa.provider}")
            print(f"  UID: {sa.uid}")
            print(f"  Extra Data: {sa.extra_data}")
            
    except User.DoesNotExist:
        print("User not found")

if __name__ == "__main__":
    check_socials()
