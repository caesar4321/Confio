#!/usr/bin/env python3
"""
Create a test JWT token for WebSocket testing
"""
import jwt
import datetime
from django.conf import settings
import os
import sys

# Add the project to the path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()

def create_test_token(username):
    try:
        user = User.objects.get(username=username)
        
        # Create JWT payload (similar to the real JWT tokens)
        payload = {
            'user_id': user.id,
            'username': user.username,
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=1),
            'iat': datetime.datetime.utcnow(),
            'type': 'access'
        }
        
        # Generate token
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')
        
        print(f"✅ Test JWT token created for user '{username}':")
        print(f"🔑 Token: {token}")
        print(f"🆔 User ID: {user.id}")
        print(f"📅 Expires: {payload['exp']}")
        
        return token
        
    except User.DoesNotExist:
        print(f"❌ User '{username}' not found")
        print("Available users:")
        for user in User.objects.all():
            print(f"  - {user.username} (ID: {user.id})")
        return None

if __name__ == "__main__":
    username = sys.argv[1] if len(sys.argv) > 1 else "julianmoonluna"
    create_test_token(username)