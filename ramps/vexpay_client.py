"""HTTP client for VEXPay (https://docs.pay.vexwallet.co).

Venezuelan bolívar pay-ins (C2P, Pago Móvil) with an `onwardPayout`: when a
payment completes, VEXPay converts its net VES to USDT and pays it to the
given wallet. Auth is a per-account `x-api-key`; the test key runs the same
chain on the sandbox without moving money.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from decimal import Decimal

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 20
SIGNATURE_TOLERANCE_S = 300


class VexPayError(Exception):
    def __init__(self, message: str, *, status: int | None = None, code: str = '', payload=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.payload = payload


class VexPayConfigurationError(VexPayError):
    pass


class VexPayAmbiguousError(VexPayError):
    """The request may have reached VEXPay; its outcome is unknown."""


@dataclass(frozen=True)
class OnwardPayout:
    network: str
    address: str

    def as_json(self) -> dict:
        return {'network': self.network, 'address': self.address}


class VexPayClient:
    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 timeout: int = DEFAULT_TIMEOUT_S, session: requests.Session | None = None):
        self.api_key = (api_key if api_key is not None else getattr(settings, 'VEXPAY_API_KEY', '')) or ''
        self.base_url = (base_url or getattr(settings, 'VEXPAY_API_URL', 'https://api.pay.vexwallet.co')).rstrip('/')
        self.timeout = timeout
        self.session = session or requests.Session()

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _request(self, method: str, path: str, *, json_body=None, params=None, idempotency_key: str = ''):
        if not self.is_configured:
            raise VexPayConfigurationError('VEXPay API key is not configured')
        headers = {'x-api-key': self.api_key, 'accept': 'application/json'}
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key
        try:
            response = self.session.request(
                method, f'{self.base_url}{path}', json=json_body, params=params,
                headers=headers, timeout=self.timeout,
            )
        except requests.RequestException as exc:
            # Never include the exception text: it can carry the request URL.
            # A write may have reached VEXPay before the connection dropped,
            # so any transport failure on one is an unknown outcome.
            message = f'VEXPay request failed ({type(exc).__name__})'
            if method != 'GET':
                raise VexPayAmbiguousError(message) from exc
            raise VexPayError(message) from exc
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.ok and payload is None and method != 'GET':
            raise VexPayAmbiguousError('VEXPay accepted a write with an unreadable response',
                                       status=response.status_code)
        if response.status_code >= 500 and method != 'GET':
            raise VexPayAmbiguousError(
                f'VEXPay returned HTTP {response.status_code}', status=response.status_code, payload=payload)
        if not response.ok:
            code, message = '', f'VEXPay returned HTTP {response.status_code}'
            if isinstance(payload, dict):
                code = str(payload.get('error') or payload.get('code') or '')[:80]
                raw_message = payload.get('message')
                if isinstance(raw_message, list):
                    raw_message = '; '.join(str(m) for m in raw_message)
                if raw_message:
                    message = str(raw_message)[:300]
            raise VexPayError(message, status=response.status_code, code=code, payload=payload)
        if payload is None:
            raise VexPayError('VEXPay returned a non-JSON response', status=response.status_code)
        return payload

    # Catalog -----------------------------------------------------------------

    def payment_methods(self) -> dict:
        return self._request('GET', '/v1/payment-methods')

    def banks(self) -> list:
        return self._request('GET', '/v1/banks')

    def quote_usd(self, usd_amount: Decimal) -> dict:
        return self._request('GET', '/v1/quote', params={'usdAmount': str(usd_amount)})

    def receiving_account(self) -> dict:
        return self._request('GET', '/v1/payments/pago-movil/receiving-account')

    def balance(self) -> dict:
        return self._request('GET', '/v1/balance')

    def conversion_settings(self) -> dict:
        return self._request('GET', '/v1/conversions/settings')

    def crypto_networks(self, currency: str = 'USDT') -> list:
        return self._request('GET', '/v1/crypto/networks', params={'currency': currency})

    # Pay-ins -----------------------------------------------------------------

    def c2p_request(self, *, usd_amount: Decimal, debtor_id: str, debtor_phone: str,
                    debtor_bank_code: int, external_ref: str, onward: OnwardPayout,
                    idempotency_key: str = '') -> dict:
        return self._request('POST', '/v1/payments/c2p/request', idempotency_key=idempotency_key, json_body={
            'usdAmount': float(usd_amount),
            'debtorId': debtor_id,
            'debtorCellPhone': debtor_phone,
            'debtorBankCode': int(debtor_bank_code),
            'externalRef': external_ref,
            'onwardPayout': onward.as_json(),
        })

    def c2p_execute(self, *, intent_id: str, token: str, debtor_id: str, debtor_phone: str,
                    debtor_bank_code: int, external_ref: str, onward: OnwardPayout,
                    idempotency_key: str = '') -> dict:
        return self._request('POST', '/v1/payments/c2p', idempotency_key=idempotency_key, json_body={
            'intentId': intent_id,
            'token': token,
            'debtorId': debtor_id,
            'debtorCellPhone': debtor_phone,
            'debtorBankCode': int(debtor_bank_code),
            'externalRef': external_ref,
            'onwardPayout': onward.as_json(),
        })

    def pago_movil_verify(self, *, usd_amount: Decimal, reference: str, external_ref: str,
                          onward: OnwardPayout, debtor_bank_code: str = '',
                          debtor_phone: str = '', date_movement: str = '',
                          idempotency_key: str = '') -> dict:
        body = {
            'usdAmount': float(usd_amount),
            'reference': reference,
            'externalRef': external_ref,
            'txType': 'pago_movil',
            'onwardPayout': onward.as_json(),
        }
        if debtor_bank_code:
            body['debtorBankCode'] = str(debtor_bank_code)
        if debtor_phone:
            body['debtorCellPhone'] = debtor_phone
        if date_movement:
            body['dateMovement'] = date_movement
        return self._request('POST', '/v1/payments/pago-movil/verify', json_body=body,
                             idempotency_key=idempotency_key)

    # Off-ramp ----------------------------------------------------------------

    def deposit_address(self, *, customer_ref: str, network: str, idempotency_key: str = '') -> dict:
        """The static USDT address for one customer ref (same ref, same address)."""
        return self._request('POST', '/v1/crypto/deposit-addresses', idempotency_key=idempotency_key,
                             json_body={'customerRef': customer_ref, 'network': network, 'currency': 'USDT'})

    def credit(self, *, bank_code: str, cedula: str, phone: str, ves_amount: Decimal, concept: str,
               idempotency_key: str) -> dict:
        """Crédito inmediato to a Pago Móvil destination. The key replays the
        stored answer for 24 h only; after that the same key pays again."""
        return self._request('POST', '/v1/payments/credit', idempotency_key=idempotency_key, json_body={
            'banco': bank_code,
            'cedula': cedula,
            'telefono': phone,
            'monto': float(ves_amount),
            'concepto': concept[:30],
        })

    def operation(self, operation_id: str) -> dict:
        return self._request('GET', f'/v1/payments/operations/{operation_id}')

    def get_payment(self, payment_id: str) -> dict:
        return self._request('GET', f'/v1/payments/{payment_id}')

    def get_payment_by_ref(self, external_ref: str) -> dict:
        return self._request('GET', f'/v1/payments/by-ref/{external_ref}')


def verify_webhook_signature(raw_body: bytes, header: str, secret: str, *,
                             now: float | None = None,
                             tolerance: int = SIGNATURE_TOLERANCE_S) -> bool:
    """`VexPay-Signature: t=<unix>,v1=<hex>`; v1 = HMAC-SHA256(secret, f'{t}.{raw}')."""
    if not secret or not header or raw_body is None:
        return False
    parts = {}
    for item in str(header).split(','):
        key, _, value = item.strip().partition('=')
        if key and value:
            parts.setdefault(key, []).append(value)
    try:
        timestamp = int(parts.get('t', [''])[0])
    except ValueError:
        return False
    current = time.time() if now is None else now
    if abs(current - timestamp) > tolerance:
        return False
    signed = f'{timestamp}.'.encode() + raw_body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in parts.get('v1', []))
