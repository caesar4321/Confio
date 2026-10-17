"""Rules for the paid-offer probes (Confío IA+, Cuenta inteligente).

Pure intent probes: nothing is sold, charged or unlocked. Who sees each door:

- Confío IA+: the assistant header pill and investing chips, for anyone who
  is not an employee, on a build that has the pitch screen.
- Cuenta inteligente: the Billeteras row for everyone (funded or not; the
  waitlist records which, so the target persona is read apart), plus
  pain-point / asked chips; never employees.

Each probe has its own server flag, so App Review objections can turn one off
alone. Prices come from settings, never from app copy.

Since 2026-10-17 Confío IA+ is a benefit inside Cuenta inteligente (like Nu+
or Robinhood Gold), not its own offer: IA_PLUS_PROBE_ENABLED is off and its
doors open Cuenta inteligente. The preview list no longer turns the standalone
IA+ back on, so a tester sees what everyone sees.
"""
import re

from django.conf import settings

from .models_product_waitlist import PRODUCT_IA_PLUS, PRODUCT_SMART_ACCOUNT, PRODUCTS

FLAGS = {
    PRODUCT_IA_PLUS: 'IA_PLUS_PROBE_ENABLED',
    PRODUCT_SMART_ACCOUNT: 'SMART_ACCOUNT_PROBE_ENABLED',
}
PRICES = {
    PRODUCT_IA_PLUS: 'IA_PLUS_MONTHLY_PRICE_USD',
    PRODUCT_SMART_ACCOUNT: 'SMART_ACCOUNT_MONTHLY_PRICE_USD',
}
EVENT = 'paid_offer_interest'


def previewing(user_id):
    """Listed people (the founder testing a pre-release build on a real
    phone) see both probes whatever the flags and the build number say."""
    preview = str(getattr(settings, 'PAID_OFFER_PREVIEW_USER_IDS', '') or '')
    return user_id is not None and str(user_id) in {p.strip() for p in preview.split(',') if p.strip()}


def enabled(product, user_id=None):
    """The probe's flag, or a preview for listed people (never for the
    standalone Confío IA+, now part of Cuenta inteligente)."""
    if product not in PRODUCTS:
        return False
    on = bool(getattr(settings, FLAGS[product], False))
    return on or (product != PRODUCT_IA_PLUS and previewing(user_id))


def price(product):
    """The monthly price as shown ("9.99"), or None: the screen then hides it."""
    value = str(getattr(settings, PRICES.get(product, ''), '') or '').strip()
    return value if re.fullmatch(r'[0-9]{1,4}(\.[0-9]{2})?', value) else None


def _version(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}', value):
        return None
    return tuple(int(part) for part in value.split('.'))


def _at_least(meta, setting):
    floor = _version(str(getattr(settings, setting, '') or ''))
    version = _version(str((meta or {}).get('HTTP_X_CONFIO_VERSION', '') or ''))
    return floor is not None and version is not None and version >= floor


def app_version(meta):
    """The build that made the request ("5.2.4"), or '' (stamped on probe
    events so a pitch change is read by build, not by date)."""
    value = str((meta or {}).get('HTTP_X_CONFIO_VERSION', '') or '')
    return value if _version(value) else ''


def client_supports(meta):
    """True on app builds that have the pitch screen, so old builds never get
    a chip that opens nothing (and are never counted as shown)."""
    return _at_least(meta, 'PAID_OFFER_MIN_APP_VERSION')


def _has_plus(user_id):
    from assistant.models import AssistantSubscription
    from django.utils import timezone

    now = timezone.now()
    return any(sub.is_entitled(now) for sub in AssistantSubscription.objects.filter(user_id=user_id))


def available(product, *, is_employee, meta, user_id=None):
    """Can this person open the pitch at all (from any door)? Someone who
    already has Assistant+ is never pitched Confío IA+."""
    if not (enabled(product, user_id) and not is_employee and (client_supports(meta) or previewing(user_id))):
        return False
    return not (product == PRODUCT_IA_PLUS and user_id is not None and _has_plus(user_id))


def ia_plus_bundled(*, meta, user_id=None):
    """Does this person's Cuenta inteligente pitch include Confío IA+? Only on
    builds that show the perk block (older pitches never mention it), and
    never for someone who already has Assistant+."""
    if not (_at_least(meta, 'SMART_ACCOUNT_IA_PLUS_MIN_APP_VERSION') or previewing(user_id)):
        return False
    return not (user_id is not None and _has_plus(user_id))


def billeteras_row_visible(*, is_employee, meta, user_id=None):
    """The Cuenta inteligente row: whoever can open the pitch. It was
    ever-funded only (design 21A) until 2026-10-14: 7 views in 3 days was too
    little to learn from, and the waitlist's `funded` keeps the persona split."""
    return available(PRODUCT_SMART_ACCOUNT, is_employee=is_employee, meta=meta, user_id=user_id)
