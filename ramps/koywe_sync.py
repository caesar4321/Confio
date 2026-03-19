from __future__ import annotations

import hashlib
import hmac
import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.utils import timezone

from ramps.models import RampTransaction

logger = logging.getLogger(__name__)

_KOYWE_COMPLETED_STATUSES = {'DELIVERED', 'CRYPTO_DELIVERED', 'FIAT_DELIVERED'}
_KOYWE_FAILED_STATUSES = {
    'REJECTED',
    'FAILED',
    'CANCELLED',
    'REFUNDED',
    'REFUND_DELIVERED',
    'INVALID_WITHDRAWALS_DETAILS',
}
_KOYWE_PROCESSING_STATUSES = {
    'PAYMENT_CREATED',
    'PAYMENT_RECEIVED',
    'PENDING',
    'EXECUTING',
    'IN_PROGRESS',
    'CRYPTO_TX_SENT',
    'FIAT_SENT',
}
_KOYWE_PENDING_STATUSES = {'WAITING'}


def verify_koywe_webhook_signature(raw_body: bytes, signature_header: str | None) -> bool:
    secret = (getattr(settings, 'KOYWE_WEBHOOK_SECRET', '') or '').strip()
    if not secret:
        return True
    provided = (signature_header or '').strip()
    if not provided:
        return False
    expected = hmac.new(
        secret.encode('utf-8'),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, provided)


def extract_koywe_event_id(payload: dict[str, Any]) -> str | None:
    event_id = payload.get('id') or payload.get('eventId') or payload.get('_id')
    if event_id:
        return str(event_id)

    order_id = extract_koywe_order_id(payload)
    event_type = extract_koywe_event_type(payload) or 'event'
    timestamp = (
        payload.get('createdAt')
        or payload.get('timestamp')
        or payload.get('occurredAt')
        or payload.get('processedAt')
    )
    if order_id or timestamp:
        return f'koywe:{event_type}:{order_id or "unknown"}:{timestamp or "unknown"}'
    return None


def extract_koywe_event_type(payload: dict[str, Any]) -> str:
    return str(
        payload.get('type')
        or payload.get('eventType')
        or payload.get('event')
        or payload.get('status')
        or ''
    ).strip()


def extract_koywe_order_id(payload: dict[str, Any]) -> str | None:
    candidates = [
        payload.get('orderId'),
        payload.get('paymentId'),
        payload.get('id'),
        payload.get('_id'),
        (payload.get('data') or {}).get('orderId') if isinstance(payload.get('data'), dict) else None,
        (payload.get('order') or {}).get('orderId') if isinstance(payload.get('order'), dict) else None,
        (payload.get('payment') or {}).get('orderId') if isinstance(payload.get('payment'), dict) else None,
    ]
    for candidate in candidates:
        if candidate:
            return str(candidate)
    return None


def map_koywe_status(status: str | None) -> tuple[str, str]:
    normalized = str(status or '').strip().upper()
    if normalized in _KOYWE_COMPLETED_STATUSES:
        return 'COMPLETED', normalized.lower()
    if normalized in _KOYWE_FAILED_STATUSES:
        if normalized == 'INVALID_WITHDRAWALS_DETAILS':
            return 'FAILED', 'invalid_withdrawals_details'
        if normalized == 'REFUND_DELIVERED':
            return 'FAILED', 'refund_delivered'
        return 'FAILED', normalized.lower()
    if normalized in _KOYWE_PROCESSING_STATUSES:
        return 'PROCESSING', normalized.lower()
    if normalized in _KOYWE_PENDING_STATUSES:
        return 'PENDING', normalized.lower()
    if normalized:
        return 'PENDING', normalized.lower()
    return 'PENDING', 'pending'


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _normalize_direction(value: str | None) -> str:
    normalized = str(value or '').strip().upper()
    if normalized in {'OFF_RAMP', 'OFF-RAMP', 'SELL'}:
        return 'off_ramp'
    return 'on_ramp'


def _extract_order_status_payload(order_payload: dict[str, Any] | None) -> tuple[str, str]:
    status = str((order_payload or {}).get('status') or '').strip().upper()
    status_details = str((order_payload or {}).get('statusDetails') or '').strip()
    return status, status_details


def _extract_metadata(
    *,
    payment_method_code: str | None,
    payment_method_display: str | None,
    next_action_url: str | None,
    auth_email: str | None,
    order_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    metadata = {
        'payment_method_code': payment_method_code or '',
        'payment_method_display': payment_method_display or '',
        'next_action_url': next_action_url or '',
        'auth_email': auth_email or '',
    }
    if order_payload:
        metadata['koywe_status'] = str(order_payload.get('status') or '').strip()
        metadata['payment_details'] = order_payload
    return metadata


def upsert_koywe_ramp_transaction(
    *,
    actor_user,
    actor_business,
    actor_type: str,
    actor_display_name: str,
    actor_address: str,
    direction: str,
    country_code: str,
    fiat_currency: str,
    payment_method_code: str,
    payment_method_display: str,
    order_id: str,
    external_id: str | None,
    amount_in: str | Decimal | None,
    amount_out: str | Decimal | None,
    next_action_url: str | None,
    auth_email: str | None,
    order_payload: dict[str, Any] | None,
) -> RampTransaction:
    normalized_direction = _normalize_direction(direction)
    fiat_amount = _to_decimal(amount_in) if normalized_direction == 'on_ramp' else _to_decimal(amount_out)
    crypto_estimated = _to_decimal(amount_out) if normalized_direction == 'on_ramp' else _to_decimal(amount_in)
    final_amount = _to_decimal(amount_out) if normalized_direction == 'on_ramp' else _to_decimal(amount_in)
    status_raw, status_details = _extract_order_status_payload(order_payload)
    ramp_status, normalized_detail = map_koywe_status(status_raw)
    completed_at = timezone.now() if ramp_status == 'COMPLETED' else None
    status_detail = normalized_detail if not status_details else f'{normalized_detail}: {status_details}'

    defaults = {
        'provider': 'koywe',
        'direction': normalized_direction,
        'status': ramp_status,
        'provider_order_id': order_id,
        'external_id': external_id or '',
        'country_code': (country_code or '').upper(),
        'actor_user': actor_user,
        'actor_business': actor_business,
        'actor_type': actor_type or 'user',
        'actor_display_name': actor_display_name or '',
        'actor_address': actor_address or '',
        'fiat_currency': fiat_currency or '',
        'fiat_amount': fiat_amount,
        'crypto_currency': getattr(settings, 'KOYWE_CRYPTO_SYMBOL', 'USDC Solana'),
        'crypto_amount_estimated': crypto_estimated,
        'crypto_amount_actual': None,
        'final_currency': 'CUSD' if normalized_direction == 'on_ramp' else getattr(settings, 'KOYWE_CRYPTO_SYMBOL', 'USDC Solana'),
        'final_amount': final_amount,
        'status_detail': status_detail,
        'metadata': _extract_metadata(
            payment_method_code=payment_method_code,
            payment_method_display=payment_method_display,
            next_action_url=next_action_url,
            auth_email=auth_email,
            order_payload=order_payload,
        ),
        'completed_at': completed_at,
    }
    ramp_tx, _ = RampTransaction.objects.update_or_create(
        provider='koywe',
        provider_order_id=order_id,
        defaults=defaults,
    )
    return ramp_tx


def sync_koywe_ramp_transaction_from_order(
    *,
    ramp_tx: RampTransaction,
    order_payload: dict[str, Any] | None,
    next_action_url: str | None = None,
) -> RampTransaction:
    order_payload = order_payload or {}
    status_raw, status_details = _extract_order_status_payload(order_payload)
    ramp_status, normalized_detail = map_koywe_status(status_raw)

    amount_in = _to_decimal(order_payload.get('amountIn'))
    amount_out = _to_decimal(order_payload.get('amountOut'))
    direction = ramp_tx.direction or _normalize_direction(
        order_payload.get('flow')
        or order_payload.get('direction')
        or order_payload.get('type')
    )

    if direction == 'on_ramp':
        ramp_tx.fiat_amount = amount_in or ramp_tx.fiat_amount
        ramp_tx.crypto_amount_estimated = amount_out or ramp_tx.crypto_amount_estimated
        ramp_tx.final_currency = 'CUSD'
        ramp_tx.final_amount = amount_out or ramp_tx.final_amount
    else:
        ramp_tx.fiat_amount = amount_out or ramp_tx.fiat_amount
        ramp_tx.crypto_amount_estimated = amount_in or ramp_tx.crypto_amount_estimated
        ramp_tx.crypto_amount_actual = amount_in or ramp_tx.crypto_amount_actual
        ramp_tx.final_currency = getattr(settings, 'KOYWE_CRYPTO_SYMBOL', 'USDC Solana')
        ramp_tx.final_amount = amount_in or ramp_tx.final_amount

    ramp_tx.status = ramp_status
    ramp_tx.status_detail = normalized_detail if not status_details else f'{normalized_detail}: {status_details}'
    if ramp_status == 'COMPLETED':
        ramp_tx.completed_at = ramp_tx.completed_at or timezone.now()
    elif ramp_status in {'FAILED', 'AML_REVIEW', 'PROCESSING', 'PENDING'}:
        if ramp_status != 'FAILED':
            ramp_tx.completed_at = None

    metadata = dict(ramp_tx.metadata or {})
    metadata.update(
        _extract_metadata(
            payment_method_code=metadata.get('payment_method_code'),
            payment_method_display=metadata.get('payment_method_display'),
            next_action_url=next_action_url,
            auth_email=metadata.get('auth_email'),
            order_payload=order_payload,
        )
    )
    ramp_tx.metadata = metadata
    ramp_tx.save(
        update_fields=[
            'fiat_amount',
            'crypto_amount_estimated',
            'crypto_amount_actual',
            'final_currency',
            'final_amount',
            'status',
            'status_detail',
            'metadata',
            'completed_at',
            'updated_at',
        ]
    )
    return ramp_tx


def pretty_print_koywe_payload(payload: dict[str, Any]) -> str:
    try:
        return json.dumps(payload, sort_keys=True)
    except TypeError:
        logger.warning('Failed to serialize Koywe payload for logging')
        return '{}'
