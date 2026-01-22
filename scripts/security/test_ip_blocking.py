
import os
import sys
import django
from django.conf import settings
from django.test import RequestFactory
from unittest.mock import Mock, patch

# Setup Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from security.middleware import SecurityMiddleware
from security.models import IPAddress
from django.contrib.auth import get_user_model

User = get_user_model()

def test_ip_blocking():
    print("Setting up test environment...")
    
    # Create a dummy user
    user, created = User.objects.get_or_create(username='test_user_blocked', email='test_blocked@example.com')
    
    # Create a blocked IP
    blocked_ip_str = '192.0.2.254' # Test-Net-1
    ip_obj, _ = IPAddress.objects.get_or_create(ip_address=blocked_ip_str)
    ip_obj.is_blocked = True
    ip_obj.save()
    print(f"Created/Updated blocked IP: {blocked_ip_str}")

    # Create a clean IP
    clean_ip_str = '192.0.2.253'
    ip_obj_clean, _ = IPAddress.objects.get_or_create(ip_address=clean_ip_str)
    ip_obj_clean.is_blocked = False
    ip_obj_clean.save()
    print(f"Created/Updated clean IP: {clean_ip_str}")

    # Initialize Middleware
    get_response = Mock(return_value="OK")
    middleware = SecurityMiddleware(get_response)
    
    factory = RequestFactory()

    # Test 1: Blocked IP
    print("\nTest 1: Request from Blocked IP")
    request = factory.get('/')
    request.user = user
    request.META['HTTP_X_FORWARDED_FOR'] = blocked_ip_str
    
    response = middleware(request)
    
    if hasattr(response, 'status_code') and response.status_code == 403:
        print("PASS: Blocked IP was forbidden (403).")
    else:
        print(f"FAIL: Blocked IP got response: {response}")

    # Test 2: Clean IP
    print("\nTest 2: Request from Clean IP")
    request_clean = factory.get('/')
    request_clean.user = user
    request_clean.META['HTTP_X_FORWARDED_FOR'] = clean_ip_str
    
    response_clean = middleware(request_clean)
    
    if response_clean == "OK":
        print("PASS: Clean IP was allowed.")
    else:
         # It might return "OK" object if mock returned it
        if response_clean == "OK": 
             print("PASS: Clean IP was allowed.")
        else:
             print(f"FAIL: Clean IP got unexpected response: {response_clean}")

    # Cleanup
    print("\nCleaning up...")
    IPAddress.objects.filter(ip_address__in=[blocked_ip_str, clean_ip_str]).delete()
    # User cleanup might cascade, skipping to avoid side effects
    
if __name__ == "__main__":
    try:
        test_ip_blocking()
    except Exception as e:
        print(f"Error: {e}")
