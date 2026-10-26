"""QR Bolivia, provider-neutral.

The app only knows "QR Bolivia": Recibir (show a QR any Bolivian bank app can
pay; the bolivianos arrive as dollars in the person's balance) and Enviar
(pay any Bolivian QR from that balance). Which provider does each is a server
setting, like Venezuelan Pago Móvil (ramps/ve_pagomovil.py):

  BOLIVIA_QR_RECEIVE_PROVIDER  new receive orders (RECEIVE_ADAPTERS)
  BOLIVIA_QR_SEND_PROVIDER     new sends        (SEND_ADAPTERS)

An existing order always stays with the provider that created it. Each
direction has an explicit switch and an app floor; while a direction is on,
Koywe's matching row is replaced for Bolivian users (koywe_replaced).
"""
from __future__ import annotations

import importlib

from django.conf import settings

from ramps.ve_pagomovil import VePagoMovilError, _version, optional_limit  # noqa: F401  (shared helpers)

RECEIVE = 'on_ramp'
SEND = 'off_ramp'
COUNTRY = 'BO'
PUBLIC_NAME = 'QR Bolivia'

# Provider name -> adapter module. Never shown to users (partners are
# confidential and can change without the user noticing).
RECEIVE_ADAPTERS = {
    'stereum': 'ramps.bolivia_qr_stereum',
    'mesadepagos': 'ramps.bolivia_qr_mesadepagos',
}
SEND_ADAPTERS = {
    'stereum': 'ramps.bolivia_qr_stereum',
    'mesadepagos': 'ramps.bolivia_qr_mesadepagos',
}
UNAVAILABLE = {
    RECEIVE: 'Recibir con QR Bolivia no está disponible por ahora.',
    SEND: 'Pagar con QR Bolivia no está disponible por ahora.',
}


class BoliviaQrError(VePagoMovilError):
    """User-facing refusal (Spanish copy); the send core's error type."""


# ------------------------------------------------------------------ gates

def _setting(direction: str, suffix: str):
    name = f"BOLIVIA_QR_{'RECEIVE' if direction == RECEIVE else 'SEND'}_{suffix}"
    return getattr(settings, name, None)


def enabled(direction: str) -> bool:
    return bool(_setting(direction, 'ENABLED'))


def client_supports(direction: str, meta) -> bool:
    """Only builds with the QR Bolivia screens get the rows; an unset floor
    shows them to nobody."""
    floor = _version(_setting(direction, 'MIN_APP_VERSION') or '')
    version = _version((meta or {}).get('HTTP_X_CONFIO_VERSION', ''))
    return floor is not None and version is not None and version >= floor


def is_tester(user) -> bool:
    raw = str(getattr(settings, 'BOLIVIA_QR_TEST_USER_IDS', '') or '')
    ids = {part.strip() for part in raw.split(',') if part.strip()}
    return bool(user and getattr(user, 'pk', None) and str(user.pk) in ids)


def offered(direction: str, meta, user=None) -> bool:
    """Shown to this build: the switch is on (or the person is a listed
    tester, for the final tests before it is), and the build has the screens."""
    return (enabled(direction) or is_tester(user)) and client_supports(direction, meta)


def is_bolivian(user) -> bool:
    return str(getattr(user, 'phone_country', '') or '').strip().upper() == COUNTRY


def koywe_replaced(user, meta) -> dict:
    """Which Koywe rows QR Bolivia replaces for this person right now: the
    switch is on and their build has the screens that take over."""
    bolivian = bool(user and getattr(user, 'is_authenticated', False) and is_bolivian(user))
    return {
        'top_up': bolivian and offered(RECEIVE, meta, user),
        'withdraw': bolivian and offered(SEND, meta, user),
    }


# ------------------------------------------------------------------ adapters

def provider_name(direction: str) -> str:
    return str(_setting(direction, 'PROVIDER') or '').strip().lower()


def adapter(direction: str, provider: str | None = None):
    registry = RECEIVE_ADAPTERS if direction == RECEIVE else SEND_ADAPTERS
    path = registry.get(provider or provider_name(direction))
    if not path:
        raise BoliviaQrError(UNAVAILABLE[direction])
    return importlib.import_module(path)


def providers(direction: str) -> list[str]:
    return list(RECEIVE_ADAPTERS if direction == RECEIVE else SEND_ADAPTERS)


def is_bolivia_qr(ramp) -> bool:
    """A QR Bolivia order (RampTransaction.provider is the adapter name)."""
    return ramp.country_code == COUNTRY and ramp.provider in (set(RECEIVE_ADAPTERS) | set(SEND_ADAPTERS))
