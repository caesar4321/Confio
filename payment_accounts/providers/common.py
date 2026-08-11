from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional


@dataclass(frozen=True)
class ProviderResult:
    resource_id: str
    status: str
    provider_status: str
    raw: dict[str, Any] = field(default_factory=dict)
    available_balance: Optional[Decimal] = None
    current_balance: Optional[Decimal] = None


ACCOUNT_STATUS_MAP = {
    'ACTIVE': 'active',
    'CONNECTED': 'active',
    'COMPLETED': 'active',
    'PROVISIONING': 'pending',
    'PENDING': 'pending',
    'PROCESSING': 'pending',
    'SUSPENDED': 'suspended',
    'REJECTED': 'rejected',
    'CLOSED': 'closed',
    'FAILED': 'failed',
    'ERROR': 'failed',
}

OPERATION_STATUS_MAP = {
    'PENDING': 'submitted',
    'INITIATED': 'submitted',
    'IN_PROGRESS': 'processing',
    'PROCESSING': 'processing',
    'PENDING_APPROVAL': 'needs_review',
    'SETTLING': 'settling',
    'COMPLETED': 'succeeded',
    'SUCCESS': 'succeeded',
    'SUCCEEDED': 'succeeded',
    'FAILED': 'failed',
    'ERROR': 'failed',
    'REJECTED': 'failed',
    'CANCELED': 'failed',
    'CANCELLED': 'failed',
    'EXPIRED': 'failed',
    'RETURNED': 'reversed',
    'REVERSED': 'reversed',
}


def iso_alpha2(value):
    """Translate Confío's canonical ISO alpha-3 country to provider alpha-2."""
    import pycountry

    normalized = str(value or '').strip().upper()
    if normalized in {'XX', 'XXX'}:
        return 'XX'
    if len(normalized) == 2:
        country = pycountry.countries.get(alpha_2=normalized)
    elif len(normalized) == 3:
        country = pycountry.countries.get(alpha_3=normalized)
    else:
        country = None
    if not country:
        raise ValueError(f'Unsupported ISO country code: {value!r}')
    return country.alpha_2


def same_country(left, right):
    try:
        return iso_alpha2(left) == iso_alpha2(right)
    except ValueError:
        return False


def provider_status(payload):
    status = payload.get('status', '') if isinstance(payload, dict) else ''
    if isinstance(status, dict):
        status = status.get('state') or status.get('status') or ''
    return str(status or '').strip().upper()


def account_status(payload):
    raw = provider_status(payload)
    if not raw and isinstance(payload, dict):
        raw = str((payload.get('connectivity') or {}).get('status') or '').upper()
    return ACCOUNT_STATUS_MAP.get(raw, 'pending'), raw


def operation_status(payload):
    raw = provider_status(payload)
    return OPERATION_STATUS_MAP.get(raw, 'unknown'), raw
