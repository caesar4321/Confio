import hashlib
import hmac
import json
import logging
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any

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


def _normalized_identity_name(value: Any) -> str:
    normalized = unicodedata.normalize('NFKD', str(value or ''))
    return ''.join(char for char in normalized if char.isalnum()).casefold()


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


def resolve_brazilian_cpf_for_verification(verification: IdentityVerification) -> tuple[str | None, list[int]]:
    """Resolve one collision-free CPF from this identity's matching Didit attempts."""
    identity_key = (
        _normalized_identity_name(verification.verified_first_name),
        _normalized_identity_name(verification.verified_last_name),
        verification.verified_date_of_birth,
        str(verification.document_issuing_country or '').upper(),
    )
    candidates: dict[str, set[int]] = {}
    attempts = IdentityVerification.objects.filter(
        user_id=verification.user_id,
        document_issuing_country='BRA',
    ).exclude(pk=verification.pk)
    attempts = [verification, *attempts]
    for attempt in attempts:
        attempt_key = (
            _normalized_identity_name(attempt.verified_first_name),
            _normalized_identity_name(attempt.verified_last_name),
            attempt.verified_date_of_birth,
            str(attempt.document_issuing_country or '').upper(),
        )
        if attempt_key != identity_key:
            continue
        session = ((attempt.risk_factors or {}).get('didit') or {}).get('session') or {}
        attempt_cpfs: set[str] = set()
        database_validation_present = False
        authoritative_cpf = None
        if isinstance(session, dict):
            database_validation_present, authoritative_cpf = (
                _authoritative_brazilian_cpf_from_database_validation(session)
            )
            if authoritative_cpf:
                attempt_cpfs.add(authoritative_cpf)
            elif not database_validation_present:
                attempt_cpfs = _brazilian_cpfs_from_didit_payload(session)
        stored_cpf = normalize_brazilian_cpf(attempt.document_number)
        if stored_cpf and not (
            isinstance(session, dict)
            and database_validation_present
            and not authoritative_cpf
        ):
            attempt_cpfs.add(stored_cpf)
        for cpf in attempt_cpfs:
            candidates.setdefault(cpf, set()).add(attempt.pk)

    if len(candidates) != 1:
        return None, []
    cpf, source_ids = next(iter(candidates.items()))
    collision = IdentityVerification.objects.filter(
        document_issuing_country='BRA',
        document_number_normalized=cpf,
        status='verified',
    ).exclude(user_id=verification.user_id).exists()
    return (None, []) if collision else (cpf, sorted(source_ids))


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


def _workflow_id_for_account(account_type: str, phone_country: str | None = None) -> str:
    business_workflow = getattr(settings, 'DIDIT_BUSINESS_WORKFLOW_ID', '') or ''
    workflow_map = getattr(settings, 'DIDIT_WORKFLOW_IDS_BY_PHONE_COUNTRY', {}) or {}
    normalized_phone_country = str(phone_country or '').strip().upper()
    workflow_id = business_workflow if account_type == 'business' and business_workflow else ''
    if not workflow_id and normalized_phone_country:
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


def create_didit_session(*, user, account_type: str = 'personal', business_id: str | None = None, callback_url: str | None = None) -> dict[str, Any]:
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

    payload: dict[str, Any] = {
        'workflow_id': _workflow_id_for_account(account_type, phone_country=phone_country),
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
    if response_payload.get('session_kind') == 'business':
        registry_checks = response_payload.get('registry_checks') or []
        registry = next(
            (
                item for item in registry_checks
                if isinstance(item, dict)
                and str(item.get('status') or '').strip().lower() == 'approved'
            ),
            registry_checks[0] if registry_checks else {},
        )
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


def sync_didit_session(*, session_id: str, expected_user=None) -> tuple[IdentityVerification, dict[str, Any]]:
    response_payload = retrieve_didit_decision(
        session_id=session_id,
        expected_user=expected_user,
    )
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
    verification.status = status
    if (
        status == 'verified'
        and verification.document_issuing_country == 'BRA'
        and not extracted.get('brazilian_cpf_database_validation_present')
        and not normalize_brazilian_cpf(verification.document_number)
    ):
        recovered_cpf, source_ids = resolve_brazilian_cpf_for_verification(verification)
        if recovered_cpf:
            verification.document_number = recovered_cpf
            risk_factors['document_number_recovery'] = {
                'source': 'matching_didit_attempts',
                'source_verification_ids': source_ids,
                'recovered_at': timezone.now().isoformat(),
                'reason': 'approved_brazil_identity_missing_valid_cpf',
            }
    if status == 'verified' and verification.verified_at is None:
        verification.verified_at = timezone.now()
    if status != 'rejected':
        verification.rejected_reason = None
    verification.save()
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
