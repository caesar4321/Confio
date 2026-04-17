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


def verify_koywe_webhook_signature(payload: dict[str, Any]) -> bool:
    secret = (getattr(settings, 'KOYWE_WEBHOOK_SECRET', '') or '').strip()
    if not secret:
        return True
    provided = str(payload.get('signature') or '').strip()
    if not provided:
        return False
    unsigned_payload = {
        key: value
        for key, value in payload.items()
        if key != 'signature'
    }
    message = json.dumps(
        unsigned_payload,
        ensure_ascii=False,
        separators=(',', ':'),
    ).encode('utf-8')
    expected = hmac.new(
        secret.encode('utf-8'),
        message,
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
        or payload.get('eventName')
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


_MAX_DISCOVERY_DEPTH = 6
_SNAPSHOT_FIELD_ALIASES = {
    'beneficiary_name': {'beneficiary', 'beneficiaryname', 'accountholder', 'account_holder', 'holdername', 'holder', 'titular', 'name'},
    'bank_name': {'bank', 'bankname', 'institution', 'institutionname', 'entity', 'entidad', 'banco'},
    'bank_code': {'bankcode', 'bank_code'},
    'account_number': {'accountnumber', 'account_number', 'account', 'accountid', 'account_id'},
    'account_type': {'accounttype', 'account_type'},
    'alias': {'alias'},
    'cbu': {'cbu'},
    'cvu': {'cvu'},
    'clabe': {'clabe'},
    'cci': {'cci'},
    'pix_key': {'pixkey', 'pix_key'},
    'reference': {'reference', 'referencia', 'memo', 'concept', 'concepto', 'message', 'additionalreference', 'additional_reference', 'motivo'},
    'email': {'email'},
    'phone_number': {'phone', 'phonenumber', 'phone_number', 'telefono', 'celular'},
    'document_number': {'documentnumber', 'document_number', 'cuit', 'cuil', 'ruc', 'rut', 'dni', 'documentid'},
    'wallet_address': {'destinationaddress', 'walletaddress', 'wallet_address'},
}


def _normalize_key(value: str) -> str:
    return ''.join(ch for ch in str(value or '').strip().lower() if ch.isalnum())


def _normalize_json_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _maybe_parse_nested_json(value: str) -> Any:
    trimmed = value.strip()
    if not trimmed or trimmed[0] not in '{[':
        return None
    try:
        parsed = json.loads(trimmed)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def _collect_scalar_candidates(
    value: Any,
    *,
    path: str = 'root',
    depth: int = 0,
    sink: list[dict[str, Any]] | None = None,
    seen: set[int] | None = None,
) -> list[dict[str, Any]]:
    sink = sink or []
    seen = seen or set()
    if value is None or depth > _MAX_DISCOVERY_DEPTH:
        return sink
    if isinstance(value, (str, int, float, bool, Decimal)):
        normalized_value = _normalize_json_scalar(value)
        sink.append({'path': path, 'value': normalized_value})
        if isinstance(normalized_value, str):
            nested = _maybe_parse_nested_json(normalized_value)
            if nested is not None:
                _collect_scalar_candidates(nested, path=f'{path}.__parsed__', depth=depth + 1, sink=sink, seen=seen)
        return sink
    if not isinstance(value, (dict, list)):
        return sink
    object_id = id(value)
    if object_id in seen:
        return sink
    seen.add(object_id)
    if isinstance(value, list):
        for index, entry in enumerate(value):
            _collect_scalar_candidates(entry, path=f'{path}[{index}]', depth=depth + 1, sink=sink, seen=seen)
        return sink
    for key, entry in value.items():
        _collect_scalar_candidates(entry, path=f'{path}.{key}', depth=depth + 1, sink=sink, seen=seen)
    return sink


def _is_image_like_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    trimmed = value.strip()
    return (
        trimmed.startswith('data:image/')
        or trimmed.startswith('iVBORw0KGgo')
        or trimmed.startswith('/9j/')
        or trimmed.startswith('PHN2Zy')
        or trimmed.startswith('<svg')
    )


def _to_image_data_uri(value: str) -> str | None:
    trimmed = value.strip()
    if trimmed.startswith('data:image/'):
        return trimmed
    if trimmed.startswith('iVBORw0KGgo'):
        return f'data:image/png;base64,{trimmed}'
    if trimmed.startswith('/9j/'):
        return f'data:image/jpeg;base64,{trimmed}'
    if trimmed.startswith('PHN2Zy'):
        return f'data:image/svg+xml;base64,{trimmed}'
    if trimmed.startswith('<svg'):
        return f'data:image/svg+xml;utf8,{trimmed}'
    return None


def _score_url_candidate(path: str) -> int:
    normalized = path.lower()
    score = 0
    if any(token in normalized for token in ('providedaction', 'redirect', 'action', 'url', 'link', 'deeplink')):
        score += 5
    if 'providerlinkurl' in normalized:
        score += 3
    if 'response.__parsed__' in normalized:
        score += 1
    return score


def _score_image_candidate(path: str) -> int:
    normalized = path.lower()
    score = 0
    if 'providerlinkurl' in normalized:
        score += 8
    if any(token in normalized for token in ('qr', 'image', 'png', 'jpg', 'jpeg', 'svg')):
        score += 5
    if 'response.__parsed__' in normalized:
        score += 2
    return score


def _score_qr_candidate(path: str) -> int:
    normalized = path.lower()
    score = 0
    if 'providedaction' in normalized:
        score += 8
    if any(token in normalized for token in ('qr', 'payload', 'content', 'code', 'providerlinkurl')):
        score += 5
    if 'response.__parsed__' in normalized:
        score += 2
    return score


def _resolve_external_action_url(candidates: list[dict[str, Any]], next_action_url: str | None) -> str | None:
    if next_action_url and str(next_action_url).strip().startswith('http'):
        return str(next_action_url).strip()
    prioritized = sorted(candidates, key=lambda item: _score_url_candidate(str(item.get('path') or '')), reverse=True)
    for candidate in prioritized:
        value = candidate.get('value')
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed.startswith('http'):
                return trimmed
    return None


def _resolve_qr_image_uri(candidates: list[dict[str, Any]]) -> str | None:
    prioritized = sorted(
        (candidate for candidate in candidates if _is_image_like_value(candidate.get('value'))),
        key=lambda item: _score_image_candidate(str(item.get('path') or '')),
        reverse=True,
    )
    for candidate in prioritized:
        value = candidate.get('value')
        if isinstance(value, str):
            uri = _to_image_data_uri(value)
            if uri:
                return uri
    return None


def _resolve_qr_value(candidates: list[dict[str, Any]], qr_image_uri: str | None) -> str | None:
    if qr_image_uri:
        return None
    prioritized = sorted(candidates, key=lambda item: _score_qr_candidate(str(item.get('path') or '')), reverse=True)
    for candidate in prioritized:
        value = candidate.get('value')
        if not isinstance(value, str):
            continue
        trimmed = value.strip()
        if not trimmed or trimmed.startswith('http') or _is_image_like_value(trimmed):
            continue
        if trimmed.startswith('{') or trimmed.startswith('[') or len(trimmed) > 3000:
            continue
        return trimmed
    return None


def _extract_labeled_rows(raw_address: str | None) -> list[dict[str, str]]:
    if not raw_address:
        return []
    rows: list[dict[str, str]] = []
    for index, line in enumerate(str(raw_address).splitlines()):
        trimmed = line.strip()
        if not trimmed or trimmed.lower() == 'undefined':
            continue
        match = trimmed.split(None, 1)
        if len(match) == 2 and _normalize_key(match[0]) in {'alias', 'cbu', 'cvu', 'clabe', 'cci', 'banco', 'email', 'pix', 'bank', 'reference', 'referencia'}:
            label = match[0].strip().rstrip(':')
            rows.append({'label': label, 'value': match[1].strip()})
            continue
        rows.append({'label': f'Dato {index + 1}', 'value': trimmed})
    return rows


def _extract_instruction_fields(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for candidate in candidates:
        path = str(candidate.get('path') or '')
        key = _normalize_key(path.rsplit('.', 1)[-1])
        value = candidate.get('value')
        if value in (None, ''):
            continue
        for field_name, aliases in _SNAPSHOT_FIELD_ALIASES.items():
            if field_name in fields:
                continue
            if key in aliases:
                fields[field_name] = _normalize_json_scalar(value)
    return fields


def build_koywe_instruction_snapshot(
    *,
    order_payload: dict[str, Any] | None,
    next_action_url: str | None,
) -> dict[str, Any]:
    payload = order_payload or {}
    candidates = _collect_scalar_candidates(payload)
    if next_action_url:
        candidates.insert(0, {'path': 'providedAction', 'value': next_action_url})

    provided_address = payload.get('providedAddress') if isinstance(payload.get('providedAddress'), str) else None
    provided_action = payload.get('providedAction') if isinstance(payload.get('providedAction'), str) else None
    if provided_action:
        candidates.insert(0, {'path': 'payload.providedAction', 'value': provided_action})

    qr_image_uri = _resolve_qr_image_uri(candidates)
    qr_value = _resolve_qr_value(candidates, qr_image_uri)
    external_action_url = _resolve_external_action_url(candidates, next_action_url)

    snapshot = {
        'provider_status': str(payload.get('status') or '').strip(),
        'provider_status_details': str(payload.get('statusDetails') or '').strip(),
        'order_type': str(payload.get('orderType') or '').strip(),
        'symbol_in': str(payload.get('symbolIn') or '').strip(),
        'symbol_out': str(payload.get('symbolOut') or '').strip(),
        'amount_in': _normalize_json_scalar(payload.get('amountIn')),
        'amount_out': _normalize_json_scalar(payload.get('amountOut')),
        'payment_method_id': str(payload.get('paymentMethodId') or '').strip(),
        'next_action_url': next_action_url or '',
        'external_action_url': external_action_url or '',
        'provided_action': provided_action or '',
        'provided_address': provided_address or '',
        'qr_image_uri': qr_image_uri or '',
        'qr_value': qr_value or '',
        'fields': _extract_instruction_fields(candidates),
        'address_rows': _extract_labeled_rows(provided_address),
        'captured_at': timezone.now().isoformat(),
    }
    return snapshot


def _merge_koywe_metadata(
    *,
    existing_metadata: dict[str, Any] | None,
    payment_method_code: str | None,
    payment_method_display: str | None,
    next_action_url: str | None,
    auth_email: str | None,
    order_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    metadata = dict(existing_metadata or {})
    metadata.update({
        'payment_method_code': payment_method_code or metadata.get('payment_method_code') or '',
        'payment_method_display': payment_method_display or metadata.get('payment_method_display') or '',
        'next_action_url': next_action_url or '',
        'auth_email': auth_email or metadata.get('auth_email') or '',
    })
    if order_payload:
        metadata['koywe_status'] = str(order_payload.get('status') or '').strip()
        metadata['payment_details'] = order_payload
        metadata['provider_payload_latest'] = order_payload
        metadata.setdefault('provider_payload_created', order_payload)
        snapshot = build_koywe_instruction_snapshot(
            order_payload=order_payload,
            next_action_url=next_action_url or metadata.get('next_action_url'),
        )
        metadata['instruction_snapshot_latest'] = snapshot
        metadata.setdefault('instruction_snapshot_created', snapshot)
    return metadata


def _extract_metadata(
    *,
    payment_method_code: str | None,
    payment_method_display: str | None,
    next_action_url: str | None,
    auth_email: str | None,
    order_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    return _merge_koywe_metadata(
        existing_metadata=None,
        payment_method_code=payment_method_code,
        payment_method_display=payment_method_display,
        next_action_url=next_action_url,
        auth_email=auth_email,
        order_payload=order_payload,
    )


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

    existing = RampTransaction.objects.filter(
        provider='koywe',
        provider_order_id=order_id,
    ).first()

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
        'crypto_currency': getattr(settings, 'KOYWE_CRYPTO_SYMBOL', 'USDC Polygon'),
        'crypto_amount_estimated': crypto_estimated,
        'crypto_amount_actual': None,
        'final_currency': 'CUSD' if normalized_direction == 'on_ramp' else getattr(settings, 'KOYWE_CRYPTO_SYMBOL', 'USDC Polygon'),
        'final_amount': final_amount,
        'status_detail': status_detail,
        'metadata': _merge_koywe_metadata(
            existing_metadata=(existing.metadata if existing else None),
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
        ramp_tx.final_currency = getattr(settings, 'KOYWE_CRYPTO_SYMBOL', 'USDC Polygon')
        ramp_tx.final_amount = amount_in or ramp_tx.final_amount

    ramp_tx.status = ramp_status
    ramp_tx.status_detail = normalized_detail if not status_details else f'{normalized_detail}: {status_details}'
    if ramp_status == 'COMPLETED':
        ramp_tx.completed_at = ramp_tx.completed_at or timezone.now()
    elif ramp_status in {'FAILED', 'AML_REVIEW', 'PROCESSING', 'PENDING'}:
        if ramp_status != 'FAILED':
            ramp_tx.completed_at = None

    existing_metadata = dict(ramp_tx.metadata or {})
    ramp_tx.metadata = _merge_koywe_metadata(
        existing_metadata=existing_metadata,
        payment_method_code=existing_metadata.get('payment_method_code'),
        payment_method_display=existing_metadata.get('payment_method_display'),
        next_action_url=next_action_url,
        auth_email=existing_metadata.get('auth_email'),
        order_payload=order_payload,
    )
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
