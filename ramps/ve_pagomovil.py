"""Venezuelan Pago Móvil, provider-neutral.

The app only ever speaks "VE Pago Móvil": top up with bolívares (Recargar) and
send bolívares (Enviar). Which provider does each is a server setting:

  VE_PAGOMOVIL_TOPUP_PROVIDER  new top-ups   (adapter registry below)
  VE_PAGOMOVIL_SEND_PROVIDER   new sends

An existing order always stays with the provider that created it
(RampTransaction.provider), so switching a setting never strands an order.
Product rules (who may use it, app floors, limits) live here, not in a
provider module.
"""
from __future__ import annotations

import importlib
import re
from decimal import Decimal, InvalidOperation

from django.conf import settings

TOPUP = 'on_ramp'
SEND = 'off_ramp'

# Provider name -> adapter module (see each module's docstring for the
# functions it implements).
TOPUP_ADAPTERS = {'vexpay': 'ramps.vexpay_topup'}
SEND_ADAPTERS = {'pagoasap': 'ramps.pagoasap_send'}

# Venezuelan banks that take Pago Móvil (SUDEBAN codes). Ours, not a
# provider's: the picker never depends on a provider being reachable.
BANKS = (
    ('0102', 'Banco de Venezuela'),
    ('0104', 'Banco Venezolano de Crédito'),
    ('0105', 'Banco Mercantil'),
    ('0108', 'BBVA Provincial'),
    ('0114', 'Bancaribe'),
    ('0115', 'Banco Exterior'),
    ('0128', 'Banco Caroní'),
    ('0134', 'Banesco'),
    ('0137', 'Banco Sofitasa'),
    ('0138', 'Banco Plaza'),
    ('0146', 'Bangente'),
    ('0151', 'BFC Banco Fondo Común'),
    ('0156', '100% Banco'),
    ('0157', 'DelSur'),
    ('0163', 'Banco del Tesoro'),
    ('0166', 'Banco Agrícola de Venezuela'),
    ('0168', 'Bancrecer'),
    ('0169', 'R4 Banco Microfinanciero'),
    ('0171', 'Banco Activo'),
    ('0172', 'Bancamiga'),
    ('0174', 'Banplus'),
    ('0175', 'Banco Digital de los Trabajadores'),
    ('0177', 'Banfanb'),
    ('0191', 'Banco Nacional de Crédito (BNC)'),
)
BANK_NAMES = dict(BANKS)
CEDULA_RE = re.compile(r'^[VEJPG]\d{6,9}$')


class VePagoMovilError(Exception):
    """User-facing refusal; the message is Spanish copy for the app."""

    def __init__(self, message: str, next_step: str | None = None):
        super().__init__(message)
        self.next_step = next_step


# ------------------------------------------------------------------ gates

def _version(value) -> tuple | None:
    value = str(value or '').strip()
    if not re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}', value):
        return None
    return tuple(int(part) for part in value.split('.'))


def client_supports(direction: str, meta) -> bool:
    """Only builds with the VE screens get the rows (an older build would
    open the Infinia screen for them). An unset floor shows them to nobody."""
    name = 'VE_PAGOMOVIL_TOPUP_MIN_APP_VERSION' if direction == TOPUP else 'VE_PAGOMOVIL_SEND_MIN_APP_VERSION'
    floor = _version(getattr(settings, name, ''))
    version = _version((meta or {}).get('HTTP_X_CONFIO_VERSION', ''))
    return floor is not None and version is not None and version >= floor


def enabled(direction: str) -> bool:
    name = 'VE_PAGOMOVIL_TOPUP_ENABLED' if direction == TOPUP else 'VE_PAGOMOVIL_SEND_ENABLED'
    return bool(getattr(settings, name, False))


def setting_decimal(name: str, default: str) -> Decimal:
    try:
        return Decimal(str(getattr(settings, name, default)))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


# ------------------------------------------------------------------ adapters

def _load(path: str):
    return importlib.import_module(path)


def topup_adapter(provider: str | None = None):
    """The adapter for `provider`, or for new top-ups when None."""
    name = provider or getattr(settings, 'VE_PAGOMOVIL_TOPUP_PROVIDER', 'vexpay')
    path = TOPUP_ADAPTERS.get(name)
    if not path:
        raise VePagoMovilError('Las recargas en bolívares no están disponibles por ahora.')
    return _load(path)


def send_adapter(provider: str | None = None):
    name = provider or getattr(settings, 'VE_PAGOMOVIL_SEND_PROVIDER', 'pagoasap')
    path = SEND_ADAPTERS.get(name)
    if not path:
        raise VePagoMovilError('Los envíos en bolívares no están disponibles por ahora.')
    return _load(path)


def _providers(direction: str) -> list[str]:
    return list(TOPUP_ADAPTERS if direction == TOPUP else SEND_ADAPTERS)


def owned_order(user, order_id, direction: str):
    """The user's order by id, whatever provider made it."""
    from django.core.exceptions import ValidationError
    from ramps.models import RampTransaction
    if not (user and getattr(user, 'is_authenticated', False)):
        return None
    try:
        return RampTransaction.objects.filter(
            provider__in=_providers(direction), direction=direction, actor_user=user,
            country_code='VE', internal_id=order_id,
        ).first()
    except (ValueError, TypeError, ValidationError):
        return None


def adapter_for(ramp):
    return topup_adapter(ramp.provider) if ramp.direction == TOPUP else send_adapter(ramp.provider)


def active_order(user, direction: str):
    """The order the app resumes, across providers (newest first)."""
    found = []
    for provider in _providers(direction):
        adapter = topup_adapter(provider) if direction == TOPUP else send_adapter(provider)
        ramp = adapter.active_order(user)
        if ramp is not None:
            found.append(ramp)
    return max(found, key=lambda r: r.created_at) if found else None


# ------------------------------------------------------------------ display

# What a person sees as the counterparty of a VE order. Never a provider name:
# partners are confidential (NDA) and can change without the user noticing.
PUBLIC_NAME = 'Pago Móvil'


def public_provider_name(ramp) -> str:
    """The provider label shown to users for any ramp."""
    if ramp.provider in TOPUP_ADAPTERS or ramp.provider in SEND_ADAPTERS:
        return PUBLIC_NAME
    return ramp.get_provider_display()


# ------------------------------------------------------------------ input

def normalize_cedula(value: str) -> str:
    cleaned = re.sub(r'[^A-Z0-9]', '', str(value or '').upper())
    if cleaned and cleaned[0].isdigit():
        cleaned = f'V{cleaned}'
    if not CEDULA_RE.fullmatch(cleaned):
        raise VePagoMovilError('La cédula debe tener el formato V12345678.')
    return cleaned


def normalize_phone(value: str) -> str:
    """Venezuelan mobile → 58 + 10 digits."""
    digits = re.sub(r'\D', '', str(value or ''))
    if digits.startswith('58') and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith('0') and len(digits) == 11:
        digits = digits[1:]
    if not re.fullmatch(r'4(12|14|16|22|24|26)\d{7}', digits):
        raise VePagoMovilError('El teléfono debe ser un móvil venezolano, por ejemplo 0414 1234567.')
    return f'58{digits}'


def normalize_bank(value) -> str:
    """A 4-digit SUDEBAN code from the list above."""
    digits = re.sub(r'\D', '', str(value or ''))
    code = digits.zfill(4) if digits and len(digits) <= 4 else ''
    if code not in BANK_NAMES:
        raise VePagoMovilError('Elige un banco de la lista.')
    return code
