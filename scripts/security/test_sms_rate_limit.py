
from unittest.mock import MagicMock, patch
from django.core.cache import cache
from django.contrib.auth import get_user_model
from sms_verification.schema import InitiateSMSVerification

User = get_user_model()

def test_rate_limiting():
    # Clear cache
    cache.clear()
    
    # Create dummy user with unique fields
    import uuid
    user, _ = User.objects.get_or_create(
        username="test_rate_limit_v2", 
        defaults={
            "email": "test_v2@example.com",
            "firebase_uid": str(uuid.uuid4())
        }
    )
    
    # Mock info.context
    mock_info = MagicMock()
    mock_info.context.user = user
    # user.is_authenticated is a property, no need to set it (it's True for DB users)
    mock_info.context.META = {'REMOTE_ADDR': '127.0.0.1'}
    
    phone = "+15005550006"
    
    print("Testing Rate Limiting...")
    
    with patch('sms_verification.schema.send_verification_sms') as mock_send:
        mock_send.return_value = ('SMxxxxxxxx', 'pending')
        
        # 1. Test Success
        res = InitiateSMSVerification.mutate(None, mock_info, phone_number=phone, country_code="US")
        if res.success:
            print("1. First Request: SUCCESS")
        else:
            print(f"1. First Request: FAILED ({res.error})")

        # 2. Test Cooldown (should fail immediately)
        res = InitiateSMSVerification.mutate(None, mock_info, phone_number=phone, country_code="US")
        if not res.success and "espera un minuto" in res.error:
            print("2. Cooldown Check: PASSED")
        else:
            print(f"2. Cooldown Check: FAILED ({res.success} - {res.error})")
            
        # Clear cooldown to test limit
        cache.delete(f"sms_limit:cooldown:{phone}")
        
        # 3. Test User Limit (5 per hour)
        # We already did 1 success. Do 4 more.
        for i in range(4):
            cache.delete(f"sms_limit:cooldown:{phone}") # Clear cooldown for each
            res = InitiateSMSVerification.mutate(None, mock_info, phone_number=phone, country_code="US")
        
        # Next one should fail
        cache.delete(f"sms_limit:cooldown:{phone}")
        res = InitiateSMSVerification.mutate(None, mock_info, phone_number=phone, country_code="US")
        if not res.success and "excedido el límite" in res.error:
            print("3. User Limit Check: PASSED")
        else:
            print(f"3. User Limit Check: FAILED ({res.success} - {res.error})")

try:
    test_rate_limiting()
except Exception as e:
    import traceback
    traceback.print_exc()
