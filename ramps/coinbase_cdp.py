"""Coinbase CDP (Onramp/Offramp) API client.

Auth is a short-lived EdDSA JWT signed with the CDP secret API key
(Ed25519, stored in Secrets Manager as prod/coinbase-cdp-api). Used for:
  - session tokens (buy widget for the US ACH→ALGO on-ramp,
    sell widget for the US ALGO→ACH off-ramp)
  - the sell Transaction Status API, which is where Coinbase publishes the
    `to_address` deposit address the user must fund (offramp step 2).

The offramp trust rule: `to_address` is ONLY ever read server-side from this
API — a client-supplied destination is never accepted anywhere.
"""
import base64
import json
import logging
import secrets
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

CDP_HOST = 'api.developer.coinbase.com'


class CoinbaseCdpError(Exception):
    pass


def _mint_jwt(method: str, path: str) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import jwt as py_jwt

    key_id = getattr(settings, 'COINBASE_CDP_KEY_ID', '')
    secret = getattr(settings, 'COINBASE_CDP_SECRET', '')
    if not key_id or not secret:
        raise CoinbaseCdpError('coinbase_cdp_not_configured')
    priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(secret)[:32])
    now = int(time.time())
    return py_jwt.encode(
        {
            'iss': 'cdp', 'sub': key_id, 'nbf': now, 'exp': now + 110,
            'uris': [f'{method} {CDP_HOST}{path}'], 'uri': f'{method} {CDP_HOST}{path}',
        },
        priv, algorithm='EdDSA',
        headers={'kid': key_id, 'nonce': secrets.token_hex(16)},
    )


def _request(method: str, path: str, payload: dict | None = None, query: str = '') -> dict:
    token = _mint_jwt(method, path)
    url = f'https://{CDP_HOST}{path}{query}'
    resp = requests.request(
        method, url,
        json=payload,
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        timeout=15,
    )
    if not resp.ok:
        logger.error('CDP %s %s failed: %s %s', method, path, resp.status_code, resp.text[:300])
        raise CoinbaseCdpError(f'cdp_http_{resp.status_code}')
    return resp.json()


def create_session_token(address: str, assets: list[str]) -> str:
    data = _request('POST', '/onramp/v1/token', {
        'addresses': [{'address': address, 'blockchains': ['algorand']}],
        'assets': assets,
    })
    token = data.get('token')
    if not token:
        raise CoinbaseCdpError('empty_session_token')
    return token


def partner_user_ref(user_id) -> str:
    return f'confio-{user_id}'


def list_sell_transactions(ref: str) -> list[dict]:
    data = _request('GET', f'/onramp/v1/sell/user/{ref}/transactions')
    return data.get('transactions', []) or []


def _parse_amount(value) -> str | None:
    """CDP amounts arrive either as {'value': '12.3', 'currency': 'ALGO'} or a bare string."""
    if isinstance(value, dict):
        return value.get('value')
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def get_latest_pending_sell(ref: str) -> dict | None:
    """Newest sell transaction that is still waiting for the user's deposit.

    Returns {'to_address', 'sell_amount', 'asset', 'network', 'status',
    'transaction_id'} or None. Offramp deposits time out 30 minutes after the
    user initiates the cash-out, so anything older is ignored.
    """
    terminal_markers = ('SUCCESS', 'FAILED', 'EXPIRED', 'CANCEL')
    for tx in list_sell_transactions(ref):
        status = str(tx.get('status', '')).upper()
        if any(m in status for m in terminal_markers):
            continue
        to_address = tx.get('to_address') or tx.get('sell_address')
        amount = _parse_amount(tx.get('sell_amount'))
        if not to_address or not amount:
            continue
        return {
            'to_address': to_address,
            'sell_amount': amount,
            'asset': (tx.get('asset') or '').upper(),
            'network': tx.get('network') or '',
            'status': status,
            'transaction_id': tx.get('transaction_id') or tx.get('id') or '',
        }
    return None
