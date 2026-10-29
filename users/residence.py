"""Where a user lives: the writes behind `User.country`.

Signup stopped asking for a phone in 2026-10, so the phone prefix can no
longer say where someone is. `User.country` holds it instead, read through
`security.geo.country_of`:

- login: an account with no country yet takes the request's IP country;
- daily: `refresh_residence_country` replaces it with the IP majority of the
  last 90 days (`security.geo.residence_country_for`) once there is one;
- backfill: accounts from before the column take their residence, else the
  phone country they verified.

None of these ever writes null over a known country: "we could not tell
today" is not "they live nowhere". Store-review accounts (country_source
'review') are left alone; the review link owns them.
"""
import logging
from typing import Mapping

from django.utils import timezone

from security.geo import get_country_for_ip, normalize_country, residence_country_for, to_iso2

logger = logging.getLogger(__name__)


def _write(user, country: str, source: str) -> bool:
    if user.country == country and user.country_source == source:
        return False
    user.country = country
    user.country_source = source
    user.country_updated_at = timezone.now()
    user.save(update_fields=['country', 'country_source', 'country_updated_at'])
    return True


def _request_ip_country(meta: Mapping | None) -> str | None:
    """The request's IP country. The CF-IPCountry header counts only on a
    request that really came through Cloudflare: this value is stored and
    gates regulated products, so a header forged on a direct-origin request
    must not become someone's country."""
    from security.request_utils import came_through_cloudflare, extract_client_ip_from_meta
    meta = meta or {}
    header = meta.get('HTTP_CF_IPCOUNTRY') if came_through_cloudflare(meta) else None
    return get_country_for_ip(extract_client_ip_from_meta(meta), header)


def set_country_from_request(user, meta: Mapping | None) -> bool:
    """First known country for an account that has none. An account from the
    phone era takes its backfill answer (residence, else the verified phone
    country) so a login never replaces a verified phone country with
    whatever IP this one request came from; only a phone-less account takes
    the request's IP. Never overrides an existing country: the daily
    residence refresh is what moves people."""
    if getattr(user, 'country', None):
        return False
    if normalize_country(getattr(user, 'phone_country', None)):
        return backfill_country(user)
    try:
        country = normalize_country(_request_ip_country(meta))
    except Exception:  # noqa: BLE001 — a lookup failure must not break login
        logger.exception('[RESIDENCE] IP country lookup failed user_id=%s', getattr(user, 'id', None))
        return False
    if not country:
        return False
    return _write(user, country, user.COUNTRY_SOURCE_SIGNUP_IP)


def _pin_review_number(user) -> bool | None:
    """A store-review number stands for its country (users/review_numbers.py):
    pin it, whatever the reviewer's IP says. None when not a review number."""
    from users.review_numbers import review_number_for_key
    number = review_number_for_key(getattr(user, 'phone_key', None))
    if not number:
        return None
    return _write(user, number.country, user.COUNTRY_SOURCE_REVIEW)


def refresh_residence_country(user) -> bool:
    """Move the user to their 90-day IP majority country when there is one."""
    from users.review_access import active_review_access
    if active_review_access(user):
        # A live review-link grant outranks everything, a reviewer number too.
        return False
    pinned = _pin_review_number(user)
    if pinned is not None:
        return pinned
    if user.country_source == user.COUNTRY_SOURCE_REVIEW:
        return _restore_after_review(user)
    country = to_iso2(residence_country_for(user))
    if not country:
        return False
    return _write(user, country, user.COUNTRY_SOURCE_RESIDENCE)


def _restore_after_review(user) -> bool:
    """The review link's grant ended (expired, superseded with nothing after
    it, or the token cleared): give the account back its country. Locked and
    rechecked, so a grant issued meanwhile (users.review_access holds the same
    row lock) is never overwritten."""
    from django.db import transaction
    from users.review_access import active_review_access, latest_review_access
    with transaction.atomic():
        user = type(user).objects.select_for_update().get(pk=user.pk)
        if user.country_source != user.COUNTRY_SOURCE_REVIEW or active_review_access(user):
            return False
        country = to_iso2(residence_country_for(user))
        if country:
            return _write(user, country, user.COUNTRY_SOURCE_RESIDENCE)
        last = latest_review_access(user)
        before = getattr(last, 'country_before_review', None)
        if before:
            return _write(user, before, getattr(last, 'source_before_review', '') or user.COUNTRY_SOURCE_SIGNUP_IP)
        user.country, user.country_source, user.country_updated_at = None, '', timezone.now()
        user.save(update_fields=['country', 'country_source', 'country_updated_at'])
        return True


def backfill_country(user) -> bool:
    """One-time seed for accounts created before `User.country` existed."""
    if user.country:
        return False
    pinned = _pin_review_number(user)
    if pinned is not None:
        return pinned
    country = to_iso2(residence_country_for(user))
    if country:
        return _write(user, country, user.COUNTRY_SOURCE_RESIDENCE)
    legacy = normalize_country(user.phone_country)
    if legacy:
        return _write(user, legacy, user.COUNTRY_SOURCE_LEGACY_PHONE)
    return False
