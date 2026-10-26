"""Mesa de pagos partner API (ON RAMP, v2), the calls QR Bolivia uses.

Auth: POST /v2/auth/login (partner email + password) returns a JWT sent as
`Authorization: Bearer`. The token's lifetime is not documented: it is cached
briefly and a 401 re-logs in once.

Writes are classified like the other provider clients: a definite refusal
(4xx other than 408/409) is safe to report; a timeout, 5xx, 408/409 or an
unreadable answer is ambiguous and must never be blindly retried.
"""
from __future__ import annotations

import base64
import io
import logging
from decimal import Decimal

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 25
TOKEN_CACHE_KEY = 'mesadepagos:jwt'
TOKEN_CACHE_SECONDS = 20 * 60
BLOCKCHAIN = 'Polygon'
ASSET = 'USDC'


class MesaDePagosError(Exception):
    def __init__(self, message: str, *, status: int | None = None, code: str = '', ambiguous: bool = False):
        super().__init__(message)
        self.status = status
        self.code = code
        self.ambiguous = ambiguous


class MesaDePagosConfigurationError(MesaDePagosError):
    pass


def qr_png_base64(payload: str) -> str:
    """A Bolivian QR's text rendered back into a PNG (the API only takes
    images), base64 without a data: prefix."""
    import qrcode
    image = qrcode.make(payload, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('ascii')


class MesaDePagosClient:
    def __init__(self, *, base_url: str | None = None, email: str | None = None, password: str | None = None,
                 timeout: int = DEFAULT_TIMEOUT_S, session: requests.Session | None = None):
        self.base_url = (base_url or getattr(settings, 'MESADEPAGOS_API_URL', '')).rstrip('/')
        self.email = email if email is not None else getattr(settings, 'MESADEPAGOS_EMAIL', '')
        self.password = password if password is not None else getattr(settings, 'MESADEPAGOS_PASSWORD', '')
        self.timeout = timeout
        self.session = session or requests.Session()

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url.startswith('https://') and self.email and self.password)

    # -------------------------------------------------------------- transport

    def _login(self) -> str:
        if not self.is_configured:
            raise MesaDePagosConfigurationError('Mesa de pagos is not configured')
        try:
            response = self.session.post(f'{self.base_url}/v2/auth/login', timeout=self.timeout,
                                         json={'email': self.email, 'password': self.password})
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise MesaDePagosError('Mesa de pagos login failed', ambiguous=True) from exc
        token = body.get('accessToken') if isinstance(body, dict) else None
        if response.status_code != 200 or not token:
            raise MesaDePagosConfigurationError('Mesa de pagos login refused', status=response.status_code)
        cache.set(TOKEN_CACHE_KEY, token, TOKEN_CACHE_SECONDS)
        return token

    def _token(self) -> str:
        return cache.get(TOKEN_CACHE_KEY) or self._login()

    def request(self, method: str, path: str, *, payload=None, params=None, writes: bool = False, retried=False):
        token = self._token()
        try:
            response = self.session.request(
                method, f'{self.base_url}{path}', json=payload, params=params, timeout=self.timeout,
                headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'})
        except requests.RequestException as exc:
            raise MesaDePagosError('Mesa de pagos unreachable', ambiguous=writes) from exc
        if response.status_code == 401 and not retried:
            cache.delete(TOKEN_CACHE_KEY)
            return self.request(method, path, payload=payload, params=params, writes=writes, retried=True)
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code >= 400 or body is None:
            ambiguous = writes and (body is None or response.status_code >= 500 or response.status_code in (408, 409))
            code = ''
            if isinstance(body, dict):
                code = str(body.get('code') or body.get('error') or '')
            raise MesaDePagosError(f'Mesa de pagos error {response.status_code}', status=response.status_code,
                                   code=code, ambiguous=ambiguous)
        return body

    # -------------------------------------------------------------- calls

    def quote(self, pair: str, transaction_type: str) -> dict:
        """Indicative rate (no lock, no id): pair like USDC/BOB."""
        rows = self.request('GET', '/v2/quotes', params={'pair': pair, 'transaction_type': transaction_type})
        rows = rows if isinstance(rows, list) else (rows or {}).get('quotes') or []
        if not rows or not isinstance(rows[0], dict):
            raise MesaDePagosError('Mesa de pagos returned no quote')
        return rows[0]

    def create_deposit_qr(self, *, reference: str, crypto_amount: Decimal, deposit_address: str,
                          expiration: str = '00:15:00', description: str = '') -> dict:
        """A one-time BO QR; its bolivianos are converted and sent as USDC on
        Polygon to `deposit_address`."""
        return self.request('POST', '/v2/transactions/deposit/qr', writes=True, payload={
            'fundingSource': 'conversion', 'country': 'BO', 'fiatCurrency': 'BOB', 'referenceId': reference,
            'cryptoAmount': float(crypto_amount), 'asset': ASSET, 'blockchain': BLOCKCHAIN,
            'depositAddress': deposit_address, 'qrExpirationTime': expiration,
            **({'description': description[:60]} if description else {}),
        })

    def validate_qr(self, payload: str) -> dict:
        return self.request('POST', '/v2/transactions/payouts/validate/qr', payload={'image': qr_png_base64(payload)})

    def create_payout_qr(self, *, payload: str, reference: str, amount: Decimal | None) -> dict:
        """Pay a BO QR funded per order: answers with the Polygon address and
        the USDC amount that, once received, execute the payment."""
        body = {'image': qr_png_base64(payload), 'external_reference': reference[:32],
                'funding_source': 'conversion', 'asset_deposit': ASSET, 'blockchain': BLOCKCHAIN}
        if amount is not None:
            body['amount'] = float(amount)
        return self.request('POST', '/v2/transactions/payouts/qr', writes=True, payload=body)

    def find(self, reference: str, *, transaction_type: str) -> dict | None:
        """The transaction with this reference (there is no GET by id)."""
        body = self.request('GET', '/v2/transactions/history', params={
            'search': reference, 'type': transaction_type, 'limit': 10, 'page': 1})
        for row in (body or {}).get('transactions') or []:
            if isinstance(row, dict) and str(row.get('externalReference') or '') == reference:
                return row
        return None
