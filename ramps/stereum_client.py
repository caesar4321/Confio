"""Stereum's documented API. Credentials never travel in URLs or exception text.

The sandbox and production share a hostname; the key selects the company/network.
This implementation deliberately permits sandbox only until settlement is certified.
"""
import hashlib
import hmac
import json
import re
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import requests
from django.conf import settings


class StereumError(RuntimeError):
    def __init__(self, message, *, code='', ambiguous=False):
        super().__init__(message)
        self.code = code
        self.ambiguous = ambiguous


def amount(value):
    try:
        value = Decimal(str(value))
        if not value.is_finite() or value <= 0 or value > 69600:
            raise ValueError
        if value != value.quantize(Decimal('.01')):
            raise ValueError
    except (InvalidOperation, ValueError, TypeError):
        raise StereumError('Amount must be positive, at most 69,600, with at most two decimals.')
    return format(value, '.2f')


def resource_id(value):
    value = str(value or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value):
        raise StereumError('Invalid resource identifier.')
    return quote(value, safe='')


def validate_response(data, *, writes=False):
    """Reject unusable JSON and mainnet flags, including nested order history."""
    try:
        json.dumps(data, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise StereumError('Stereum returned invalid JSON data.', ambiguous=writes) from None
    pending = [data]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for key in ('on_main_net', 'onMainNet'):
                flag = item.get(key)
                if flag is True or flag == 1 or (isinstance(flag, str) and flag.lower() == 'true'):
                    raise StereumError('Production resource returned to the test integration.', ambiguous=writes)
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return data


class StereumClient:
    BASE_URL = 'https://api.stereum.tech'

    def __init__(self, *, session=None):
        self.environment = getattr(settings, 'STEREUM_ENV', 'sandbox')
        if self.environment != 'sandbox':
            raise StereumError('Stereum production settlement is not enabled.')
        self.api_key = getattr(settings, 'STEREUM_API_KEY', '')
        self.secret = getattr(settings, 'STEREUM_SECRET_KEY', '')
        self.company_id = getattr(settings, 'STEREUM_COMPANY_ID', '')
        self.account_id = getattr(settings, 'STEREUM_BOB_ACCOUNT_ID', '')
        self.session = session or requests.Session()

    @property
    def scope(self):
        # Separate idempotency and resource ownership across credential rotations.
        return hashlib.sha256(self.api_key.encode()).hexdigest()

    def request(self, method, path, *, payload=None, signed=False, writes=False, timeout=25):
        if not self.api_key:
            raise StereumError('Stereum test API key is not configured.')
        if writes and (not getattr(settings, 'STEREUM_TEST_ENABLED', False) or not getattr(settings, 'STEREUM_TEST_WRITES_ENABLED', False)):
            raise StereumError('Stereum test mutations are disabled.')
        try:
            raw = json.dumps(payload, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode() if payload is not None else None
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise StereumError('Request payload must contain valid JSON data.') from None
        headers = {'x-api-key': self.api_key, 'Content-Type': 'application/json'}
        if signed:
            if not self.secret:
                raise StereumError('Stereum signing secret is not configured.')
            headers.update({
                'x-signature': hmac.new(self.secret.encode(), raw or b'', hashlib.sha256).hexdigest(),
                'x-timestamp': str(int(time.time())),
            })
        try:
            response = self.session.request(
                method, self.BASE_URL + path, data=raw, headers=headers,
                timeout=timeout, allow_redirects=False,
            )
        except requests.RequestException:
            raise StereumError('Stereum request failed; reconcile before retrying.', ambiguous=writes) from None
        try:
            data = response.json()
        except (ValueError, RecursionError):
            raise StereumError('Stereum returned an invalid response.', ambiguous=writes) from None
        if not 200 <= response.status_code < 300:
            # Provider errors can echo personal information. Keep only a bounded code.
            code = data.get('code', '') if isinstance(data, dict) else ''
            code = code if isinstance(code, str) and re.fullmatch(r'[A-Z_0-9]{1,80}', code) else ''
            raise StereumError(
                f'Stereum rejected the request (HTTP {response.status_code}{": " + code if code else ""}).',
                code=code, ambiguous=writes and (300 <= response.status_code < 400 or response.status_code >= 500 or response.status_code in {408, 409}),
            )
        return validate_response(data, writes=writes)

    def banks(self):
        return self.request('GET', '/api/v1/banks?country=BO')

    def balance(self):
        return self.request('GET', f'/api/v1/business-accounts/{resource_id(self.account_id)}/available-balance')

    def create_quote(self, *, side, value, currency='USDT', customer='SELF'):
        if side not in {'BUY', 'SELL'} or currency not in {'USDT', 'USDC'}:
            raise StereumError('Unsupported Bolivia quote direction or asset.')
        return self.request('POST', '/api/v1/otc/quotes', payload={
            'externalUserId': customer, 'side': side, 'inputAmount': amount(value),
            'inputCurrency': 'BOB' if side == 'BUY' else currency,
            'outputCurrency': currency if side == 'BUY' else 'BOB',
            'inputNetwork': 'CSL' if side == 'BUY' else 'POLYGON',
            'outputNetwork': 'POLYGON' if side == 'BUY' else 'CSL', 'country': 'BO',
        })

    def decode_qr(self, qrs):
        if not isinstance(qrs, str) or not qrs.strip() or len(qrs) > 32768:
            raise StereumError('Provide the scanned bank QR string (maximum 32 KiB).')
        return self.request('POST', '/api/v1/transfers/decode-qr', payload={'qrs': qrs})

    def create_charge(self, payload):
        return self.request('POST', '/api/v1/transactions/create-charge', payload=payload, writes=True)

    def validate_identity(self, payload):
        return self.request('POST', '/api/v1/segip/validate', payload=payload, signed=True, writes=True)

    def create_customer(self, payload):
        return self.request('POST', '/api/v1/customers/create', payload=payload, signed=True, writes=True)

    def create_order(self, payload):
        return self.request('POST', '/api/v1/otc/orders', payload=payload, writes=True)

    def send_transfer(self, payload, *, qr=False):
        return self.request('POST', '/api/v1/transfers/send-qr' if qr else '/api/v1/transfers/send',
                            payload=payload, signed=True, writes=True, timeout=70 if qr else 25)

    def get_charge(self, identifier):
        return self.request('GET', f'/api/v1/transactions/{resource_id(identifier)}/verify')

    def get_transfer(self, identifier):
        return self.request('GET', f'/api/v1/transfers/{resource_id(identifier)}/verify')

    def list_orders(self):
        return self.request('GET', f'/api/v1/sales/{resource_id(self.company_id)}/otc-orders')

    def confirm_test_charge(self, *, identifier, value):
        return self.request('POST', '/api/v1/callback/confirm-pay-test', writes=True, payload={
            'companyId': resource_id(self.company_id), 'transactionId': resource_id(identifier),
            'amount': amount(value), 'currency': 'BOB',
        })

    def verify_webhook(self, raw, signature):
        if not self.api_key or not self.secret or not isinstance(signature, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', signature):
            return False
        expected = hmac.new(self.secret.encode(), raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.lower())
