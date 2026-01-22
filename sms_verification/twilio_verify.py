import base64
import os
from typing import Optional, Tuple

import requests
from django.conf import settings


class TwilioVerifyError(Exception):
    pass


def _auth_header() -> str:
    # Prefer API Key SID/Secret if provided
    api_key = getattr(settings, 'TWILIO_API_KEY_SID', None) or os.getenv('TWILIO_API_KEY_SID')
    api_secret = getattr(settings, 'TWILIO_API_KEY_SECRET', None) or os.getenv('TWILIO_API_KEY_SECRET')
    if api_key and api_secret:
        token = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
        return f"Basic {token}"

    # Fallback to Account SID/Auth Token
    account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', None) or os.getenv('TWILIO_ACCOUNT_SID')
    auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', None) or os.getenv('TWILIO_AUTH_TOKEN')
    if not account_sid or not auth_token:
        raise TwilioVerifyError('Missing Twilio credentials: set TWILIO_API_KEY_SID/TWILIO_API_KEY_SECRET or TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN')
    token = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
    return f"Basic {token}"


def _service_sid() -> str:
    svc = getattr(settings, 'TWILIO_VERIFY_SERVICE_SID', None) or os.getenv('TWILIO_VERIFY_SERVICE_SID')
    if not svc:
        raise TwilioVerifyError('Missing TWILIO_VERIFY_SERVICE_SID configuration')
    return svc


def send_verification_sms(phone_e164: str) -> Tuple[str, str]:
    """
    Start a Twilio Verify SMS verification.
    Returns (verification_sid, status) on success.
    """
    service_sid = _service_sid()
    url = f"https://verify.twilio.com/v2/Services/{service_sid}/Verifications"
    headers = {
        'Authorization': _auth_header(),
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    data = {
        'To': phone_e164,
        'Channel': 'sms',
    }
    # Optional locale (e.g., 'es' for Spanish)
    locale = getattr(settings, 'TWILIO_VERIFY_LOCALE', None) or os.getenv('TWILIO_VERIFY_LOCALE')
    if locale:
        data['Locale'] = locale
    resp = requests.post(url, headers=headers, data=data, timeout=10)
    if resp.status_code >= 400:
        raise TwilioVerifyError(f"Twilio Verify error {resp.status_code}: {resp.text}")
    j = resp.json()
    return j.get('sid', ''), j.get('status', '')


def check_verification(phone_e164: str, code: str) -> Tuple[bool, Optional[str]]:
    """
    Check a Twilio Verify code.
    Returns (approved, status).
    """
    service_sid = _service_sid()
    url = f"https://verify.twilio.com/v2/Services/{service_sid}/VerificationCheck"
    headers = {
        'Authorization': _auth_header(),
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    data = {
        'To': phone_e164,
        'Code': code,
    }
    resp = requests.post(url, headers=headers, data=data, timeout=10)
    if resp.status_code >= 400:
        raise TwilioVerifyError(f"Twilio Verify error {resp.status_code}: {resp.text}")
    j = resp.json()
    status = j.get('status')
    return status == 'approved', status


def check_phone_line_type(phone_e164: str) -> Optional[str]:
    """
    Check phone number line type using Twilio Lookup v2.
    Returns 'mobile', 'landline', 'voip', etc. or None if lookup fails.
    """
    try:
        # Use Lookups v2 API
        url = f"https://lookups.twilio.com/v2/PhoneNumbers/{phone_e164}"
        headers = {
            'Authorization': _auth_header(),
        }
        params = {
            'Fields': 'line_type_intelligence'
        }
        
        resp = requests.get(url, headers=headers, params=params, timeout=5)
        if resp.status_code != 200:
            # Log warning but allow permissive failure (return None = don't block)
            # or could raise error depending on strictness
            return None
            
        data = resp.json()
        # Extract line type from v2 response structure
        # Response: { "line_type_intelligence": { "type": "mobile", ... }, ... }
        ltie = data.get('line_type_intelligence', {})
        line_type = ltie.get('type')
        return line_type
        
    except Exception:
        return None
