from __future__ import annotations

"""
Shared phone normalization utilities.

Goals:
- Canonicalize phone numbers to a stable key using numeric calling codes
  so ISO variations (e.g., US vs DO both +1) collapse to the same key.
- Be tolerant of inputs that provide either an ISO alpha-2 code ("US")
  or a calling code string ("+1" or "1").
"""

from typing import Optional
from .country_codes import COUNTRY_CODES

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
