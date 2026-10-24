"""HTTP client for Pago ASAP's partner API (gateway …/partners/v2).

Auth is an Auth0 client-credentials token (24 h), cached. Every POST needs an
`Idempotency-Key` UUID: the same key replays the first answer, even for a
different body, so a retry with new details must use a new key.
"""
from __future__ import annotations

import base64
import logging
import time
import uuid
from decimal import Decimal

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 20
TOKEN_CACHE_KEY = 'pagoasap:token'


class PagoAsapError(Exception):
    def __init__(self, message: str, *, status: int | None = None, code: str = '', payload=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.payload = payload


class PagoAsapAmbiguousError(PagoAsapError):
    """The request may have reached Pago ASAP; its outcome is unknown."""


def idempotency_key(seed: str) -> str:
    """A UUID that is the same for the same seed (an attempt replays its own
    key after a restart), and different for every new attempt."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f'confio:pagoasap:{seed}'))


class PagoAsapClient:
    def __init__(self, *, session: requests.Session | None = None, timeout: int = DEFAULT_TIMEOUT_S):
        self.client_id = getattr(settings, 'PAGOASAP_CLIENT_ID', '') or ''
        self.client_secret = getattr(settings, 'PAGOASAP_CLIENT_SECRET', '') or ''
        self.auth_url = getattr(settings, 'PAGOASAP_AUTH_URL', '') or ''
        self.audience = getattr(settings, 'PAGOASAP_AUDIENCE', '') or ''
        self.base_url = (getattr(settings, 'PAGOASAP_API_URL', '') or '').rstrip('/')
        self.session = session or requests.Session()
        self.timeout = timeout

    @property
    def is_configured(self) -> bool:
        return all((self.client_id, self.client_secret, self.auth_url, self.audience, self.base_url))

    def _token(self, *, refresh: bool = False) -> str:
        if not refresh:
            cached = cache.get(TOKEN_CACHE_KEY)
            if cached:
                return cached
        try:
            response = self.session.post(self.auth_url, timeout=self.timeout, json={
                'client_id': self.client_id, 'client_secret': self.client_secret,
                'audience': self.audience, 'grant_type': 'client_credentials',
            })
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise PagoAsapError(f'Pago ASAP auth failed ({type(exc).__name__})') from exc
        token = payload.get('access_token') if isinstance(payload, dict) else None
        if not response.ok or not token:
            raise PagoAsapError('Pago ASAP auth refused', status=response.status_code)
        expires = int(payload.get('expires_in') or 3600)
        cache.set(TOKEN_CACHE_KEY, token, max(expires - 300, 60))
        return token

    def _request(self, method: str, path: str, *, json_body=None, params=None, idempotency_key: str = '',
                 _retried: bool = False):
        if not self.is_configured:
            raise PagoAsapError('Pago ASAP is not configured')
        headers = {'Authorization': f'Bearer {self._token()}', 'accept': 'application/json'}
        if idempotency_key:
            headers['idempotency-key'] = idempotency_key
        try:
            response = self.session.request(method, f'{self.base_url}/v2{path}', json=json_body, params=params,
                                            headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            # Never include the exception text: it can carry the URL.
            message = f'Pago ASAP request failed ({type(exc).__name__})'
            if method != 'GET':
                raise PagoAsapAmbiguousError(message) from exc
            raise PagoAsapError(message) from exc
        if response.status_code == 401 and not _retried:
            # An expired or revoked token: no request was processed.
            self._token(refresh=True)
            return self._request(method, path, json_body=json_body, params=params,
                                 idempotency_key=idempotency_key, _retried=True)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if method != 'GET' and (response.status_code >= 500 or (response.ok and payload is None)):
            raise PagoAsapAmbiguousError(f'Pago ASAP returned HTTP {response.status_code}',
                                         status=response.status_code, payload=payload)
        if not response.ok or not isinstance(payload, dict) or payload.get('status') == 'error':
            code = str((payload or {}).get('error') or '')[:120] if isinstance(payload, dict) else ''
            raise PagoAsapError(code or f'Pago ASAP returned HTTP {response.status_code}',
                                status=response.status_code, code=code, payload=payload)
        return payload.get('payload') if 'payload' in payload else payload

    # Reads ------------------------------------------------------------------

    def balances(self) -> dict:
        """{symbol: balance}."""
        payload = self._request('GET', '/balance') or {}
        return {str(b.get('symbol') or '').upper(): Decimal(str(b.get('balance') or '0'))
                for b in payload.get('balances') or []}

    def rate(self, source: str = 'USD', target: str = 'VES') -> Decimal:
        payload = self._request('GET', '/rate', params={'from': source, 'to': target}) or {}
        return Decimal(str(payload.get('rate') or '0'))

    def reference_rate(self) -> Decimal:
        """Market reference (Binance P2P based), VES per USD."""
        payload = self._request('GET', '/referenceVes') or {}
        return Decimal(str(payload.get('rate') or '0'))

    def preview(self, amount_ves: Decimal) -> dict:
        """Cost in USD of paying `amount_ves`: {rate, base, fees, total}."""
        return self._request('GET', '/payments/preview', params={'amountVES': str(amount_ves)}) or {}

    def payout(self, intent_id: str) -> dict:
        return (self._request('GET', f'/payments/pago-movil/{intent_id}') or {}).get('intent') or {}

    # Writes -----------------------------------------------------------------

    def create_payout(self, *, phone: str, amount_ves: Decimal, cedula: str, bank_code: str, order_ref: str,
                      idempotency_key: str) -> str:
        """Pago Móvil to a third party. Returns the intent id."""
        payload = self._request('POST', '/payments/pago-movil', idempotency_key=idempotency_key, json_body={
            'phoneNumber': phone,
            'amountVES': float(amount_ves),
            'destinaryDocumentNumber': cedula,
            'bankCode': bank_code,
            'metadata': {'source': 'confio', 'orderNumber': order_ref},
        }) or {}
        intent_id = str(payload.get('intentId') or '')
        if not intent_id:
            raise PagoAsapAmbiguousError('Pago ASAP accepted a payout without an intent id')
        return intent_id


def verify_webhook_signature(raw_body: bytes, signature_b64: str, public_key_pem: str) -> bool:
    """`X-Webhook-Signature`: base64 Ed25519 over the exact raw body."""
    if not raw_body or not signature_b64 or not public_key_pem:
        return False
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        key = load_pem_public_key(public_key_pem.encode())
        key.verify(base64.b64decode(signature_b64), raw_body)
        return True
    except Exception:  # noqa: BLE001 — any parse or verify failure is a rejection
        return False


def now() -> float:
    return time.time()
