import base64
import hashlib
import hmac
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.cache import cache


class ProviderAPIError(RuntimeError):
    def __init__(self, message, *, status_code=None, payload=None, retryable=False):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload
        self.retryable = retryable


class ProviderConfigurationError(ProviderAPIError):
    pass


class ComplianceHandoffError(RuntimeError):
    pass


class BaseProviderClient:
    provider = ''

    def __init__(self, *, base_url, timeout=20, session=None):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({'User-Agent': 'ConfioBackend/1.0'})

    def _parse(self, response, action):
        try:
            payload = response.json()
        except ValueError:
            payload = {'raw': response.text[:2000]}
        if not response.ok:
            message = None
            if isinstance(payload, dict):
                message = payload.get('message') or payload.get('detail') or payload.get('error')
            elif isinstance(payload, (list, str)):
                message = str(payload)[:500]
            raise ProviderAPIError(
                f'{action}: {message or response.status_code}',
                status_code=response.status_code,
                payload=payload,
                retryable=response.status_code >= 500,
            )
        return payload

    def _request(self, method, url, *, action, **kwargs):
        try:
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            raise ProviderAPIError(
                f'{action}: network error',
                retryable=True,
            ) from exc
        return self._parse(response, action)


class CobreClient(BaseProviderClient):
    provider = 'cobre'

    def __init__(self, *, session=None):
        super().__init__(
            base_url=getattr(settings, 'COBRE_API_URL', 'https://api.cobre.co/v1'),
            timeout=getattr(settings, 'PAYMENT_PROVIDER_TIMEOUT_SECONDS', 20),
            session=session,
        )
        self.user_id = getattr(settings, 'COBRE_USER_ID', '')
        self.secret = getattr(settings, 'COBRE_SECRET', '')

    @property
    def is_configured(self):
        return bool(self.user_id and self.secret)

    def _token(self):
        if not self.is_configured:
            raise ProviderConfigurationError('Cobre credentials are not configured')
        cache_key = 'payment-accounts:cobre:access-token'
        token = cache.get(cache_key)
        if token:
            return token
        try:
            response = self.session.post(
                f'{self.base_url}/auth',
                json={'user_id': self.user_id, 'secret': self.secret},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ProviderAPIError(
                'Cobre authentication failed: network error', retryable=True
            ) from exc
        data = self._parse(response, 'Cobre authentication failed')
        token = data.get('access_token')
        if not token:
            raise ProviderAPIError('Cobre authentication response has no access_token')
        cache.set(cache_key, token, timeout=18 * 60)
        return token

    def request(
        self, method, path, *, payload=None, params=None, idempotency_key=None, _retry_auth=True
    ):
        headers = {'Authorization': f'Bearer {self._token()}'}
        if idempotency_key:
            headers['idempotency'] = idempotency_key
        try:
            return self._request(
                method,
                f'{self.base_url}/{path.lstrip("/")}',
                action=f'Cobre {method} {path} failed',
                json=payload,
                params=params,
                headers=headers,
            )
        except ProviderAPIError as exc:
            if exc.status_code == 401 and _retry_auth:
                cache.delete('payment-accounts:cobre:access-token')
                return self.request(
                    method,
                    path,
                    payload=payload,
                    params=params,
                    idempotency_key=idempotency_key,
                    _retry_auth=False,
                )
            raise

    def create_account(self, payload):
        return self.request('POST', '/accounts', payload=payload)

    def get_account(self, account_id):
        return self.request('GET', f'/accounts/{account_id}')

    def find_account(self, alias):
        return self.request('GET', '/accounts', params={'alias': alias, 'page_size': 1})

    def create_key(self, account_id, payload):
        return self.request('POST', f'/accounts/{account_id}/keys', payload=payload)

    def get_key(self, account_id, key_id):
        return self.request('GET', f'/accounts/{account_id}/keys/{key_id}')

    def find_key(self, account_id, alias):
        return self.request(
            'GET', f'/accounts/{account_id}/keys', params={'alias': alias, 'page_size': 1}
        )

    def create_counterparty(self, payload, *, idempotency_key=None):
        return self.request(
            'POST', '/counterparties', payload=payload, idempotency_key=idempotency_key
        )

    def find_counterparty(self, alias):
        return self.request(
            'GET', '/counterparties', params={'alias': alias, 'page_size': 1}
        )

    def create_money_movement(self, payload, *, idempotency_key):
        return self.request(
            'POST', '/money_movements', payload=payload, idempotency_key=idempotency_key
        )

    def find_money_movement(self, external_id):
        return self.request(
            'GET', '/money_movements', params={'external_id': external_id, 'page_size': 1}
        )

    def create_fx_quote(self, payload):
        return self.request('POST', '/fx_quotes', payload=payload)

    def create_cross_border_movement(self, payload, *, idempotency_key):
        return self.request(
            'POST', '/cross_border_money_movements',
            payload=payload,
            idempotency_key=idempotency_key,
        )

    def find_cross_border_movement(self, external_id):
        return self.request(
            'GET', '/cross_border_money_movements',
            params={'external_id': external_id, 'page_size': 1},
        )


class InfiniaClient(BaseProviderClient):
    provider = 'infinia'

    def __init__(self, *, session=None):
        super().__init__(
            base_url=getattr(
                settings,
                'INFINIA_API_URL',
                'https://app2test.infiniaweb.com/infinia_api',
            ),
            timeout=getattr(settings, 'PAYMENT_PROVIDER_TIMEOUT_SECONDS', 20),
            session=session,
        )
        self.secret_id = getattr(settings, 'INFINIA_SECRET_ID', '')
        self.secret_password = getattr(settings, 'INFINIA_SECRET_PASSWORD', '')
        self.company_id = getattr(settings, 'INFINIA_COMPANY_ID', '')

    @property
    def is_configured(self):
        return bool(self.secret_id and self.secret_password)

    def request(self, method, path, *, payload=None, params=None):
        if not self.is_configured:
            raise ProviderConfigurationError('Infinia credentials are not configured')
        headers = {}
        if self.company_id:
            headers['X-Company-Id'] = str(self.company_id)
        parsed = self._request(
            method,
            f'{self.base_url}/{path.lstrip("/")}',
            action=f'Infinia {method} {path} failed',
            json=payload,
            params=params,
            headers=headers,
            auth=(self.secret_id, self.secret_password),
        )
        if (
            isinstance(parsed, dict)
            and str(parsed.get('status') or '').lower() == 'success'
            and 'data' in parsed
        ):
            return parsed['data']
        return parsed

    def create_owner(self, payload):
        return self.request('POST', '/v1/accounts/owners/', payload=payload)

    def find_owner(self, idempotency_key):
        return self.request(
            'GET',
            '/v1/accounts/owners/',
            params={'idempotency_key': idempotency_key, 'page_size': 1},
        )

    def initiate_owner_document(self, *, document_type, double_sided=False):
        return self.request(
            'POST',
            '/v1/accounts/owners/documents/',
            payload={
                'document_type': document_type,
                'double_sided': bool(double_sided),
            },
        )

    def upload_owner_document(self, upload_url, content, *, content_type):
        """Upload raw evidence to an Infinia-issued presigned URL without auth."""
        parsed = urlparse(str(upload_url or ''))
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ComplianceHandoffError('Infinia document upload URL must use HTTPS')
        try:
            response = self.session.put(
                upload_url,
                data=content,
                headers={'Content-Type': content_type},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ProviderAPIError(
                'Infinia document upload failed: network error', retryable=True
            ) from exc
        if not response.ok:
            raise ProviderAPIError(
                f'Infinia document upload failed: {response.status_code}',
                status_code=response.status_code,
                retryable=response.status_code >= 500,
            )

    def get_owner(self, owner_id):
        return self.request('GET', f'/v1/accounts/owners/{owner_id}/')

    def create_account(self, payload):
        return self.request('POST', '/v1/accounts/', payload=payload)

    def get_account(self, account_id):
        return self.request('GET', f'/v1/accounts/{account_id}/')

    def create_payout(self, payload):
        try:
            return self.request('POST', '/v2/payouts/', payload=payload)
        except ProviderAPIError as exc:
            # Infinia documents HTTP 412 as a terminal payout record returned
            # in `data`, not as an unknown transport outcome.
            if exc.status_code == 412 and isinstance(exc.payload, dict):
                data = exc.payload.get('data')
                if isinstance(data, dict):
                    return data
            raise

    def create_internal_transfer(self, payload):
        return self.request('POST', '/v1/accounts/internal-transfer/', payload=payload)

    def find_operation(self, operation_type, idempotency_key):
        if operation_type == 'payout':
            path, params = '/v2/payouts/', {'origin_id': idempotency_key}
        elif operation_type == 'payin':
            path, params = '/v1/payments/', {'reference': idempotency_key}
        elif operation_type in {'internal_transfer', 'conversion'}:
            path = '/v1/internal-transfers/'
            params = {'idempotency_key': idempotency_key}
        else:
            raise ProviderAPIError(f'Infinia cannot reconcile {operation_type}')
        return self.request('GET', path, params=params)


def verify_cobre_signature(raw_body, timestamp, signature, secret):
    if not timestamp or not signature or not secret:
        return False
    digest = hmac.new(
        secret.encode('utf-8'),
        timestamp.encode('utf-8') + b'.' + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, signature)


def verify_infinia_signature(raw_body, signature, secret_id):
    if not signature or not secret_id:
        return False
    computed = hmac.new(secret_id.encode('utf-8'), raw_body, hashlib.sha256).digest()
    try:
        provided = base64.b64decode(signature, validate=True)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(computed, provided)


def first_item(payload: Any):
    if isinstance(payload, list):
        return payload[0] if payload else None
    if not isinstance(payload, dict):
        return None
    for key in (
        'items', 'results', 'data', 'contents', 'accounts', 'keys', 'counterparties',
        'money_movements', 'payouts', 'payments', 'internal_transfers',
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return value[0] if value else None
    return payload if payload.get('id') else None
