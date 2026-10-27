"""
Presale eligibility (geo-blocking).

Layered "reasonable measures" stack, checked in order:
  1. Test-account bypass — geo-exempt store-review accounts (the Argentine
     reviewer numbers) are always eligible regardless of phone country or IP,
     so Apple/Google reviewers can exercise the flow. The US/UK reviewer
     numbers get no bypass and see the block.
  2. Phone-country block — US, KR and GB.
  3. IP-country block — US and GB (PRESALE_IP_BLOCKED_COUNTRIES). Country is resolved from the Cloudflare
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

PRESALE_POLICY = GeoPolicy(
    name='presale',
    phone_blocked=frozenset({'US', 'KR', 'GB'}),
    # IP blocks: the IP country may be any on the list, so no country named.
    message=IP_BLOCK_MSG,
    phone_messages=MappingProxyType({'US': US_BLOCK_MSG, 'KR': KR_BLOCK_MSG, 'GB': GB_BLOCK_MSG}),
    # Preserved: a user with no phone country falls through to eligible here,
    # where Ondo fails closed. Now explicit rather than accidental.
    allow_missing_phone=True,
    # A SEPARATE list from the phone one, read at call time so the setting
    # stays live.
    ip_blocked=lambda: getattr(settings, 'PRESALE_IP_BLOCKED_COUNTRIES', ['US', 'GB']),
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
