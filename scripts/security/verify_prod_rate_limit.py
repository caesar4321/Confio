
from unittest.mock import MagicMock, patch
from django.core.cache import cache
from django.contrib.auth import get_user_model
from sms_verification.schema import InitiateSMSVerification
import uuid
import time

User = get_user_model()

def verify_production_limits():
    # We DO NOT clear the entire cache on production!
    # cache.clear() <- DANGEROUS IN PROD
    
    print("--- Starting Production Rate Limit Verification ---")
    
    # Create unique dummy user for this run
    run_id = str(uuid.uuid4())[:8]
    username = f"rate_limit_test_{run_id}"
    email = f"test_{run_id}@example.com"
    phone_number = f"+1555{run_id[:7]}" # Random dummy phone
    
    print(f"Creating test user: {username} | Phone: {phone_number}")
    user, _ = User.objects.get_or_create(
        username=username, 
        defaults={
            "email": email,
            "firebase_uid": str(uuid.uuid4())
        }
    )
    
    # Mock context
    mock_info = MagicMock()
    mock_info.context.user = user
    mock_info.context.META = {'REMOTE_ADDR': '127.0.0.1'} # Internal IP
    
    # Key helpers
    key_cooldown = f"sms_limit:cooldown:{phone_number}"
    
    # We must patch send_verification_sms so we don't actually trigger Twilio costs/errors
    # for these fake numbers
    with patch('sms_verification.schema.send_verification_sms') as mock_send:
        mock_send.return_value = ('SM_TEST_SID', 'pending')
        
        # 1. First Request - Should Success
        print("\n1. Testing 1st Request (Should Succeed)...")
        res = InitiateSMSVerification.mutate(None, mock_info, phone_number=phone_number, country_code="US")
        if res.success:
            print("   SUCCESS [OK]")
        else:
            print(f"   FAILED: {res.error} [UNEXPECTED]")
            return

        # 2. Immediate Second Request - Should Fail (Cooldown)
        print("\n2. Testing Cooldown (Should Fail)...")
        res2 = InitiateSMSVerification.mutate(None, mock_info, phone_number=phone_number, country_code="US")
        if not res2.success and "espera un minuto" in str(res2.error):
            print("   BLOCKED by Cooldown [OK]")
        else:
            print(f"   RESULT: Success={res2.success}, Error={res2.error} [POSSIBLE FAILURE]")

        # 3. Test Volume Limit
        # We need to clear cooldown execution-side to test volume limit quickly
        # This is safe because it's a specific key for our dummy number
        print("\n3. Testing Volume Limit (5/hr)...")
        
        # We already succeeded 1 time.
        # We want to hit the limit of 5.
        # So we need 4 more successes.
        
        for i in range(4):
            # Clear cooldown manually
            cache.delete(key_cooldown)
            
            res = InitiateSMSVerification.mutate(None, mock_info, phone_number=phone_number, country_code="US")
            print(f"   Request {i+2}: Success={res.success}")
            
        # The next one (6th total) should fail due to User limit (5) or Phone limit (3)
        # Our limits are: Phone=3, User=5.
        # So actually, it should have failed on the 4th request (Phone limit).
        
        # Let's check if we hit the limit
        cache.delete(key_cooldown)
        final_res = InitiateSMSVerification.mutate(None, mock_info, phone_number=phone_number, country_code="US")
        
        if not final_res.success:
             print(f"   Final Request Blocked: {final_res.error} [OK]")
        else:
             print("   Final Request SUCCEEDED [FAILURE - Limit not enforced]")

    print("\n--- Cleanup ---")
    # Clean up user
    user.delete()
    print("Test user deleted.")
    
try:
    verify_production_limits()
except Exception as e:
    import traceback
    traceback.print_exc()
