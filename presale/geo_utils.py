"""
Presale eligibility (geo-blocking).

Layered "reasonable measures" stack, checked in order:
  1. Test-account bypass — store-review accounts (configured reviewer phone
     numbers) are always eligible regardless of phone country or IP, so
     Apple/Google reviewers using the +1 test number can exercise the flow.
  2. Phone-country block — US and KR (existing behavior).
  3. IP-country block — US only. Country is resolved from the Cloudflare
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


def is_presale_test_account(user) -> bool:
    """Store-review test accounts bypass every geo check (phone + IP)."""
    try:
        from users.review_numbers import is_review_test_phone_key
        return is_review_test_phone_key(getattr(user, 'phone_key', None))
    except Exception:
        return False


# The IP resolver moved to security/geo.py — it was never presale-specific,
# and cusd_plus had to reach across app boundaries for it. Re-exported here so
# every existing presale call site keeps working unchanged.
from types import MappingProxyType  # noqa: E402

from security.geo import (  # noqa: E402,F401
    GeoPolicy,
    get_country_for_ip,
    normalize_country as _normalize_country,
)

PRESALE_POLICY = GeoPolicy(
    name='presale',
    phone_blocked=frozenset({'US', 'KR'}),
    message=US_BLOCK_MSG,
    phone_messages=MappingProxyType({'US': US_BLOCK_MSG, 'KR': KR_BLOCK_MSG}),
    # Preserved: a user with no phone country falls through to eligible here,
    # where Ondo fails closed. Now explicit rather than accidental.
    allow_missing_phone=True,
    # A SEPARATE list from the phone one, read at call time so the setting
    # stays live.
    ip_blocked=lambda: getattr(settings, 'PRESALE_IP_BLOCKED_COUNTRIES', ['US']),
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
