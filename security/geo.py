"""Geo-eligibility: one mechanism, one policy object per feature.

Two signals decide whether someone may ENTER a gated product: the country
their phone number was verified in, and the country their request appears to
come from. Before this module each feature wrote its own pair — presale in
`presale/geo_utils.py`, Ondo savings in `cusd_plus/eligibility.py` — and the
shared IP resolver lived inside presale, which cusd_plus imported across app
boundaries with a comment admitting it was a follow-up.

That cost us a real bug. Twelve call sites check the phone half ALONE. Most
are correct — a Celery scanner, a payroll recipient and a send recipient have
no request, so no IP exists to check. But `cusdPlusSummary.savingsEnabled`
had a request and still checked phone only, so the app told users behind a
blocked IP that they could save while the relay refused them, stranding
deposits. Nothing in the old API distinguished "partial on purpose" from
"partial by oversight": both called `is_ondo_eligible`.

So the two entry points here are named for what they actually do:

    POLICY.phone_eligible(user)          # explicitly the half-check
    POLICY.evaluate(user, meta=request)  # the full set

BEHAVIOUR IS PRESERVED EXACTLY, including where the two features disagree.
They are legal controls on a live token sale and a regulated issuer's
product, and a refactor is not the place to change either. The known
divergence — a user with NO phone country passes presale but fails Ondo —
is expressed by `allow_missing_phone` rather than left to fall out of one
being written as a blocklist and the other as an allowlist. It is now a
visible setting to decide on, not an accident.
"""
import ipaddress
import logging
from dataclasses import dataclass, field
from typing import Callable, Mapping

logger = logging.getLogger(__name__)


# ── IP resolution (moved verbatim from presale/geo_utils) ───────────────

def _is_public_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def phone_country_of(user) -> str:
    """The user's verified phone country, normalized the way BOTH features
    already did it: strip + upper, nothing more.

    Deliberately NOT `normalize_country` — that rejects anything not exactly
    two characters, which would turn malformed data into a refusal. Stricter
    is arguably right for a regulated gate, but it is a policy change, not a
    refactor, so it stays a separate decision.
    """
    return (getattr(user, 'phone_country', None) or '').strip().upper()


def normalize_country(code) -> str | None:
    """Upper-cased ISO-3166 alpha-2, or None for unknowns.
    Cloudflare uses 'XX' for unknown and 'T1' for Tor."""
    if not code:
        return None
    code = str(code).strip().upper()
    if len(code) != 2 or code in ('XX', 'T1'):
        return None
    return code


def get_country_for_ip(client_ip: str | None, header_country: str | None = None) -> str | None:
    """Resolve the ISO country for a request. Cheap paths first: the
    Cloudflare edge header, then the cached security.IPAddress row, then a
    live ipapi.co lookup which is written back as the cache."""
    country = normalize_country(header_country)
    if country:
        return country

    if not client_ip or not _is_public_ip(client_ip):
        return None

    try:
        from security.models import IPAddress
        row = IPAddress.objects.filter(ip_address=client_ip).only('country_code').first()
        if row and row.country_code:
            return normalize_country(row.country_code)
    except Exception:  # noqa: BLE001
        pass

    try:
        import requests
        response = requests.get(
            f'https://ipapi.co/{client_ip}/json/',
            timeout=4,
            headers={'User-Agent': 'Confio Security/1.0'},
        )
        if response.status_code == 200:
            data = response.json()
            country = normalize_country(data.get('country_code'))
            if country:
                try:
                    from security.models import IPAddress
                    IPAddress.objects.update_or_create(
                        ip_address=client_ip,
                        defaults={
                            'country_code': country,
                            'country_name': (data.get('country_name') or '')[:100],
                        },
                    )
                except Exception:  # noqa: BLE001
                    pass
                return country
    except Exception as exc:  # noqa: BLE001
        logger.info('[GEO] live IP lookup failed for %s: %s', client_ip, exc)

    return None


def country_for_request(meta: Mapping | None) -> str | None:
    """IP country from a request's META, Cloudflare header first."""
    meta = meta or {}
    from security.request_utils import extract_client_ip_from_meta
    return get_country_for_ip(
        extract_client_ip_from_meta(meta), meta.get('HTTP_CF_IPCOUNTRY'))


# ── Policy ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GeoDecision:
    allowed: bool
    message: str | None = None
    #: 'phone' | 'ip' | None — which signal refused, for logs and support.
    blocked_by: str | None = None

    def __bool__(self) -> bool:
        return self.allowed


@dataclass(frozen=True)
class GeoPolicy:
    """One feature's geo rules. The mechanism above is shared; this is not."""

    name: str
    #: Phone countries refused outright.
    phone_blocked: frozenset
    #: Default refusal copy, shown to the user.
    message: str
    #: Per-country copy overrides (presale says something different for KR).
    phone_messages: Mapping[str, str] = field(default_factory=dict)
    #: A user with NO verified phone country. Ondo fails CLOSED (it cannot
    #: attest a jurisdiction); presale falls through to eligible. Preserved
    #: from each feature's original behaviour — see the module docstring.
    allow_missing_phone: bool = False
    #: IP countries refused. None means "same list as phone_blocked" (Ondo);
    #: a callable is read at CALL time so a Django setting stays live
    #: (presale reads PRESALE_IP_BLOCKED_COUNTRIES).
    ip_blocked: frozenset | Callable[[], object] | None = None
    #: An unresolvable IP already yields None and is allowed. This covers a
    #: RAISE during resolution: Ondo swallows it (an outage must not strand an
    #: attested-eligible user), presale lets it propagate.
    ip_fails_open_on_error: bool = True
    #: Escape hatch evaluated before everything (store-review accounts).
    bypass: Callable[[object], bool] | None = None

    # -- the half-check, named so its partiality is visible at the call site
    def phone_eligible(self, user) -> bool:
        """Phone country ONLY. Correct where no request exists (Celery, a
        recipient's eligibility); everywhere else prefer `evaluate`."""
        if self.bypass is not None and self.bypass(user):
            return True
        country = phone_country_of(user)
        if not country:
            return self.allow_missing_phone
        return country not in self.phone_blocked

    # -- the full set
    def evaluate(self, user, meta: Mapping | None = None, *,
                 client_ip: str | None = None,
                 ip_country_hint: str | None = None) -> GeoDecision:
        """Both signals. Pass a request's META, or an explicit ip/hint for
        callers without one (websocket consumers)."""
        if self.bypass is not None and self.bypass(user):
            return GeoDecision(True)

        country = phone_country_of(user)
        if not country:
            if not self.allow_missing_phone:
                return GeoDecision(False, self.message, 'phone')
        elif country in self.phone_blocked:
            return GeoDecision(
                False, self.phone_messages.get(country, self.message), 'phone')

        blocked = self.ip_blocked
        if callable(blocked):
            blocked = blocked()
        if blocked is None:
            blocked = self.phone_blocked
        if not blocked:
            return GeoDecision(True)

        try:
            if meta is not None:
                ip_country = country_for_request(meta)
            else:
                ip_country = get_country_for_ip(client_ip, ip_country_hint)
        except Exception:  # noqa: BLE001
            if self.ip_fails_open_on_error:
                return GeoDecision(True)
            raise

        if ip_country is not None and ip_country in blocked:
            logger.warning(
                '[GEO][%s] blocked by IP country=%s user_id=%s',
                self.name, ip_country, getattr(user, 'id', None))
            return GeoDecision(False, self.message, 'ip')
        return GeoDecision(True)
