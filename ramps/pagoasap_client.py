"""HTTP client for Pago ASAP's partner API (gateway …/partners/v2).

Auth is an Auth0 client-credentials token (24 h), cached. Every POST needs an
`Idempotency-Key` UUID: the same key replays the first answer, even for a
different body, so a retry with new details must use a new key.

With a signing key configured, every v2 request also carries an RFC 9421
Ed25519 signature (Content-Digest, Signature-Input, Signature) over the exact
bytes sent. Each attempt is signed afresh: new `created`, new `nonce`.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
import uuid
from decimal import Decimal
from urllib.parse import urlsplit

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


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def key_id(public_x: str) -> str:
    """RFC 7638 thumbprint of the Ed25519 public key (base64url `x`)."""
    canonical = json.dumps({'crv': 'Ed25519', 'kty': 'OKP', 'x': public_x}, separators=(',', ':'), sort_keys=True)
    return base64.urlsafe_b64encode(hashlib.sha256(canonical.encode()).digest()).decode().rstrip('=')


def public_x(private_key) -> str:
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    raw = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def signature_base(method: str, url: str, authorization: str, body: bytes | None, *,
                   created: int, keyid: str, nonce: str) -> tuple[str, str, str]:
    """(signature base, Signature-Input value, Content-Digest or '') for
    Pago ASAP's profile: @method @authority @path [@query] authorization
    [content-digest]; params created, keyid, nonce, alg."""
    parts = urlsplit(url)
    authority = (parts.hostname or '').lower()
    if parts.port and parts.port != 443:
        authority = f'{authority}:{parts.port}'
    lines = [('@method', method.upper()), ('@authority', authority), ('@path', parts.path or '/')]
    if '?' in url:
        lines.append(('@query', f'?{parts.query}'))
    lines.append(('authorization', authorization))
    digest = ''
    if body:
        digest = f'sha-256=:{_b64(hashlib.sha256(body).digest())}:'
        lines.append(('content-digest', digest))
    params = (f'({" ".join(chr(34) + name + chr(34) for name, _ in lines)})'
              f';created={created};keyid="{keyid}";nonce="{nonce}";alg="ed25519"')
    base = '\n'.join([f'"{name}": {value}' for name, value in lines] + [f'"@signature-params": {params}'])
    return base, params, digest


class PagoAsapClient:
    def __init__(self, *, session: requests.Session | None = None, timeout: int = DEFAULT_TIMEOUT_S):
        self.client_id = getattr(settings, 'PAGOASAP_CLIENT_ID', '') or ''
        self.client_secret = getattr(settings, 'PAGOASAP_CLIENT_SECRET', '') or ''
        self.auth_url = getattr(settings, 'PAGOASAP_AUTH_URL', '') or ''
        self.audience = getattr(settings, 'PAGOASAP_AUDIENCE', '') or ''
        self.base_url = (getattr(settings, 'PAGOASAP_API_URL', '') or '').rstrip('/')
        self.session = session or requests.Session()
        self.timeout = timeout
        self.signing_key = None
        pem = getattr(settings, 'PAGOASAP_SIGNING_PRIVATE_KEY', '') or ''
        if pem:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            # A configured key that does not load must stop the client, never
            # fall back to unsigned requests.
            self.signing_key = load_pem_private_key(pem.encode(), password=None)
            self.signing_key_id = key_id(public_x(self.signing_key))

    def _sign(self, prepared: requests.PreparedRequest) -> None:
        body = prepared.body.encode() if isinstance(prepared.body, str) else prepared.body
        base, params, digest = signature_base(
            prepared.method, prepared.url, prepared.headers['Authorization'], body,
            created=int(time.time()), keyid=self.signing_key_id, nonce=secrets.token_urlsafe(18))
        if digest:
            prepared.headers['Content-Digest'] = digest
        prepared.headers['Signature-Input'] = f'sig1={params}'
        prepared.headers['Signature'] = f'sig1=:{_b64(self.signing_key.sign(base.encode()))}:'

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
        if json_body is not None:
            headers['content-type'] = 'application/json'
        try:
            # Exact bytes, prepared before signing: the signature covers them.
            prepared = self.session.prepare_request(requests.Request(
                method, f'{self.base_url}/v2{path}', params=params, headers=headers,
                data=None if json_body is None else json.dumps(json_body, separators=(',', ':')).encode()))
            if self.signing_key is not None:
                self._sign(prepared)
            # Same proxy/CA environment as session.request. Never follow a
            # redirect: it would carry a signature over the original URL.
            options = self.session.merge_environment_settings(prepared.url, {}, None, None, None)
            response = self.session.send(prepared, timeout=self.timeout, allow_redirects=False, **options)
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
            # The error key moved from `code` to `error` (Pago ASAP, 2026-11-03).
            code = (str(payload.get('error') or payload.get('code') or '')[:120]
                    if isinstance(payload, dict) else '')
            raise PagoAsapError(code or f'Pago ASAP returned HTTP {response.status_code}',
                                status=response.status_code, code=code, payload=payload)
        return payload.get('payload') if 'payload' in payload else payload

    # Reads ------------------------------------------------------------------

    def balances(self) -> dict:
        """{symbol: balance}. Their dollar balance is named "USD" from
        2026-11-03 and "USDT" before; both read as "USD"."""
        payload = self._request('GET', '/balance') or {}
        balances = {}
        for b in payload.get('balances') or []:
            symbol = str(b.get('symbol') or '').upper()
            balances['USD' if symbol == 'USDT' else symbol] = Decimal(str(b.get('balance') or '0'))
        return balances

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
