from security.middleware import SecurityMiddleware
from security.models import IPAddress
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from unittest.mock import Mock

User = get_user_model()

print("Setting up test environment...")
# Create a dummy user
import uuid
user, created = User.objects.get_or_create(
    username='test_user_blocked', 
    defaults={
        'email': 'test_blocked@example.com',
        'firebase_uid': f'test_uid_{uuid.uuid4()}'
    }
)

# Create a blocked IP
blocked_ip_str = '192.0.2.254'
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
    if response_clean == "OK": 
         print("PASS: Clean IP was allowed.")
    else:
         print(f"FAIL: Clean IP got unexpected response: {response_clean}")

# Cleanup
print("\nCleaning up...")
IPAddress.objects.filter(ip_address__in=[blocked_ip_str, clean_ip_str]).delete()
