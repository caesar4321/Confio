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


def _is_public_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def _normalize_country(code) -> str | None:
    """Return an upper-cased ISO-3166 alpha-2 code, or None for unknowns.
    Cloudflare uses 'XX' for unknown and 'T1' for Tor."""
    if not code:
        return None
    code = str(code).strip().upper()
    if len(code) != 2 or code in ('XX', 'T1'):
        return None
    return code


def get_country_for_ip(client_ip: str | None, header_country: str | None = None) -> str | None:
    """Resolve the ISO country for a request. Cheap paths first."""
    country = _normalize_country(header_country)
    if country:
        return country

    if not client_ip or not _is_public_ip(client_ip):
        return None

    try:
        from security.models import IPAddress
        row = IPAddress.objects.filter(ip_address=client_ip).only('country_code').first()
        if row and row.country_code:
            return _normalize_country(row.country_code)
    except Exception:
        row = None

    # Last resort: live lookup (same free service the security middleware
    # uses manually), persisted back onto the IPAddress row as a cache.
    try:
        import requests
        response = requests.get(
            f'https://ipapi.co/{client_ip}/json/',
            timeout=4,
            headers={'User-Agent': 'Confio Security/1.0'},
        )
        if response.status_code == 200:
            data = response.json()
            country = _normalize_country(data.get('country_code'))
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
                except Exception:
                    pass
                return country
    except Exception as e:
        logger.info(f"[PRESALE][GEO] live IP lookup failed for {client_ip}: {e}")

    return None


def check_presale_eligibility(user, client_ip: str | None = None, ip_country_hint: str | None = None):
    """
    Check presale eligibility by phone country and (when available) IP country.
    Returns: (is_eligible: bool, error_message: str|None)
    """
    if is_presale_test_account(user):
        return True, None

    code = getattr(user, 'phone_country', None)
    if code == 'US':
        return False, US_BLOCK_MSG
    if code == 'KR':
        return False, KR_BLOCK_MSG

    blocked_countries = getattr(settings, 'PRESALE_IP_BLOCKED_COUNTRIES', ['US'])
    if blocked_countries:
        ip_country = get_country_for_ip(client_ip, ip_country_hint)
        if ip_country in blocked_countries:
            logger.warning(
                f"[PRESALE][GEO] blocked by IP country={ip_country} ip={client_ip} user_id={getattr(user, 'id', None)}"
            )
            return False, US_BLOCK_MSG

    return True, None
