import hashlib
import hmac
import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from notifications.models import NotificationType as NotificationTypeChoices
from notifications.utils import create_notification
from security.models import IdentityVerification, normalize_brazilian_cpf
from users.models import Business

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
    'identity card': 'national_id',
    'national_id': 'national_id',
    'driving_license': 'drivers_license',
    'driving license': 'drivers_license',
    'driver_license': 'drivers_license',
    'driver license': 'drivers_license',
    'residence_permit': 'foreign_id',
    'residence permit': 'foreign_id',
    'residence_card': 'foreign_id',
    'residence card': 'foreign_id',
    'foreigner_id': 'foreign_id',
    'foreigner id': 'foreign_id',
    'foreign_id': 'foreign_id',
    'foreign id': 'foreign_id',
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


def _parsed_address_component(parsed_address: dict[str, Any], *component_types: str) -> str:
    address_components = (
        (parsed_address.get('raw_results') or {}).get('address_components') or []
    )
    wanted_types = set(component_types)
    for component in address_components:
        if not isinstance(component, dict):
            continue
        if wanted_types.intersection(component.get('types') or []):
            return str(component.get('long_name') or component.get('short_name') or '').strip()
    return ''


def _document_postal_code(value: Any) -> str:
    matches = re.findall(r'(?<!\d)(\d{5})(?!\d)', str(value or ''))
    return matches[-1] if matches else ''


def _brazilian_cpfs_from_didit_payload(payload: dict[str, Any]) -> set[str]:
    """Extract CPF candidates only from Didit's CPF/tax-specific fields."""
    candidates: list[Any] = [
        payload.get('tax_number'),
        payload.get('taxNumber'),
        payload.get('cpf'),
        payload.get('personal_number'),
    ]
    id_verifications = payload.get('id_verifications') or []
    if not isinstance(id_verifications, list):
        id_verifications = []
    for item in id_verifications:
        if not isinstance(item, dict):
            continue
        extra_fields = item.get('extra_fields') or {}
        if not isinstance(extra_fields, dict):
            extra_fields = {}
        candidates.extend((
            item.get('tax_number'),
            item.get('taxNumber'),
            item.get('cpf'),
            item.get('personal_number'),
            extra_fields.get('tax_number'),
            extra_fields.get('taxNumber'),
            extra_fields.get('cpf'),
        ))
    return {cpf for value in candidates if (cpf := normalize_brazilian_cpf(value))}


def _authoritative_brazilian_cpf_from_database_validation(
    payload: dict[str, Any],
) -> tuple[bool, str | None]:
    """Return whether bra_cpf ran and its single fully matched CPF, if any."""
    raw_checks = payload.get('database_validations') or payload.get('database_validation') or []
    if isinstance(raw_checks, dict):
        raw_checks = [raw_checks]
    if not isinstance(raw_checks, list):
        raw_checks = []

    found_bra_cpf = False
    matched_cpfs: set[str] = set()
    for check in raw_checks:
        if not isinstance(check, dict):
            continue
        validations = check.get('validations') or []
        if not isinstance(validations, list):
            continue
        screened_data = check.get('screened_data') or {}
        if not isinstance(screened_data, dict):
            screened_data = {}
        for validation in validations:
            if not isinstance(validation, dict):
                continue
            if str(validation.get('service_id') or '').strip().lower() != 'bra_cpf':
                continue
            found_bra_cpf = True
            field_matches = validation.get('validation') or {}
            if not isinstance(field_matches, dict):
                field_matches = {}
            if not (
                str(check.get('status') or '').strip().lower() == 'approved'
                and str(check.get('match_type') or '').strip().lower() == 'full_match'
                and str(validation.get('outcome_code') or '').strip().upper() == 'MATCH'
                and str(field_matches.get('identification_number') or '').strip().lower() == 'full_match'
                and str(field_matches.get('date_of_birth') or '').strip().lower() == 'full_match'
            ):
                continue

            source_data = validation.get('source_data') or {}
            if not isinstance(source_data, dict):
                source_data = {}
            candidates = {
                cpf
                for value in (
                    screened_data.get('tax_number'),
                    source_data.get('identification_number'),
                )
                if (cpf := normalize_brazilian_cpf(value))
            }
            if len(candidates) == 1:
                matched_cpfs.update(candidates)

    return found_bra_cpf, next(iter(matched_cpfs)) if len(matched_cpfs) == 1 else None


def _single_brazilian_cpf_from_didit_payload(payload: dict[str, Any]) -> str | None:
    candidates = _brazilian_cpfs_from_didit_payload(payload)
    return next(iter(candidates)) if len(candidates) == 1 else None


def _enforce_brazilian_cpf_database_validation(
    *,
    status: str,
    document_issuing_country: str,
    extracted: dict[str, Any],
    risk_factors: dict[str, Any],
) -> str:
    """Route inconsistent bra_cpf approvals to review instead of trusting OCR."""
    if not (
        status == 'verified'
        and document_issuing_country == 'BRA'
        and extracted.get('brazilian_cpf_database_validation_present')
        and not extracted.get('brazilian_cpf_database_validation_valid')
    ):
        return status
    risk_factors['requires_review'] = True
    risk_factors['brazilian_cpf_validation'] = {
        'source': 'didit_bra_cpf',
        'result': 'not_full_match',
        'review_required_at': timezone.now().isoformat(),
    }
    return 'pending'


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


def _extract_signature_value(signature_header: str | None) -> str:
    if not signature_header:
        return ''
    provided = signature_header.strip()
    if ',' in provided:
        last_piece = provided.split(',')[-1]
        provided = last_piece.split('=')[-1].strip()
    elif '=' in provided:
        provided = provided.split('=')[-1].strip()
    return provided


def _normalize_didit_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_didit_payload(value[key]) for key in sorted(value.keys())}
    if isinstance(value, list):
        return [_normalize_didit_payload(item) for item in value]
    if isinstance(value, float):
        decimal_value = Decimal(str(value))
        normalized = decimal_value.normalize()
        if normalized == normalized.to_integral():
            return int(normalized)
        return float(normalized)
    return value


_DIDIT_TRANSIENT_MEDIA_KEYS = {
    'portrait_image', 'front_image', 'back_image', 'full_front_image',
    'full_back_image', 'front_video', 'back_video', 'reference_image',
    'video_url', 'file_url', 'session_url', 'kyc_session_url',
    'url', 'document_file', 'files', 'extra_files',
    'front_image_camera_front', 'back_image_camera_front',
}


def _without_transient_didit_media(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_transient_didit_media(item)
            for key, item in value.items()
            if key not in _DIDIT_TRANSIENT_MEDIA_KEYS
            and not key.endswith('_image_url')
        }
    if isinstance(value, list):
        return [_without_transient_didit_media(item) for item in value]
    return value


def _canonicalize_didit_payload(raw_body: bytes) -> str | None:
    try:
        payload = json.loads(raw_body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    normalized = _normalize_didit_payload(payload)
    return json.dumps(normalized, separators=(',', ':'), ensure_ascii=False)


def _build_simple_signature_payload(raw_body: bytes) -> str | None:
    try:
        payload = json.loads(raw_body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    session_id = payload.get('session_id')
    status = payload.get('status')
    webhook_type = payload.get('webhook_type')
    timestamp = payload.get('timestamp')
    if None in (timestamp, session_id, status, webhook_type):
        return None
    return f'{timestamp}:{session_id}:{status}:{webhook_type}'


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


def validate_brazilian_cpf_with_didit(
    *,
    cpf: str,
    date_of_birth: date,
    vendor_data: str,
) -> dict[str, Any]:
    """Run Didit's standalone Receita Federal CPF lookup."""
    normalized_cpf = normalize_brazilian_cpf(cpf)
    if not normalized_cpf:
        raise DiditAPIError('A valid Brazilian CPF is required')
    if not isinstance(date_of_birth, date):
        raise DiditAPIError('A valid date of birth is required')

    headers = _didit_headers()
    headers.pop('Content-Type', None)
    fields = {
        'issuing_state': (None, 'BRA'),
        'services': (None, 'bra_cpf'),
        'tax_number': (None, normalized_cpf),
        'date_of_birth': (None, date_of_birth.isoformat()),
        'vendor_data': (None, str(vendor_data)),
    }
    try:
        response = requests.request(
            'POST',
            _didit_url('/v3/database-validation/'),
            headers=headers,
            files=fields,
            timeout=DIDIT_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError('response is not an object')
        return payload
    except requests.RequestException as exc:
        logger.exception('Didit API request failed: POST /v3/database-validation/')
        raise DiditAPIError(str(exc)) from exc
    except ValueError as exc:
        logger.exception('Didit API returned invalid CPF validation JSON')
        raise DiditAPIError('Didit API returned invalid JSON') from exc


_BRA_CPF_RETRYABLE_OUTCOMES = {'REGISTRY_UNAVAILABLE', 'REGISTRY_ERROR'}


def classify_brazilian_cpf_database_validation(
    payload: dict[str, Any],
    *,
    expected_cpf: str,
) -> tuple[str, dict[str, Any]]:
    """Classify a standalone bra_cpf result and return PII-minimized evidence."""
    normalized_expected = normalize_brazilian_cpf(expected_cpf)
    result_payload = payload.get('database_validation') or payload
    if not isinstance(result_payload, dict):
        result_payload = {}
    validations = result_payload.get('validations') or []
    if not isinstance(validations, list):
        validations = []
    service_results = [
        item for item in validations
        if isinstance(item, dict)
        and str(item.get('service_id') or '').strip().lower() == 'bra_cpf'
    ]
    validation = service_results[0] if len(service_results) == 1 else {}
    field_matches = validation.get('validation') or {}
    if not isinstance(field_matches, dict):
        field_matches = {}
    outcome_code = str(validation.get('outcome_code') or '').strip().upper()
    source_data = validation.get('source_data') or {}
    if not isinstance(source_data, dict):
        source_data = {}
    source_cpf = normalize_brazilian_cpf(source_data.get('identification_number'))

    evidence = {
        'service_id': 'bra_cpf',
        'cpf_sha256': hashlib.sha256((normalized_expected or '').encode('ascii')).hexdigest(),
        'request_id': str(payload.get('request_id') or result_payload.get('request_id') or ''),
        'provider_status': str(result_payload.get('status') or ''),
        'match_type': str(result_payload.get('match_type') or ''),
        'outcome_code': outcome_code,
        'field_matches': {
            key: str(field_matches.get(key) or '')
            for key in ('identification_number', 'date_of_birth')
        },
    }
    is_full_match = (
        bool(normalized_expected)
        and len(service_results) == 1
        and str(result_payload.get('status') or '').strip().lower() == 'approved'
        and str(result_payload.get('match_type') or '').strip().lower() == 'full_match'
        and outcome_code == 'MATCH'
        and str(field_matches.get('identification_number') or '').strip().lower() == 'full_match'
        and str(field_matches.get('date_of_birth') or '').strip().lower() == 'full_match'
        and source_cpf == normalized_expected
    )
    if is_full_match:
        return 'full_match', evidence
    if len(service_results) != 1 or not outcome_code or outcome_code in _BRA_CPF_RETRYABLE_OUTCOMES:
        return 'retryable', evidence
    return 'review_required', evidence


def is_authoritative_brazilian_cpf_backfill(evidence: Any, *, cpf: str) -> bool:
    """Verify that stored backfill evidence is a full match for the current CPF."""
    normalized_cpf = normalize_brazilian_cpf(cpf)
    if not normalized_cpf or not isinstance(evidence, dict):
        return False
    field_matches = evidence.get('field_matches') or {}
    return (
        evidence.get('result') == 'full_match'
        and evidence.get('service_id') == 'bra_cpf'
        and str(evidence.get('provider_status') or '').strip().lower() == 'approved'
        and str(evidence.get('match_type') or '').strip().lower() == 'full_match'
        and str(evidence.get('outcome_code') or '').strip().upper() == 'MATCH'
        and str(field_matches.get('identification_number') or '').strip().lower() == 'full_match'
        and str(field_matches.get('date_of_birth') or '').strip().lower() == 'full_match'
        and evidence.get('cpf_sha256') == hashlib.sha256(normalized_cpf.encode('ascii')).hexdigest()
    )


def _workflow_id_for_account(account_type: str, phone_country: str | None = None) -> str:
    if account_type == 'business':
        business_workflow = (getattr(settings, 'DIDIT_BUSINESS_WORKFLOW_ID', '') or '').strip()
        if not business_workflow:
            raise DiditConfigurationError('La verificación de tu negocio no está disponible por ahora. Contacta a soporte.')
        return business_workflow

    workflow_map = getattr(settings, 'DIDIT_WORKFLOW_IDS_BY_PHONE_COUNTRY', {}) or {}
    normalized_phone_country = str(phone_country or '').strip().upper()
    workflow_id = str(workflow_map.get(normalized_phone_country, '') or '')
    if not workflow_id:
        if normalized_phone_country:
            raise DiditConfigurationError(
                'La verificación de identidad no está disponible por ahora para tu país.'
            )
        raise DiditConfigurationError('No pudimos identificar tu país para iniciar la verificación.')
    return workflow_id


def build_didit_callback_url(request=None) -> str | None:
    configured = (getattr(settings, 'DIDIT_WEBHOOK_URL', '') or '').strip()
    if configured:
        return configured
    if request is not None:
        return request.build_absolute_uri('/api/didit/webhook/')
    return None


ADDITIONAL_DOCUMENT_TYPES = frozenset({'P', 'ID', 'DL'})
_DOCUMENT_TYPE_CODES = {'passport': 'P', 'national_id': 'ID', 'drivers_license': 'DL'}


def normalize_document_request(id_country: Any = None, document_types: Any = None) -> dict[str, Any]:
    """Validate what a rail asks for: an ISO3 issuing country (or any) and Didit type codes."""
    from security.geo import to_iso3
    import pycountry

    raw = str(id_country or '').strip().upper()
    country = ''
    if raw:
        country = to_iso3(raw) if len(raw) == 2 else (raw if pycountry.countries.get(alpha_3=raw) else '')
        if not country:
            raise DiditConfigurationError('País del documento no válido.')
    types = sorted({str(value).strip().upper() for value in (document_types or []) if str(value).strip()})
    if any(value not in ADDITIONAL_DOCUMENT_TYPES for value in types):
        raise DiditConfigurationError('Tipo de documento no válido.')
    return {'id_country': country, 'document_types': types}


def _personal_vendor_data(user) -> dict[str, Any]:
    # Byte-identical to the KYC session's vendor_data: Didit groups sessions by
    # it, which is how Face Match finds the face the user already verified.
    return {'user_id': user.id, 'account_type': 'personal'}


def _validated_didit_session_url(value: Any) -> str:
    url = str(value or '').strip()
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == 'https' and parsed.hostname == 'verify.didit.me'
                 and not parsed.username and not parsed.password and parsed.port in (None, 443)
                 and re.fullmatch(r'/(?:[a-z]{2}/)?session/[A-Za-z0-9_-]+/?', parsed.path))
    except ValueError:
        valid = False
    if not valid:
        raise DiditAPIError('Didit no devolvió un enlace de verificación seguro.')
    return url


def _start_session(payload: dict[str, Any]) -> dict[str, Any]:
    response = _didit_request('POST', '/v3/session/', payload=payload)
    session_id = _first_non_empty(response.get('session_id'), response.get('id'))
    session_token = response.get('session_token')
    if not session_id or not session_token:
        raise DiditAPIError('Didit session response did not include session_id/session_token')
    return {
        'session_id': str(session_id),
        'session_token': str(session_token),
        'session_url': response.get('url'),
        'status': str(response.get('status') or 'pending'),
        'raw': response,
    }


def create_didit_session(*, user, account_type: str = 'personal', business_id: str | None = None,
                         callback_url: str | None = None,
                         document_request: dict[str, Any] | None = None) -> dict[str, Any]:
    account_type = str(account_type or '').strip().lower()
    if account_type not in {'personal', 'business'}:
        raise DiditConfigurationError('Unsupported Didit account context')
    if account_type == 'business' and not business_id:
        raise DiditConfigurationError('Business verification requires a business ID')
    if account_type == 'personal':
        business_id = None
    phone_country = str(getattr(user, 'phone_country', '') or '').strip().upper()
    vendor_data = {
        'user_id': user.id,
        'account_type': account_type,
    }
    if business_id:
        vendor_data['business_id'] = str(business_id)

    if document_request is not None:
        # A second document of the same person, for a rail its primary
        # document does not satisfy. One workflow for every country: the
        # session carries the country/types and the workflow DECLINES a
        # mismatch. Never replaces the primary (see PrimaryIdentityManager).
        if account_type != 'personal':
            raise DiditConfigurationError('Solo una cuenta personal puede agregar otro documento.')
        workflow_id = getattr(settings, 'DIDIT_ADDITIONAL_DOCUMENT_WORKFLOW_ID', '') or ''
        if not workflow_id:
            raise DiditConfigurationError('La verificación de otro documento no está disponible por ahora.')
        payload: dict[str, Any] = {
            'workflow_id': workflow_id,
            'vendor_data': json.dumps(vendor_data, separators=(',', ':')),
            'metadata': {'purpose': 'additional_document'},
        }
        expected = {}
        if document_request.get('id_country'):
            expected['id_country'] = document_request['id_country']
        if document_request.get('document_types'):
            expected['expected_document_types'] = list(document_request['document_types'])
        if expected:
            payload['expected_details'] = expected
    else:
        payload = {
            'workflow_id': _workflow_id_for_account(account_type, phone_country=phone_country),
            'vendor_data': json.dumps(vendor_data, separators=(',', ':')),
        }
    if callback_url:
        payload['callback'] = callback_url

    if account_type == 'business':
        # Resume this company's unfinished KYB, including requested corrections.
        # Fetch the fresh hosted link; bearer URLs are never stored in audit JSON.
        pending = IdentityVerification.objects.filter(
            user=user, status='pending', risk_factors__provider='didit',
            risk_factors__account_type='business', risk_factors__business_id=str(business_id),
        ).order_by('-created_at').first()
        previous_id = ((pending.risk_factors or {}).get('didit') or {}).get('session_id') if pending else None
        if previous_id:
            decision = _didit_request('GET', f'/v3/session/{previous_id}/decision/')
            # Old releases could bind a personal workflow to a business. Verify
            # ownership before skipping that legacy session; never hide an API
            # failure or a session belonging to another user/business.
            _resolve_user_from_payload(decision, expected_user=user)
            previous_binding = _safe_json_loads(decision.get('vendor_data'))
            if (previous_binding.get('account_type') != 'business'
                    or str(previous_binding.get('business_id') or '') != str(business_id)):
                raise DiditAPIError('Didit KYB session does not match the active business')
            if (decision.get('session_kind') == 'business'
                    and decision.get('workflow_id') == payload['workflow_id']
                    and _map_didit_status(decision) == 'pending'
                    and str(decision.get('status') or '').lower() not in {'expired', 'abandoned'}):
                return {'session_id': previous_id, 'session_token': None,
                        'session_url': _validated_didit_session_url(decision.get('session_url')),
                        'status': decision.get('status'), 'vendor_data': vendor_data}
    session = _start_session(payload)
    if account_type == 'business':
        session['session_url'] = _validated_didit_session_url(session.get('session_url'))
        ensure_pending_didit_verification(user=user, session_id=session['session_id'],
                                          account_type='business', business_id=business_id)
    if document_request is not None:
        # Record the role now: the decision webhook must never mistake this
        # document for the primary one, whatever Didit echoes back.
        ensure_pending_didit_verification(
            user=user, session_id=session['session_id'], account_type='personal',
            document_request=document_request,
        )
    return {**session, 'vendor_data': vendor_data}


def create_didit_workflow_session(*, user, workflow_id: str, expected_details: dict[str, Any] | None = None,
                                  metadata: dict[str, Any] | None = None, callback_url: str | None = None,
                                  language: str | None = None,
                                  session_reference: str | None = None) -> dict[str, Any]:
    """A personal session on an explicit workflow, optionally bound to a request."""
    if not workflow_id:
        raise DiditConfigurationError('Didit workflow is not configured')
    payload: dict[str, Any] = {
        'workflow_id': workflow_id,
        'vendor_data': json.dumps(_personal_vendor_data(user), separators=(',', ':')),
    }
    if session_reference:
        vendor = _personal_vendor_data(user)
        vendor['edd_request_id'] = session_reference
        payload['vendor_data'] = json.dumps(vendor, separators=(',', ':'))
    if expected_details:
        payload['expected_details'] = expected_details
    if metadata:
        payload['metadata'] = metadata
    if callback_url:
        payload['callback'] = callback_url
    if language:
        payload['language'] = language
    return _start_session(payload)


def _find_existing_verification(*, user, session_id: str) -> IdentityVerification | None:
    # Every document: an additional-document session must find its own row.
    return (
        IdentityVerification.all_documents
        .filter(user=user, risk_factors__didit__session_id=session_id)
        .order_by('-created_at')
        .first()
    )


def _placeholder_defaults(*, user, session_id: str, account_type: str, business_id: str | None,
                          document_request: dict[str, Any] | None = None) -> dict[str, Any]:
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
    if document_request:
        # What the rail asked for; checked again on the decision.
        risk_factors['document_request'] = dict(document_request)

    return {
        'verified_first_name': user.first_name or 'Pending',
        'verified_last_name': user.last_name or 'Verification',
        'verified_date_of_birth': date(1900, 1, 1),
        'verified_nationality': 'UNK',
        'verified_address': '',
        'verified_address_neighborhood': '',
        'verified_city': '',
        'verified_state': '',
        'verified_country': '',
        'document_type': 'national_id',
        'document_number': f'didit:{session_id}',
        'document_issuing_country': 'UNK',
        'status': 'pending',
        'risk_factors': risk_factors,
        'is_additional_document': bool(document_request),
    }


def ensure_pending_didit_verification(*, user, session_id: str, account_type: str = 'personal', business_id: str | None = None,
                                      document_request: dict[str, Any] | None = None,
                                      request_is_default: bool = False) -> IdentityVerification:
    from django.db import transaction
    with transaction.atomic():
        # One per-user lock (the one the sync holds) around the lookup AND the
        # creation: a registration and a webhook can never both create a row for
        # one session, and a decision committed meanwhile is never reverted.
        type(user).objects.select_for_update().filter(pk=user.pk).first()
        existing = _find_existing_verification(user=user, session_id=session_id)
        if existing is None:
            return IdentityVerification.objects.create(
                user=user,
                **_placeholder_defaults(
                    user=user,
                    session_id=session_id,
                    account_type=account_type,
                    business_id=business_id,
                    document_request=document_request,
                ),
            )
        existing = IdentityVerification.all_documents.select_for_update().get(pk=existing.pk)
        completed = existing.status in ('verified', 'rejected')
        risk_factors = dict(existing.risk_factors or {})
        if not completed:
            didit_risk = dict(risk_factors.get('didit') or {})
            didit_risk.update({'session_id': session_id, 'status': 'pending'})
            risk_factors['provider'] = 'didit'
            risk_factors['didit'] = didit_risk
        if account_type == 'business':
            risk_factors['account_type'] = 'business'
        if business_id:
            risk_factors['business_id'] = str(business_id)
        # A webhook's default never replaces a request already recorded; the
        # rail's own request (registration) always does.
        if document_request and not (request_is_default and risk_factors.get('document_request')):
            # The rail's request is authoritative (a webhook that came first only
            # knew the default): always record it. A not-yet-decided row becomes
            # additional; a verified extra document must still meet it.
            risk_factors['document_request'] = dict(document_request)
            if not existing.is_additional_document and not completed:
                existing.is_additional_document = True
            if existing.status == 'verified' and existing.is_additional_document:
                unmet = _unmet_request(existing.document_issuing_country, existing.document_type, document_request)
                if unmet:
                    existing.status, existing.rejected_reason = 'rejected', unmet
        existing.risk_factors = risk_factors
        if not completed:
            existing.status = 'pending'
        existing.save(update_fields=['risk_factors', 'status', 'is_additional_document', 'rejected_reason',
                                     'updated_at'])
        return existing


def _extract_verification_payload(response_payload: dict[str, Any]) -> dict[str, Any]:
    if response_payload.get('session_kind') == 'business':
        registry_checks = response_payload.get('registry_checks') or []
        # Use the canonical first registry result consistently with provider
        # handoff; never select an older approved company from later checks.
        registry = registry_checks[0] if registry_checks and isinstance(registry_checks[0], dict) else {}
        company = registry.get('company') or {}
        addresses = company.get('addresses') or []
        address = addresses[0] if addresses and isinstance(addresses[0], dict) else {}
        country = _normalize_iso3(
            _first_non_empty(address.get('country_code'), company.get('country_code'))
        )
        company_name = str(company.get('company_name') or 'Verified Business').strip()
        return {
            'verified_first_name': company_name[:100],
            'verified_last_name': 'Business',
            'verified_date_of_birth': _parse_date(company.get('incorporation_date')) or date(1900, 1, 1),
            'verified_nationality': country,
            'verified_address': _first_non_empty(
                address.get('address'), address.get('line_1'), company.get('registered_address'),
                'Verified by Didit',
            ),
            'verified_address_neighborhood': '',
            'verified_city': address.get('city') or 'Unknown City',
            'verified_state': address.get('state') or address.get('region') or 'Unknown State',
            'verified_country': country,
            'verified_postal_code': address.get('postal_code') or '',
            'document_type': 'national_id',
            'document_number': _first_non_empty(
                company.get('tax_number'), company.get('registration_number')
            ),
            'document_issuing_country': country,
            'document_expiry_date': None,
            'brazilian_cpf_database_validation_present': False,
            'brazilian_cpf_database_validation_valid': False,
        }
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
    issuing_country_iso3 = _normalize_iso3(issuing_country)
    document_type = _first_non_empty(
        id_verification.get('document_type'),
        response_payload.get('document_type'),
        response_payload.get('document_type_name'),
    )
    raw_document_address = _first_non_empty(
        id_verification.get('address'),
        id_verification.get('formatted_address'),
    )
    street = _first_non_empty(
        parsed_address.get('street'),
        parsed_address.get('street_1'),
        parsed_address.get('address_line1'),
        _parsed_address_component(parsed_address, 'route'),
    )
    street_number = _first_non_empty(
        parsed_address.get('street_number'),
        parsed_address.get('house_number'),
    )
    if not street_number and re.search(r'\bS/?N\b', str(raw_document_address or ''), flags=re.IGNORECASE):
        street_number = 'S/N'
    line_parts = [street, street_number]
    address_line = ' '.join(str(part).strip() for part in line_parts if part)
    address_neighborhood = _first_non_empty(
        parsed_address.get('neighborhood'),
        parsed_address.get('sublocality'),
        parsed_address.get('district'),
        _parsed_address_component(parsed_address, 'sublocality', 'sublocality_level_1', 'neighborhood'),
    )
    address_city = _first_non_empty(
        parsed_address.get('city'),
        parsed_address.get('locality'),
        _parsed_address_component(parsed_address, 'locality'),
        response_payload.get('city'),
    )
    address_state = _first_non_empty(
        parsed_address.get('state'),
        parsed_address.get('region'),
        _parsed_address_component(parsed_address, 'administrative_area_level_1'),
        response_payload.get('state'),
    )
    parsed_postal_code = _first_non_empty(
        parsed_address.get('postal_code'),
        _parsed_address_component(parsed_address, 'postal_code'),
        response_payload.get('postal_code'),
    )
    document_postal_code = _document_postal_code(raw_document_address)
    postal_code = (
        _first_non_empty(document_postal_code, parsed_postal_code)
        if issuing_country_iso3 == 'MEX'
        else parsed_postal_code
    )

    document_number = _first_non_empty(
        id_verification.get('document_number'),
        response_payload.get('document_number'),
        response_payload.get('personal_number'),
    )
    extra_fields = id_verification.get('extra_fields')
    if not isinstance(extra_fields, dict):
        extra_fields = {}
    if issuing_country_iso3 == 'BRA':
        database_validation_present, authoritative_cpf = (
            _authoritative_brazilian_cpf_from_database_validation(response_payload)
        )
        if authoritative_cpf:
            document_number = authoritative_cpf
        elif not database_validation_present:
            # Legacy Brazilian workflows expose CPF as OCR tax data. Keep this
            # checksum-validated fallback only when bra_cpf did not run.
            document_number = _first_non_empty(
                _single_brazilian_cpf_from_didit_payload(response_payload),
                document_number,
            )
    else:
        database_validation_present = False
        authoritative_cpf = None
    if issuing_country_iso3 in {'CHL', 'COL', 'MEX'}:
        document_number = _first_non_empty(
            id_verification.get('personal_number'),
            response_payload.get('personal_number'),
            document_number,
        )

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
        'verified_address': address_line or _first_non_empty(
            raw_document_address,
            parsed_address.get('formatted_address'),
            response_payload.get('full_address'),
            'Verified by Didit',
        ),
        'verified_address_neighborhood': address_neighborhood or '',
        'verified_city': address_city or 'Unknown City',
        'verified_state': address_state or 'Unknown State',
        'verified_country': _normalize_iso3(
            _first_non_empty(parsed_address.get('country'), response_payload.get('country'), issuing_country)
        ),
        'verified_postal_code': postal_code,
        'document_type': DOCUMENT_TYPE_MAP.get(str(document_type or '').strip().lower(), 'national_id'),
        'document_number': document_number,
        'document_issuing_country': issuing_country_iso3,
        'document_expiry_date': _parse_date(
            _first_non_empty(id_verification.get('expiration_date'), response_payload.get('expiration_date'))
        ),
        'brazilian_cpf_database_validation_present': database_validation_present,
        'brazilian_cpf_database_validation_valid': bool(authoritative_cpf),
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
    vendor_data = _safe_json_loads(response_payload.get('vendor_data'))
    if expected_user is not None:
        vendor_user_id = vendor_data.get('user_id')
        if not vendor_user_id:
            raise DiditAPIError('Didit session is missing its Confio user binding')
        if str(vendor_user_id) != str(expected_user.id):
            raise DiditAPIError('Didit session belongs to a different Confio user')
        return expected_user

    user_id = vendor_data.get('user_id')
    if not user_id:
        return None
    try:
        return User.objects.get(id=user_id)
    except User.DoesNotExist:
        return None


def retrieve_didit_decision(
    *,
    session_id: str,
    expected_user=None,
    expected_account_type: str | None = None,
    expected_business_id: str | None = None,
) -> dict[str, Any]:
    response_payload = _didit_request('GET', f'/v3/session/{session_id}/decision/')
    user = _resolve_user_from_payload(response_payload, expected_user=expected_user)
    if user is None:
        raise DiditAPIError('Could not match Didit session to a Confio user')
    vendor_data = _safe_json_loads(response_payload.get('vendor_data'))
    account_type = str(vendor_data.get('account_type') or 'personal')
    business_id = str(vendor_data.get('business_id') or '')
    if expected_account_type and account_type != expected_account_type:
        raise DiditAPIError('Didit session does not match the active account type')
    if expected_business_id and business_id != str(expected_business_id):
        raise DiditAPIError('Didit KYB session does not match the active business')
    session_kind = str(response_payload.get('session_kind') or '').lower()
    if account_type == 'business':
        if not business_id:
            raise DiditAPIError('Didit KYB session is missing its business binding')
        if session_kind and session_kind != 'business':
            raise DiditAPIError('A personal verification cannot verify a business')
        if _map_didit_status(response_payload) == 'verified' and session_kind != 'business':
            raise DiditAPIError('Approved KYB decision is missing its business session kind')
    elif session_kind == 'business':
        raise DiditAPIError('A business verification cannot verify a personal account')
    return response_payload


def retrieve_linked_didit_decision(*, session_id: str) -> dict[str, Any]:
    """Fetch a child KYC session whose ID came from an authenticated KYB decision."""
    return _didit_request('GET', f'/v3/session/{session_id}/decision/')


def verification_values_from_didit_decision(response_payload: dict[str, Any]) -> dict[str, Any]:
    return _extract_verification_payload(response_payload)


def _notify_verification_status_change(
    *,
    verification: IdentityVerification,
    account_type: str,
    business_id: str | None,
    previous_status: str | None,
    new_status: str,
) -> None:
    if previous_status == new_status or new_status not in {'verified', 'rejected'}:
        return

    business = None
    if account_type == 'business' and business_id:
        business = Business.objects.filter(id=business_id).first()

    if new_status == 'verified':
        create_notification(
            user=verification.user,
            business=business,
            notification_type=NotificationTypeChoices.ACCOUNT_VERIFIED,
            title='Cuenta verificada',
            message='Tu verificacion de identidad fue aprobada. Ya puedes continuar en Confio.',
            data={'verification_id': str(verification.id)},
            related_object_type='IdentityVerification',
            related_object_id=str(verification.id),
            action_url='confio://verification',
        )
        return

    create_notification(
        user=verification.user,
        business=business,
        notification_type=NotificationTypeChoices.SECURITY_ALERT,
        title='Verificacion rechazada',
        message='Tu verificacion de identidad no pudo ser aprobada. Revisa los requisitos e intentalo de nuevo.',
        data={
            'verification_id': str(verification.id),
            'reason': verification.rejected_reason or '',
        },
        related_object_type='IdentityVerification',
        related_object_id=str(verification.id),
        action_url='confio://verification',
    )


def _name_tokens(value: Any) -> set[str]:
    import unicodedata
    text = unicodedata.normalize('NFKD', str(value or ''))
    # Any script's letters (Иван, 민) and one-letter names (Min O) are names too.
    # Accents go; every other mark (a Devanagari vowel sign) stays INSIDE its
    # word, never splits it: राम and राज are two names, not a shared र.
    text = ''.join(char for char in text if not unicodedata.combining(char)).casefold()
    tokens, word = set(), []
    for char in text + ' ':
        if char.isalpha() or (word and unicodedata.category(char).startswith('M')):
            word.append(char)
        elif word:
            tokens.add(''.join(word))
            word = []
    return tokens


def _same_person(primary: IdentityVerification, extracted: dict[str, Any]) -> bool:
    """Same date of birth and overlapping given names AND surnames.

    Token overlap, not equality: a passport and a cédula of the same person
    often differ in how many given names or surnames they print.
    """
    if primary.verified_date_of_birth != extracted.get('verified_date_of_birth'):
        return False
    return bool(
        _name_tokens(primary.verified_first_name) & _name_tokens(extracted.get('verified_first_name'))
        and _name_tokens(primary.verified_last_name) & _name_tokens(extracted.get('verified_last_name'))
    )


def _bind_to_person(verification: IdentityVerification, extracted: dict[str, Any]) -> tuple[str, str]:
    """('verified', '') when this document is the same person as the user's other
    verified personal documents (or is the first one), else ('rejected', why).

    Applies to every personal document, primary or extra, whichever came first:
    an account belongs to one person. The anchor is the primary verification,
    else the earliest other verified personal document (all_documents, because
    the default manager hides extra ones). Null-safe: excluding a JSON key value
    also drops rows missing the key.
    """
    from django.db.models import Q
    anchor = (
        IdentityVerification.all_documents.filter(user=verification.user, status='verified')
        .filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))
        .exclude(pk=verification.pk)
        # The personal copy a company verification creates (security.models
        # ensure_personal_verified_on_save: empty risk_factors, the company's
        # document number) describes the company, not the person.
        .exclude(risk_factors={}, document_number__in=IdentityVerification.all_documents.filter(
            user=verification.user, risk_factors__account_type='business').values('document_number'))
        .order_by('is_additional_document', 'verified_at', 'created_at').first()
    )
    if anchor is None:
        return 'verified', ''
    if not _same_person(anchor, extracted):
        return 'rejected', 'El documento no coincide con tu identidad verificada.'
    return 'verified', ''


def _unmet_request(issuing_country: Any, document_type: Any, request: dict[str, Any] | None) -> str:
    """Why a document does not meet what the rail asked for ('' when it does)."""
    request = request or {}
    wanted_country = str(request.get('id_country') or '')
    if wanted_country and issuing_country != wanted_country:
        return 'El documento no es del país que pide este medio.'
    wanted_types = set(request.get('document_types') or [])
    if wanted_types and _DOCUMENT_TYPE_CODES.get(document_type) not in wanted_types:
        return 'Ese tipo de documento no sirve para este medio.'
    return ''


def _review_additional_document(verification: IdentityVerification, extracted: dict[str, Any],
                                decision: dict[str, Any]) -> tuple[str, str]:
    """(status, rejection reason) for an extra document Didit approved.

    Didit's own session already proved the document is genuine and that its
    portrait matches the live selfie. Requiring the SAME identity as the
    primary document (date of birth and names) then binds both documents to
    one person, so no second, paid face comparison is needed. Also checks the
    document is what the rail asked for.
    """
    request = (verification.risk_factors or {}).get('document_request') or {}
    unmet = _unmet_request(extracted.get('document_issuing_country'), extracted.get('document_type'), request)
    if unmet:
        return 'rejected', unmet
    return _bind_to_person(verification, extracted)


_DEFAULT_ADDITIONAL_REQUEST = {'id_country': '', 'document_types': ['ID', 'P']}


def didit_session_purpose(payload: dict[str, Any]) -> str:
    """'edd', 'additional' or 'identity', from the workflow Didit actually ran.
    Our own placeholder alone is not enough: a webhook can arrive before it exists."""
    workflow = str((payload or {}).get('workflow_id') or '').strip()
    if workflow and workflow == str(getattr(settings, 'DIDIT_EDD_WORKFLOW_ID', '') or ''):
        return 'edd'
    if workflow and workflow == str(getattr(settings, 'DIDIT_ADDITIONAL_DOCUMENT_WORKFLOW_ID', '') or ''):
        return 'additional'
    return 'identity'


def _session_lock_id(session_id: str) -> int:
    import hashlib
    digest = hashlib.sha256(f'didit-session:{session_id}'.encode()).digest()
    return int.from_bytes(digest[:8], 'big', signed=True)


def sync_didit_session(*, session_id: str, expected_user=None, expected_account_type=None, expected_business_id=None) -> tuple[IdentityVerification, dict[str, Any]]:
    from django.db import connection, transaction
    # One sync per Didit session at a time, from asking Didit to saving: a later
    # sync always reads Didit's later answer, and a slower one can never land
    # after it (Didit's answers carry no revision to order them by).
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [_session_lock_id(session_id)])
        return _sync_didit_session(session_id=session_id, expected_user=expected_user,
                                   expected_account_type=expected_account_type,
                                   expected_business_id=expected_business_id)


def _sync_didit_session(*, session_id: str, expected_user=None, expected_account_type=None, expected_business_id=None) -> tuple[IdentityVerification, dict[str, Any]]:
    # An EDD session (proof of address, source of funds) is not an identity
    # document. Refuse it here, whichever path delivers it (webhook or the
    # app's sync mutation), so it can never create or overwrite a verification.
    from payment_accounts.edd import is_edd_session
    if is_edd_session(session_id):
        raise DiditAPIError('Esta sesión no es una verificación de identidad.')
    response_payload = retrieve_didit_decision(
        session_id=session_id,
        expected_user=expected_user,
        expected_account_type=expected_account_type,
        expected_business_id=expected_business_id,
    )
    user = _resolve_user_from_payload(response_payload, expected_user=expected_user)
    if user is None:
        raise DiditAPIError('Could not match Didit session to a Confio user')

    vendor_data = _safe_json_loads(response_payload.get('vendor_data'))
    account_type = str(vendor_data.get('account_type') or 'personal')
    business_id = vendor_data.get('business_id')

    purpose = didit_session_purpose(response_payload)
    if purpose == 'edd':
        raise DiditAPIError('Esta sesión no es una verificación de identidad.')
    verification = _find_existing_verification(user=user, session_id=session_id)
    if verification is None:
        # A webhook that beats our own registration still files an extra
        # document as an extra document, never as the primary one.
        verification = ensure_pending_didit_verification(
            user=user,
            session_id=session_id,
            account_type=account_type,
            business_id=business_id,
            document_request=dict(_DEFAULT_ADDITIONAL_REQUEST) if purpose == 'additional' else None,
            request_is_default=True,
        )

    extracted = _extract_verification_payload(response_payload)
    status = _map_didit_status(response_payload)
    previous_status = verification.status
    risk_factors = dict(verification.risk_factors or {})
    risk_factors['provider'] = 'didit'
    risk_factors['didit'] = {
        'session_id': session_id,
        'status': response_payload.get('status'),
        'raw_status': response_payload.get('status'),
        # Didit media links are short-lived credentials. Persist the decision
        # facts needed for audit/backfills, never the signed media URLs.
        'session': _without_transient_didit_media(response_payload),
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
    verification.verified_address_neighborhood = extracted['verified_address_neighborhood']
    verification.verified_city = extracted['verified_city']
    verification.verified_state = extracted['verified_state']
    verification.verified_country = extracted['verified_country']
    verification.verified_postal_code = extracted['verified_postal_code']
    verification.document_type = extracted['document_type']
    verification.document_number = extracted['document_number'] or verification.document_number
    verification.document_issuing_country = extracted['document_issuing_country']
    verification.document_expiry_date = extracted['document_expiry_date']
    verification.risk_factors = risk_factors
    status = _enforce_brazilian_cpf_database_validation(
        status=status,
        document_issuing_country=verification.document_issuing_country,
        extracted=extracted,
        risk_factors=risk_factors,
    )
    review_reason = ''
    from django.db import transaction
    # One per-user lock for everything that records a Didit result: extra
    # documents of different people can never both pass, and a registration
    # that ran meanwhile keeps what it recorded (the rail's request, the flag).
    with transaction.atomic():
        type(user).objects.select_for_update().filter(pk=user.pk).first()
        current = IdentityVerification.all_documents.filter(pk=verification.pk).values(
            'is_additional_document', 'risk_factors').first() or {}
        if current.get('is_additional_document'):
            verification.is_additional_document = True
        request_now = (current.get('risk_factors') or {}).get('document_request')
        if request_now:
            # The database's request is authoritative: a registration may have
            # replaced the webhook's default with the rail's exact requirement.
            verification.risk_factors = {**(verification.risk_factors or {}), 'document_request': request_now}
        if verification.is_additional_document and status == 'verified':
            status, review_reason = _review_additional_document(verification, extracted, response_payload)
        elif status == 'verified' and (verification.risk_factors or {}).get('account_type') != 'business':
            # A primary verified after an extra document must be the same person too.
            status, review_reason = _bind_to_person(verification, extracted)
        verification.status = status
        if status == 'verified' and verification.verified_at is None:
            verification.verified_at = timezone.now()
        if status != 'rejected':
            verification.rejected_reason = None
        elif review_reason:
            verification.rejected_reason = review_reason
        verification.save()
    if not verification.is_additional_document:
        # An extra document is not "your account was verified"; the flow that
        # asked for it reads the result itself.
        _notify_verification_status_change(
            verification=verification,
            account_type=account_type,
            business_id=business_id,
            previous_status=previous_status,
            new_status=status,
        )

    return verification, response_payload


def verify_didit_webhook_signature(
    raw_body: bytes,
    signature_header: str | None,
    *,
    signature_v2_header: str | None = None,
    signature_simple_header: str | None = None,
    timestamp_header: str | None = None,
) -> bool:
    secret = (getattr(settings, 'DIDIT_WEBHOOK_SECRET', '') or '').strip()
    if not secret:
        return True

    secret_bytes = secret.encode('utf-8')

    if timestamp_header:
        try:
            timestamp = int(str(timestamp_header).strip())
        except (TypeError, ValueError):
            logger.warning('Didit webhook rejected due to invalid timestamp header')
            return False
        now_ts = int(timezone.now().timestamp())
        if abs(now_ts - timestamp) > 300:
            logger.warning('Didit webhook rejected due to stale timestamp header')
            return False

    provided_v2 = _extract_signature_value(signature_v2_header)
    if provided_v2:
        canonical_payload = _canonicalize_didit_payload(raw_body)
        if not canonical_payload:
            return False
        expected_v2 = hmac.new(
            secret_bytes,
            canonical_payload.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(expected_v2, provided_v2):
            return True

    provided_simple = _extract_signature_value(signature_simple_header)
    if provided_simple:
        simple_payload = _build_simple_signature_payload(raw_body)
        if not simple_payload:
            return False
        expected_simple = hmac.new(
            secret_bytes,
            simple_payload.encode('utf-8'),
            hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(expected_simple, provided_simple):
            return True

    provided_legacy = _extract_signature_value(signature_header)
    if not provided_legacy:
        return False
    expected_legacy = hmac.new(secret_bytes, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_legacy, provided_legacy)
