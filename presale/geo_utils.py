"""
Presale eligibility (geo-blocking).

Layered "reasonable measures" stack, checked in order:
  1. Test-account bypass — geo-exempt store-review accounts (the Argentine
     reviewer numbers) are always eligible regardless of phone country or IP,
     so Apple/Google reviewers can exercise the flow. The US/UK reviewer
     numbers get no bypass and see the block.
  2. Phone-country block — KR and GB, plus the US unless
     PresaleSettings.us_access is 'open'.
  3. IP-country block — PRESALE_IP_BLOCKED_COUNTRIES (US and GB), the US
     again lifted only by us_access='open'. Country is resolved from the Cloudflare
     edge header when present, then the cached security.IPAddress row, then
     a live ipapi.co lookup. Unresolvable country fails OPEN (the phone
     block and the self-attestation checkbox remain as the other layers).
"""
import ipaddress
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

US_BLOCK_MSG = "Lo sentimos, los residentes de Estados Unidos no pueden participar en la preventa."
KR_BLOCK_MSG = "Lo sentimos, los ciudadanos/residentes de Corea del Sur no pueden participar en la preventa."
GB_BLOCK_MSG = "Lo sentimos, los residentes del Reino Unido no pueden participar en la preventa."
IP_BLOCK_MSG = "Lo sentimos, la preventa no está disponible en tu país."


def is_presale_test_account(user) -> bool:
    """Geo-exempt store-review accounts bypass every geo check (phone + IP);
    reviewer numbers in blocked countries do not (security.geo)."""
    from security.geo import store_review_exempt
    return store_review_exempt(user)


# The IP resolver moved to security/geo.py — it was never presale-specific,
# and cusd_plus had to reach across app boundaries for it. Re-exported here so
# every existing presale call site keeps working unchanged.
from types import MappingProxyType  # noqa: E402

from security.geo import (  # noqa: E402,F401
    GeoPolicy,
    get_country_for_ip,
    normalize_country as _normalize_country,
)

#: Blocked regardless of the US switch.
_ALWAYS_BLOCKED = frozenset({'KR', 'GB'})


def us_access() -> str:
    """PresaleSettings.us_access, read live from the admin. Fails CLOSED:
    an unreadable setting blocks the US outright, waitlist included."""
    from .models import PresaleSettings
    try:
        return PresaleSettings.get_settings().us_access
    except Exception:  # noqa: BLE001
        logger.exception('[PRESALE] us_access unreadable; treating the US as blocked')
        return PresaleSettings.US_ACCESS_BLOCKED


def _us_open() -> bool:
    from .models import PresaleSettings
    return us_access() == PresaleSettings.US_ACCESS_OPEN


def _ip_blocked_setting():
    return getattr(settings, 'PRESALE_IP_BLOCKED_COUNTRIES', ['US', 'GB'])


PRESALE_POLICY = GeoPolicy(
    name='presale',
    phone_blocked=lambda: _ALWAYS_BLOCKED if _us_open() else _ALWAYS_BLOCKED | {'US'},
    # IP blocks: the IP country may be any on the list, so no country named.
    message=IP_BLOCK_MSG,
    phone_messages=MappingProxyType({'US': US_BLOCK_MSG, 'KR': KR_BLOCK_MSG, 'GB': GB_BLOCK_MSG}),
    # Preserved: a user with no phone country falls through to eligible here,
    # where Ondo fails closed. Now explicit rather than accidental.
    allow_missing_phone=True,
    # A SEPARATE list from the phone one, read at call time so the setting
    # stays live.
    ip_blocked=lambda: [c for c in _ip_blocked_setting() if not (c == 'US' and _us_open())],
    # Preserved: presale never swallowed a resolver raise.
    ip_fails_open_on_error=False,
    bypass=is_presale_test_account,
)


def check_presale_eligibility(user, client_ip: str | None = None, ip_country_hint: str | None = None):
    """
    Check presale eligibility by phone country and (when available) IP country.
    Returns: (is_eligible: bool, error_message: str|None)
    """
    decision = PRESALE_POLICY.evaluate(
        user, client_ip=client_ip, ip_country_hint=ip_country_hint)
    return decision.allowed, decision.message


# The presale policy with the US lifted and every other block kept: who may
# join the US waitlist. Buying stays blocked by PRESALE_POLICY.
US_WAITLIST_POLICY = GeoPolicy(
    name='presale_us_waitlist',
    phone_blocked=_ALWAYS_BLOCKED,
    message=IP_BLOCK_MSG,
    phone_messages=PRESALE_POLICY.phone_messages,
    allow_missing_phone=True,
    ip_blocked=lambda: [c for c in _ip_blocked_setting() if c != 'US'],
    ip_fails_open_on_error=False,
    bypass=is_presale_test_account,
)


# The legacy Algorand WebSocket rail predates the US switch and stays closed
# to the US whatever it says: its attestation is optional for old clients.
LEGACY_PRESALE_POLICY = GeoPolicy(
    name='presale_legacy',
    phone_blocked=_ALWAYS_BLOCKED | {'US'},
    message=IP_BLOCK_MSG,
    phone_messages=PRESALE_POLICY.phone_messages,
    allow_missing_phone=True,
    ip_blocked=_ip_blocked_setting,
    ip_fails_open_on_error=False,
    bypass=is_presale_test_account,
)


def check_legacy_presale_eligibility(user, client_ip: str | None = None, ip_country_hint: str | None = None):
    """check_presale_eligibility for the legacy rail: the US always blocked."""
    decision = LEGACY_PRESALE_POLICY.evaluate(
        user, client_ip=client_ip, ip_country_hint=ip_country_hint)
    return decision.allowed, decision.message


def check_us_waitlist_eligibility(user, client_ip: str | None = None, ip_country_hint: str | None = None):
    """Same contract as check_presale_eligibility, for the US waitlist. Only
    while us_access is 'waitlist': blocked has no list, open needs none."""
    from .models import PresaleSettings
    if us_access() != PresaleSettings.US_ACCESS_WAITLIST:
        return False, US_BLOCK_MSG
    decision = US_WAITLIST_POLICY.evaluate(
        user, client_ip=client_ip, ip_country_hint=ip_country_hint)
    return decision.allowed, decision.message


ACCESS_BUY = 'buy'
ACCESS_US_WAITLIST = 'us_waitlist'
ACCESS_BLOCKED = 'blocked'


def presale_access(user, client_ip: str | None = None, ip_country_hint: str | None = None) -> dict:
    """What this user may do, for the app to show: buy, join the US
    waitlist, or nothing (with the refusal copy). The purchase and waitlist
    mutations re-check on their own; this only decides the screen."""
    ok, message = check_presale_eligibility(user, client_ip=client_ip, ip_country_hint=ip_country_hint)
    mode = us_access()
    from .models import PresaleSettings
    common = {'us_access': mode, 'not_us_attestation_required': mode != PresaleSettings.US_ACCESS_OPEN}
    if ok:
        return {'access': ACCESS_BUY, 'message': None, **common}
    if check_us_waitlist_eligibility(user, client_ip=client_ip, ip_country_hint=ip_country_hint)[0]:
        return {'access': ACCESS_US_WAITLIST, 'message': message, **common}
    return {'access': ACCESS_BLOCKED, 'message': message, **common}
