from unittest.mock import patch, MagicMock
from sms_verification.schema import InitiateSMSVerification
from sms_verification.twilio_verify import check_phone_line_type

def test_carrier_lookup():
    print("Testing Twilio Carrier Lookup Logic...")

    # Mock info.context.user
    mock_info = MagicMock()
    # Create a mock user that behaves like a model instance
    mock_user = MagicMock()
    mock_user.is_authenticated = True
    mock_user.id = 12345
    mock_info.context.user = mock_user
    mock_info.context.META = {'REMOTE_ADDR': '127.0.0.1'}

    # Test Case 1: Mobile Number (Should Pass)
    print("\n[Test 1] Mobile Number")
    with patch('sms_verification.twilio_verify.requests.get') as mock_get, \
         patch('sms_verification.schema.send_verification_sms') as mock_send, \
         patch('django.core.cache.cache.get', return_value=None): # Bypass rate limits
        
        # Mock Twilio Lookup Response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'line_type_intelligence': {'type': 'mobile'}
        }
        mock_get.return_value = mock_resp
        
        # Mock Send Response
        mock_send.return_value = ('sid123', 'pending')

        result = InitiateSMSVerification.mutate(None, mock_info, '+15005550001', 'US')
        
        if result.success:
            print("PASS: Mobile number accepted.")
        else:
            print(f"FAIL: Mobile number rejected. Error: {result.error}")

    # Test Case 2: VoIP Number (Should Fail)
    print("\n[Test 2] VoIP Number")
    with patch('sms_verification.twilio_verify.requests.get') as mock_get_voip, \
         patch('django.core.cache.cache.get', return_value=None):
        
        # Mock Twilio Lookup Response
        mock_resp_voip = MagicMock()
        mock_resp_voip.status_code = 200
        mock_resp_voip.json.return_value = {
            'line_type_intelligence': {'type': 'voip'}
        }
        mock_get_voip.return_value = mock_resp_voip

        result = InitiateSMSVerification.mutate(None, mock_info, '+15005550002', 'US')
        
        if not result.success and "Solo se permiten números móviles" in result.error:
            print("PASS: VoIP number rejected.")
        else:
            print(f"FAIL: VoIP number NOT rejected properly. Result: {result.success}, Error: {result.error}")

    # Test Case 3: Landline Number (Should Fail)
    print("\n[Test 3] Landline Number")
    with patch('sms_verification.twilio_verify.requests.get') as mock_get_land, \
         patch('django.core.cache.cache.get', return_value=None):
        
        # Mock Twilio Lookup Response
        mock_resp_land = MagicMock()
        mock_resp_land.status_code = 200
        mock_resp_land.json.return_value = {
            'line_type_intelligence': {'type': 'landline'}
        }
        mock_get_land.return_value = mock_resp_land

        result = InitiateSMSVerification.mutate(None, mock_info, '+15005550003', 'US')
        
        if not result.success and "Solo se permiten números móviles" in result.error:
            print("PASS: Landline number rejected.")
        else:
            print(f"FAIL: Landline number NOT rejected properly. Result: {result.success}, Error: {result.error}")

# Run the test
try:
    test_carrier_lookup()
except Exception as e:
    print(f"Error: {e}")
