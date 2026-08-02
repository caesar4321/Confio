from __future__ import annotations

"""
Shared phone normalization utilities.

Goals:
- Canonicalize phone numbers to a stable key using numeric calling codes
  so ISO variations (e.g., US vs DO both +1) collapse to the same key.
- Be tolerant of inputs that provide either an ISO alpha-2 code ("US")
  or a calling code string ("+1" or "1").
"""

import logging
from typing import Optional
from .country_codes import COUNTRY_CODES

logger = logging.getLogger(__name__)

_ISO_TO_CC: dict[str, str] | None = None


def _get_iso_to_cc() -> dict[str, str]:
    global _ISO_TO_CC
    if _ISO_TO_CC is None:
        _ISO_TO_CC = {row[2].upper(): row[1] for row in COUNTRY_CODES if len(row) >= 3}
    return _ISO_TO_CC


def _resolve_calling_code(country: Optional[str]) -> str:
    cc_raw = (country or '').strip()
    if not cc_raw:
        return ''
    if cc_raw.startswith('+') or cc_raw.isdigit():
        return cc_raw.replace('+', '')
    cc = _get_iso_to_cc().get(cc_raw.upper(), '')
    return cc.replace('+', '') if cc else ''


def canonicalize_phone_digits(phone_number: str, country: Optional[str]) -> str:
    """Return canonical local digits for storage and duplicate checks.

    Rules:
    - Strip non-digits.
    - If the input includes the country calling code, remove it.
    - For Argentina (+54), collapse the optional mobile `9` variant after country
      code so `+54 9 223...` and `+54 223...` map to the same canonical digits.
    - Also tolerate a leading national trunk `0` for Argentina.
    """
    digits = ''.join(ch for ch in (phone_number or '') if ch.isdigit())
    calling_code = _resolve_calling_code(country)
    if calling_code and digits.startswith(calling_code) and len(digits) > len(calling_code) + 4:
        digits = digits[len(calling_code):]

    if calling_code == '54':
        if digits.startswith('0') and len(digits) >= 11:
            digits = digits[1:]
        if digits.startswith('9') and len(digits) >= 11:
            digits = digits[1:]

    return digits


def normalize_phone(phone_number: str, country: Optional[str]) -> str:
    """Normalize to canonical key "callingcode:localdigits".

    - phone_number: may include country code; non-digits ignored
    - country: ISO alpha-2 (e.g., "US") OR calling code string (e.g., "+1" or "1")

    Behavior:
    - Resolve `calling_code` from `country`.
    - If `digits` begins with `calling_code` and has plausible length beyond it,
      strip that prefix so the key is stable even if caller included the code.
    - Return e.g., "1:9293993619". If country cannot be resolved, return just digits.
    """
    digits = canonicalize_phone_digits(phone_number, country)
    calling_code = _resolve_calling_code(country)
    if calling_code:
        return f"{calling_code}:{digits}"
    return digits


def normalize_any_phone(full_phone: str) -> Optional[str]:
    """Normalize a composite phone string like "+1 929 399 3619" into canonical key.

    Returns None if digits are insufficient.
    """
    if not full_phone:
        return None
    digits = ''.join(ch for ch in full_phone if ch.isdigit())
    if not digits or len(digits) < 6:
        return None
    # Try split first 1..4 digits as calling code; prefer longer codes first
    for cc_len in (4, 3, 2, 1):
        if len(digits) > cc_len:
            cc = digits[:cc_len]
            rest = digits[cc_len:]
            # Validate against our table: exist any ISO with this code?
            try:
                # Build a set of numeric codes once
                if not hasattr(normalize_any_phone, '_NUM_CODES'):
                    normalize_any_phone._NUM_CODES = {row[1].replace('+', '') for row in COUNTRY_CODES if len(row) >= 2}
                valid_codes = normalize_any_phone._NUM_CODES
            except Exception:
                valid_codes = set()
            if cc in valid_codes and rest:
                return f"{cc}:{rest}"
    # Fallback: treat entire digits as local without code
    return digits


def phone_lookup_key(raw_phone: str) -> str:
    """The one canonical key a caller-supplied phone names, or ''.

    A recipient is identified by the FULL number — calling code plus
    subscriber digits — and nothing else. A partial number is not a weaker
    identifier, it is a different number: "3009998877" is a valid local
    number in the US, in Colombia, and elsewhere, so matching it would pick
    a country at random and pay whoever that landed on.

    Accepted, because all three carry the full number:

    - the canonical key "57:3132587634" (what the `phoneKey` GraphQL field
      and the transaction list hand the app),
    - E.164 "+573132587634", in any punctuation.

    Rejected (returns ''): bare local digits with no calling code. The
    caller gets a clean miss and the send fails loudly as "not registered",
    which is correct — we genuinely do not know who they meant.

    The key is built exactly the way `User.save()` builds the stored one:
    `normalize_phone(all_digits, calling_code)`, routed through
    `canonicalize_phone_digits`, so country quirks line up with storage —
    notably Argentina, where "+54 9 223 1234567" and the stored
    "54:2231234567" have to collapse to the same key.
    """
    raw = (raw_phone or '').strip()
    if not raw:
        return ''

    digits = ''.join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ''

    # The calling code the caller named. An explicit key is authoritative;
    # otherwise infer the split, which only a '+' prefix licenses.
    calling_code = ''
    if ':' in raw:
        cc, _, rest = raw.partition(':')
        cc_digits = ''.join(ch for ch in cc if ch.isdigit())
        rest_digits = ''.join(ch for ch in rest if ch.isdigit())
        if cc_digits and rest_digits:
            calling_code = cc_digits
    elif raw.startswith('+'):
        guess = normalize_any_phone(digits)
        if guess and ':' in guess:
            calling_code = guess.split(':', 1)[0]

    if not calling_code:
        return ''

    key = normalize_phone(digits, calling_code)
    return key if ':' in key else ''


def to_international(value: str = '', user=None) -> str:
    """The full international number ("+573132587634") for display and reuse.

    `SendTransaction.sender_phone`/`recipient_phone` store LOCAL digits — the
    columns are matched against elsewhere (send/schema.py, graphql_views.py),
    so their format is fixed. But a local number is not a number anyone can
    read, dial, or send to: it renders as "3132587634" with no country and
    resolves to nobody. Anything LEAVING the server for a client (notification
    payloads especially) should carry the full number instead.

    `user` wins when it has a usable key — it is the canonical record. A value
    that already names its country passes through. Bare digits with no user
    are returned unchanged: we cannot invent a country, and showing the local
    number beats showing nothing.
    """
    if user is not None:
        key = getattr(user, 'phone_key', '') or ''
        if ':' not in key:
            number = getattr(user, 'phone_number', '') or ''
            country = getattr(user, 'phone_country', '') or ''
            key = normalize_phone(number, country) if number else ''
        if ':' in key:
            cc, _, local = key.partition(':')
            return f'+{cc}{local}'

    raw = (value or '').strip()
    if not raw:
        return ''
    if ':' in raw:
        cc, _, local = raw.partition(':')
        cc_digits = ''.join(ch for ch in cc if ch.isdigit())
        local_digits = ''.join(ch for ch in local if ch.isdigit())
        if cc_digits and local_digits:
            return f'+{cc_digits}{local_digits}'
    if raw.startswith('+'):
        return '+' + ''.join(ch for ch in raw if ch.isdigit())
    return raw


def find_user_by_phone(raw_phone: str):
    """Resolve a Confío user from a FULL phone number (with calling code).

    Returns None when the input names no complete number, when nothing
    matches, or when the number is AMBIGUOUS. Duplicates are real: as of
    2026-08-01 production holds 10 active accounts on `1:2025550123` and 6 on
    `54:2025550123`. `phone_key` has no unique constraint in any migration,
    and production has no such index either — that is what lets those rows
    exist. Paying an arbitrary one of several matching users is worse than
    refusing.

    The one exception is the app-store REVIEWER number, shared by design:
    `is_review_test_phone_key` is what waives the duplicate check at phone
    verification, so every reviewer signup adds a row on the same key. Those
    are reserved-for-fiction numbers holding no real money, so they resolve
    deterministically by id instead of failing the reviewer's send.

    Callers surface a None as "not registered", the safe, loud failure.
    See `phone_lookup_key` for the shapes accepted.
    """
    from django.contrib.auth import get_user_model

    key = phone_lookup_key(raw_phone)
    if not key:
        if raw_phone:
            logger.warning(
                'phone lookup refused: %r carries no calling code', raw_phone)
        return None

    User = get_user_model()
    # Soft-deleted users are already excluded by the default manager;
    # deactivated ones are not, and their wallet should not receive.
    qs = User.objects.filter(is_active=True, phone_key=key)
    matches = list(qs.order_by('id')[:2])
    if len(matches) > 1:
        from .review_numbers import is_shared_reviewer_phone_key
        if is_shared_reviewer_phone_key(key):
            logger.info(
                'phone lookup: reviewer test key %r has multiple accounts, taking the first', key)
            return matches[0]
        logger.error('phone lookup refused: phone_key=%r matches multiple active users', key)
        return None
    return matches[0] if matches else None
