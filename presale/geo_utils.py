"""
Presale eligibility (geo-blocking).

Layered "reasonable measures" stack, checked in order:
  1. Test-account bypass — geo-exempt store-review accounts (the Argentine
     reviewer numbers) are always eligible regardless of phone country or IP,
     so Apple/Google reviewers can exercise the flow. The US/UK reviewer
     numbers get no bypass and see the block.
  2. Country block — every country PresaleCountryAccess does not mark open
     (seeded: US waitlist, KR and GB blocked), against the user's country:
     User.country, from GPS, else the 90-day IP majority, else the signup IP.
  3. IP-country block — the same rows, against the request's IP. Country is
     resolved from the Cloudflare
     edge header when present, then the cached security.IPAddress row, then
     a live ipapi.co lookup. Unresolvable country fails OPEN (the phone
     block and the self-attestation checkbox remain as the other layers).
"""
import ipaddress
import logging

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

from dataclasses import dataclass  # noqa: E402


@dataclass(frozen=True)
class CountryRule:
    access: str


#: Used when the admin table can't be read or is empty: today's blocks,
#: with no waitlist and nothing open.
FAILSAFE_RULES = MappingProxyType({
    'US': CountryRule('blocked'),
    'KR': CountryRule('blocked'),
    'GB': CountryRule('blocked'),
})

#: "residentes ___" for the waitlist copy.
_RESIDENTS_OF = MappingProxyType({
    'US': 'de EE. UU.',
    'KR': 'de Corea del Sur',
    'GB': 'del Reino Unido',
})


def residents_of(country: str | None) -> str:
    return _RESIDENTS_OF.get(country or '', 'de tu país')


def country_rules() -> MappingProxyType:
    """PresaleCountryAccess, read live from the admin. Fails CLOSED: an
    unreadable or empty table falls back to FAILSAFE_RULES, so deleting
    every row can never open the presale everywhere."""
    from .models import PresaleCountryAccess
    try:
        rows = {r.country: CountryRule(r.access)
                for r in PresaleCountryAccess.objects.all()}
    except Exception:  # noqa: BLE001
        logger.exception('[PRESALE] country access unreadable; using the failsafe blocks')
        return FAILSAFE_RULES
    return MappingProxyType(rows) if rows else FAILSAFE_RULES


def country_access(country: str) -> str:
    """'blocked', 'waitlist' or 'open' for one country (no row = open)."""
    from .models import PresaleCountryAccess
    rule = country_rules().get(country)
    return rule.access if rule else PresaleCountryAccess.ACCESS_OPEN


def us_access() -> str:
    return country_access('US')


def _restricted(*, blocked_only: bool = False):
    """Countries that refuse, by the user's country and by IP alike.
    blocked_only leaves out waitlist countries: who may still join one."""
    from .models import PresaleCountryAccess as A
    refusing = {A.ACCESS_BLOCKED} if blocked_only else {A.ACCESS_BLOCKED, A.ACCESS_WAITLIST}
    return frozenset(c for c, r in country_rules().items() if r.access in refusing)


_COPY = MappingProxyType({'US': US_BLOCK_MSG, 'KR': KR_BLOCK_MSG, 'GB': GB_BLOCK_MSG})

PRESALE_POLICY = GeoPolicy(
    name='presale',
    phone_blocked=lambda: _restricted(),
    # IP blocks: the IP country may be any on the list, so no country named.
    message=IP_BLOCK_MSG,
    phone_messages=_COPY,
    # Preserved: a user with no phone country falls through to eligible here,
    # where Ondo fails closed. Now explicit rather than accidental.
    allow_missing_phone=True,
    # None = the same list, read once per check, for the request IP.
    ip_blocked=None,
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


# The presale policy with waitlist countries let through: who may join a
# country waitlist. Buying stays refused by PRESALE_POLICY.
WAITLIST_POLICY = GeoPolicy(
    name='presale_waitlist',
    phone_blocked=lambda: _restricted(blocked_only=True),
    message=IP_BLOCK_MSG,
    phone_messages=_COPY,
    allow_missing_phone=True,
    ip_blocked=None,
    ip_fails_open_on_error=False,
    bypass=is_presale_test_account,
)

# The legacy Algorand WebSocket rail predates the admin table and never
# opens these, whatever it says: its attestation is optional for old
# clients. Whatever the table refuses, it refuses too.
_LEGACY_BLOCKED = frozenset({'US', 'KR', 'GB'})

LEGACY_PRESALE_POLICY = GeoPolicy(
    name='presale_legacy',
    phone_blocked=lambda: _LEGACY_BLOCKED | _restricted(),
    message=IP_BLOCK_MSG,
    phone_messages=_COPY,
    allow_missing_phone=True,
    ip_blocked=None,
    ip_fails_open_on_error=False,
    bypass=is_presale_test_account,
)


def check_legacy_presale_eligibility(user, client_ip: str | None = None, ip_country_hint: str | None = None):
    """check_presale_eligibility for the legacy rail: never opens a country."""
    decision = LEGACY_PRESALE_POLICY.evaluate(
        user, client_ip=client_ip, ip_country_hint=ip_country_hint)
    return decision.allowed, decision.message


def waitlist_country(user, client_ip: str | None = None, ip_country_hint: str | None = None) -> str | None:
    """The ISO-2 country whose waitlist this user may join, or None.

    Only for a user refused the purchase: their own country first (it is the
    one that has to open), else the IP country that refused them."""
    from security.geo import country_of
    from .models import PresaleCountryAccess as A

    if not WAITLIST_POLICY.evaluate(user, client_ip=client_ip, ip_country_hint=ip_country_hint).allowed:
        return None
    rules = country_rules()
    home = country_of(user)
    if home and rules.get(home) and rules[home].access == A.ACCESS_WAITLIST:
        return home
    ip_country = get_country_for_ip(client_ip, ip_country_hint)
    rule = rules.get(ip_country) if ip_country else None
    if rule and rule.access == A.ACCESS_WAITLIST:
        return ip_country
    return None


ACCESS_BUY = 'buy'
ACCESS_WAITLIST = 'waitlist'
ACCESS_BLOCKED = 'blocked'
#: What the US waitlist was called by builds from 2026-11-02, which know no
#: other waitlist value. The current app reads it as 'waitlist'.
ACCESS_US_WAITLIST_LEGACY = 'us_waitlist'


def waitlist_notice(country: str | None) -> str:
    return (f"La preventa aún no está abierta para residentes {residents_of(country)}. "
            "Únete a la lista de espera y te avisaremos si se abre.")


def presale_access(user, client_ip: str | None = None, ip_country_hint: str | None = None) -> dict:
    """What this user may do, for the app to show: buy, join a country
    waitlist, or nothing (with the refusal copy). The purchase and waitlist
    mutations re-check on their own; this only decides the screen."""
    from .models import PresaleCountryAccess as A
    ok, message = check_presale_eligibility(user, client_ip=client_ip, ip_country_hint=ip_country_hint)
    us = us_access()
    common = {'us_access': us, 'not_us_attestation_required': us != A.ACCESS_OPEN,
              'waitlist_country': None, 'waitlist_notice': None}
    if ok:
        return {'access': ACCESS_BUY, 'message': None, **common}
    country = waitlist_country(user, client_ip=client_ip, ip_country_hint=ip_country_hint)
    if country:
        access = ACCESS_US_WAITLIST_LEGACY if country == 'US' else ACCESS_WAITLIST
        return {**common, 'access': access, 'message': message,
                'waitlist_country': country, 'waitlist_notice': waitlist_notice(country)}
    return {'access': ACCESS_BLOCKED, 'message': message, **common}
