import hashlib
import hmac
import json
import logging
from datetime import date, datetime
from typing import Any

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from security.models import IdentityVerification

logger = logging.getLogger(__name__)
User = get_user_model()

DIDIT_TIMEOUT_SECONDS = 20

ISO2_TO_ISO3 = {
    'AR': 'ARG',
    'BO': 'BOL',
    'BR': 'BRA',
    'CL': 'CHL',
    'CO': 'COL',
    'CR': 'CRI',
    'DO': 'DOM',
    'EC': 'ECU',
    'GT': 'GTM',
    'HN': 'HND',
    'MX': 'MEX',
    'NI': 'NIC',
    'PA': 'PAN',
    'PE': 'PER',
    'PY': 'PRY',
    'SV': 'SLV',
    'UY': 'URY',
    'VE': 'VEN',
    'US': 'USA',
}

DOCUMENT_TYPE_MAP = {
    'passport': 'passport',
    'id': 'national_id',
    'identity_card': 'national_id',
    'national_id': 'national_id',
    'driving_license': 'drivers_license',
    'driver_license': 'drivers_license',
    'residence_permit': 'foreign_id',
    'residence_card': 'foreign_id',
    'foreigner_id': 'foreign_id',
    'foreign_id': 'foreign_id',
}


class DiditConfigurationError(RuntimeError):
    pass


class DiditAPIError(RuntimeError):
    pass


def _normalize_iso3(value: Any, default: str = 'UNK') -> str:
    if not value:
        return default
    country = str(value).strip().upper()
    if len(country) == 3:
        return country
    if len(country) == 2:
        return ISO2_TO_ISO3.get(country, default)
    return default


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        if 'T' in raw:
            return datetime.fromisoformat(raw.replace('Z', '+00:00')).date()
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, '', [], {}):
            return value
    return None


def _safe_json_loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _didit_headers() -> dict[str, str]:
    api_key = getattr(settings, 'DIDIT_API_KEY', '') or ''
    if not api_key:
        raise DiditConfigurationError('DIDIT_API_KEY is not configured')
    return {
        'x-api-key': api_key,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }


def _didit_url(path: str) -> str:
    base_url = (getattr(settings, 'DIDIT_API_URL', '') or 'https://verification.didit.me').rstrip('/')
    return f'{base_url}{path}'


def _didit_request(method: str, path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        response = requests.request(
            method,
            _didit_url(path),
            headers=_didit_headers(),
            json=payload,
            timeout=DIDIT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        logger.exception('Didit API request failed: %s %s', method, path)
        raise DiditAPIError(str(exc)) from exc
    except ValueError as exc:
        logger.exception('Didit API returned invalid JSON for %s %s', method, path)
        raise DiditAPIError('Didit API returned invalid JSON') from exc


def _workflow_id_for_account(account_type: str) -> str:
    business_workflow = getattr(settings, 'DIDIT_BUSINESS_WORKFLOW_ID', '') or ''
    default_workflow = getattr(settings, 'DIDIT_WORKFLOW_ID', '') or ''
    workflow_id = business_workflow if account_type == 'business' and business_workflow else default_workflow
    if not workflow_id:
        raise DiditConfigurationError('Didit workflow is not configured')
    return workflow_id


def build_didit_callback_url(request=None) -> str | None:
    configured = (getattr(settings, 'DIDIT_WEBHOOK_URL', '') or '').strip()
    if configured:
        return configured
    if request is not None:
        return request.build_absolute_uri('/api/didit/webhook/')
    return None


def create_didit_session(*, user, account_type: str = 'personal', business_id: str | None = None, callback_url: str | None = None) -> dict[str, Any]:
    vendor_data = {
        'user_id': user.id,
        'account_type': account_type,
    }
    if business_id:
        vendor_data['business_id'] = str(business_id)

    payload: dict[str, Any] = {
        'workflow_id': _workflow_id_for_account(account_type),
        'vendor_data': json.dumps(vendor_data, separators=(',', ':')),
    }
    if callback_url:
        payload['callback'] = callback_url

    response = _didit_request('POST', '/v3/session/', payload=payload)
    session_id = _first_non_empty(response.get('session_id'), response.get('id'))
    session_token = response.get('session_token')
    if not session_id or not session_token:
        raise DiditAPIError('Didit session response did not include session_id/session_token')

    return {
        'session_id': str(session_id),
        'session_token': str(session_token),
        'status': str(response.get('status') or 'pending'),
        'vendor_data': vendor_data,
        'raw': response,
    }


def _find_existing_verification(*, user, session_id: str) -> IdentityVerification | None:
    return (
        IdentityVerification.objects
        .filter(user=user, risk_factors__didit__session_id=session_id)
        .order_by('-created_at')
        .first()
    )


def _placeholder_defaults(*, user, session_id: str, account_type: str, business_id: str | None) -> dict[str, Any]:
    risk_factors: dict[str, Any] = {
        'provider': 'didit',
        'didit': {
            'session_id': session_id,
            'status': 'pending',
        },
    }
    if account_type == 'business':
        risk_factors['account_type'] = 'business'
    if business_id:
        risk_factors['business_id'] = str(business_id)

    return {
        'verified_first_name': user.first_name or 'Pending',
        'verified_last_name': user.last_name or 'Verification',
        'verified_date_of_birth': date(1900, 1, 1),
        'verified_nationality': 'UNK',
        'verified_address': 'Pending Didit verification',
        'verified_city': 'Unknown City',
        'verified_state': 'Unknown State',
        'verified_country': 'UNK',
        'document_type': 'national_id',
        'document_number': f'didit:{session_id}',
        'document_issuing_country': 'UNK',
        'status': 'pending',
        'risk_factors': risk_factors,
    }


def ensure_pending_didit_verification(*, user, session_id: str, account_type: str = 'personal', business_id: str | None = None) -> IdentityVerification:
    existing = _find_existing_verification(user=user, session_id=session_id)
    if existing:
        risk_factors = dict(existing.risk_factors or {})
        didit_risk = dict(risk_factors.get('didit') or {})
        didit_risk.update({'session_id': session_id, 'status': 'pending'})
        risk_factors['provider'] = 'didit'
        risk_factors['didit'] = didit_risk
        if account_type == 'business':
            risk_factors['account_type'] = 'business'
        if business_id:
            risk_factors['business_id'] = str(business_id)
        existing.risk_factors = risk_factors
        if existing.status not in ('verified', 'rejected'):
            existing.status = 'pending'
        existing.save(update_fields=['risk_factors', 'status', 'updated_at'])
        return existing

    return IdentityVerification.objects.create(
        user=user,
        **_placeholder_defaults(
            user=user,
            session_id=session_id,
            account_type=account_type,
            business_id=business_id,
        ),
    )


def _extract_verification_payload(response_payload: dict[str, Any]) -> dict[str, Any]:
    id_verification = {}
    id_verifications = response_payload.get('id_verifications')
    if isinstance(id_verifications, list) and id_verifications:
        id_verification = id_verifications[0] or {}

    parsed_address = id_verification.get('parsed_address') or response_payload.get('parsed_address') or {}
    issuing_country = _first_non_empty(
        id_verification.get('issuing_state'),
        response_payload.get('issuing_state'),
        response_payload.get('issuing_country'),
    )
    document_type = _first_non_empty(
        id_verification.get('document_type'),
        response_payload.get('document_type'),
        response_payload.get('document_type_name'),
    )
    line_parts = [
        _first_non_empty(parsed_address.get('street'), parsed_address.get('address_line1')),
        parsed_address.get('street_number'),
        parsed_address.get('neighborhood'),
    ]
    address_line = ' '.join(str(part).strip() for part in line_parts if part)

    return {
        'verified_first_name': _first_non_empty(
            response_payload.get('first_name'),
            id_verification.get('first_name'),
            'Pending',
        ),
        'verified_last_name': _first_non_empty(
            response_payload.get('last_name'),
            id_verification.get('last_name'),
            'Verification',
        ),
        'verified_date_of_birth': _parse_date(
            _first_non_empty(response_payload.get('date_of_birth'), id_verification.get('date_of_birth'))
        ) or date(1900, 1, 1),
        'verified_nationality': _normalize_iso3(
            _first_non_empty(id_verification.get('nationality'), response_payload.get('nationality'))
        ),
        'verified_address': address_line or _first_non_empty(response_payload.get('full_address'), 'Verified by Didit'),
        'verified_city': _first_non_empty(parsed_address.get('city'), response_payload.get('city'), 'Unknown City'),
        'verified_state': _first_non_empty(parsed_address.get('state'), response_payload.get('state'), 'Unknown State'),
        'verified_country': _normalize_iso3(
            _first_non_empty(parsed_address.get('country'), response_payload.get('country'), issuing_country)
        ),
        'verified_postal_code': _first_non_empty(parsed_address.get('postal_code'), response_payload.get('postal_code')),
        'document_type': DOCUMENT_TYPE_MAP.get(str(document_type or '').strip().lower(), 'national_id'),
        'document_number': _first_non_empty(
            id_verification.get('document_number'),
            response_payload.get('document_number'),
            response_payload.get('personal_number'),
        ),
        'document_issuing_country': _normalize_iso3(issuing_country),
        'document_expiry_date': _parse_date(
            _first_non_empty(id_verification.get('expiration_date'), response_payload.get('expiration_date'))
        ),
    }


def _map_didit_status(response_payload: dict[str, Any]) -> str:
    raw_status = str(
        _first_non_empty(
            response_payload.get('status'),
            response_payload.get('decision'),
            response_payload.get('overall_status'),
        ) or 'pending'
    ).strip().lower()

    if raw_status in {'approved', 'verified', 'completed', 'success'}:
        return 'verified'
    if raw_status in {'declined', 'rejected', 'failed', 'denied'}:
        return 'rejected'
    return 'pending'


def _resolve_user_from_payload(response_payload: dict[str, Any], expected_user=None):
    if expected_user is not None:
        return expected_user

    vendor_data = _safe_json_loads(response_payload.get('vendor_data'))
    user_id = vendor_data.get('user_id')
    if not user_id:
        return None
    try:
        return User.objects.get(id=user_id)
    except User.DoesNotExist:
        return None


def sync_didit_session(*, session_id: str, expected_user=None) -> tuple[IdentityVerification, dict[str, Any]]:
    response_payload = _didit_request('GET', f'/v3/session/{session_id}/decision/')
    user = _resolve_user_from_payload(response_payload, expected_user=expected_user)
    if user is None:
        raise DiditAPIError('Could not match Didit session to a Confio user')

    vendor_data = _safe_json_loads(response_payload.get('vendor_data'))
    account_type = str(vendor_data.get('account_type') or 'personal')
    business_id = vendor_data.get('business_id')

    verification = _find_existing_verification(user=user, session_id=session_id)
    if verification is None:
        verification = ensure_pending_didit_verification(
            user=user,
            session_id=session_id,
            account_type=account_type,
            business_id=business_id,
        )

    extracted = _extract_verification_payload(response_payload)
    status = _map_didit_status(response_payload)
    risk_factors = dict(verification.risk_factors or {})
    risk_factors['provider'] = 'didit'
    risk_factors['didit'] = {
        'session_id': session_id,
        'status': response_payload.get('status'),
        'raw_status': response_payload.get('status'),
        'session': response_payload,
    }
    if account_type == 'business':
        risk_factors['account_type'] = 'business'
    if business_id:
        risk_factors['business_id'] = str(business_id)

    verification.verified_first_name = extracted['verified_first_name']
    verification.verified_last_name = extracted['verified_last_name']
    verification.verified_date_of_birth = extracted['verified_date_of_birth']
    verification.verified_nationality = extracted['verified_nationality']
    verification.verified_address = extracted['verified_address']
    verification.verified_city = extracted['verified_city']
    verification.verified_state = extracted['verified_state']
    verification.verified_country = extracted['verified_country']
    verification.verified_postal_code = extracted['verified_postal_code']
    verification.document_type = extracted['document_type']
    verification.document_number = extracted['document_number'] or verification.document_number
    verification.document_issuing_country = extracted['document_issuing_country']
    verification.document_expiry_date = extracted['document_expiry_date']
    verification.status = status
    verification.risk_factors = risk_factors
    if status == 'verified' and verification.verified_at is None:
        verification.verified_at = timezone.now()
    if status != 'rejected':
        verification.rejected_reason = None
    verification.save()

    return verification, response_payload


def verify_didit_webhook_signature(raw_body: bytes, signature_header: str | None) -> bool:
    secret = (getattr(settings, 'DIDIT_WEBHOOK_SECRET', '') or '').strip()
    if not secret:
        return True
    if not signature_header:
        return False

    provided = signature_header.strip()
    if ',' in provided:
        last_piece = provided.split(',')[-1]
        provided = last_piece.split('=')[-1].strip()
    elif '=' in provided:
        provided = provided.split('=')[-1].strip()

    expected = hmac.new(secret.encode('utf-8'), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)
