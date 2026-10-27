from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, List, Tuple

from django.conf import settings

from .country_codes import COUNTRY_CODES
from .phone_utils import normalize_any_phone


# Calling codes shared by several countries: the country a reviewer number
# stands for. COUNTRY_CODES lists +1 under American Samoa first.
_HOME_COUNTRY = {'+1': 'US', '+44': 'GB', '+7': 'RU'}


@dataclass(frozen=True)
class ReviewNumber:
	phone: str        # E.164
	code: str
	country: str      # ISO-2 stored as the account's phone country
	geo_exempt: bool  # bypasses every phone-country and IP block


def _country_of(phone: str) -> str | None:
	normalized = normalize_any_phone(phone)
	if not normalized:
		return None
	calling_code = '+' + normalized.split(':', 1)[0]
	if calling_code in _HOME_COUNTRY:
		return _HOME_COUNTRY[calling_code]
	return next((row[2] for row in COUNTRY_CODES if row[1] == calling_code), None)


def review_numbers() -> List[ReviewNumber]:
	"""Every configured reviewer number, one store's code each.

	Code 1 is Apple's, code 2 Google Play's. REVIEW_TEST_PHONE_E164[_2] are
	the geo-exempt numbers (Argentina): a reviewer sees every feature from
	anywhere. REVIEW_TEST_GEO_BLOCKED_PHONES_E164[_2] are numbers in blocked
	countries (US, UK) with no bypass at all, so a reviewer who signs up with
	one, or switches to it, sees the blocks a real user there gets.
	"""
	if not getattr(settings, 'REVIEW_TEST_ENABLED', False):
		return []

	numbers: List[ReviewNumber] = []
	for suffix in ('', '_2'):
		code = getattr(settings, f'REVIEW_TEST_CODE{suffix}', None)
		if not code:
			continue
		code = str(code).strip()
		phones = [(getattr(settings, f'REVIEW_TEST_PHONE_E164{suffix}', None), True)]
		blocked = getattr(settings, f'REVIEW_TEST_GEO_BLOCKED_PHONES_E164{suffix}', None) or ()
		if isinstance(blocked, str):
			blocked = blocked.split(',')
		phones += [(phone, False) for phone in blocked]
		for phone, geo_exempt in phones:
			phone = (phone or '').strip()
			country = _country_of(phone) if phone else None
			if country:
				numbers.append(ReviewNumber(phone, code, country, geo_exempt))
	return numbers


def review_test_pairs() -> List[Tuple[str, str]]:
	"""Return (phone_e164, code) tuples for configured reviewer phones."""
	return [(number.phone, number.code) for number in review_numbers()]


def review_number_for_key(phone_key: str | None) -> ReviewNumber | None:
	"""The configured reviewer number behind a canonical phone key."""
	if not phone_key:
		return None
	return next((number for number in review_numbers()
	             if normalize_any_phone(number.phone) == phone_key), None)


def is_geo_exempt_reviewer(user) -> bool:
	"""True for accounts on a geo-exempt reviewer number (see review_numbers)."""
	number = review_number_for_key(getattr(user, 'phone_key', None))
	return bool(number and number.geo_exempt)


def get_review_test_code_for_phone(phone_e164: str | None) -> str | None:
	"""Return the configured code for a review test phone, if any."""
	if not phone_e164:
		return None
	for review_phone, review_code in review_test_pairs():
		if review_phone == phone_e164:
			return review_code
	return None


def _configured_review_numbers() -> Iterable[str]:
	"""Return the raw E.164 numbers configured for reviewer testing."""
	return [phone for phone, _ in review_test_pairs()]


# Reviewer numbers this mechanism has used over time. `+12025550123` is the
# built-in default of REVIEW_TEST_PHONE_E164 (config/settings.py) and was the
# live value before prod's .env moved to +54, which is why production carries
# 10 active accounts on `1:2025550123` alongside 6 on `54:2025550123`.
#
# They stay recognized for as long as those rows exist. All of them sit in the
# NANP 555-01XX range, permanently reserved for fictional use, so no real
# person can ever hold one — recognizing them can never shadow a real user.
_RESERVED_REVIEW_PHONES: tuple[str, ...] = ('+12025550123',)


@lru_cache(maxsize=1)
def _review_phone_keys() -> set[str]:
	"""Cache canonical phone keys derived from configured review numbers."""
	keys: set[str] = set()
	for phone in _configured_review_numbers():
		normalized = normalize_any_phone(phone)
		if normalized:
			keys.add(normalized)
	return keys


@lru_cache(maxsize=1)
def _shared_reviewer_phone_keys() -> set[str]:
	"""Keys that legitimately map to SEVERAL accounts.

	The reviewer number is shared on purpose: `is_review_test_phone_key` is
	what waives the duplicate check at phone verification (sms_verification/
	schema.py), so every reviewer signup adds another row on the same key.

	Deliberately WIDER than `_review_phone_keys()` and independent of
	REVIEW_TEST_ENABLED: those rows exist in the database whether or not the
	feature is currently on, and a lookup still has to decide what to do with
	them. Deliberately NOT wired into the code bypass — a number here without
	a configured code still cannot verify, so this grants no way in.
	"""
	keys = set(_review_phone_keys())
	for phone in _RESERVED_REVIEW_PHONES:
		normalized = normalize_any_phone(phone)
		if normalized:
			keys.add(normalized)
	return keys


def is_shared_reviewer_phone_key(phone_key: str | None) -> bool:
	"""True when a key is shared by reviewer accounts by design, so resolving
	it to one of them is expected rather than an ambiguity to refuse."""
	if not phone_key:
		return False
	return phone_key in _shared_reviewer_phone_keys()


def is_review_test_phone_key(phone_key: str | None) -> bool:
	"""Return True when the canonical phone key belongs to reviewer test data."""
	if not phone_key:
		return False
	return phone_key in _review_phone_keys()


def is_review_test_phone_e164(phone_e164: str | None) -> bool:
	"""Return True when the E.164 number belongs to reviewer test data."""
	if not phone_e164:
		return False
	normalized = normalize_any_phone(phone_e164)
	if not normalized:
		return False
	return normalized in _review_phone_keys()


def find_matching_review_number(phone_input: str) -> str | None:
	"""
	Fuzzy match the input phone string against configured review numbers.
	
	If the digits of `phone_input` exactly match or are a suffix of a configured
	review number (and satisfy minimal length), return the configured E.164 number.
	This handles cases where the user/reviewer selects the wrong country code
	but enters the correct test digits.
	"""
	import re
	if not phone_input:
		return None
		
	# extract all digits
	input_digits = re.sub(r'\D', '', phone_input)
	if not input_digits:
		return None
		
	suffix_matches = []
	for review_phone, _ in review_test_pairs():
		# review_phone is expected to be E.164 (e.g. +12025550123)
		review_digits = re.sub(r'\D', '', review_phone)

		# 1. Exact digit match
		if input_digits == review_digits:
			return review_phone

		# 2. Suffix match (Input is missing country code, but reviewer entered the full national number)
		# We require at least 10 digits to avoid false positives.
		# The test number is 12025550123 (11 digits).
		if len(input_digits) >= 10 and review_digits.endswith(input_digits):
			suffix_matches.append(review_phone)

	# Several reviewer numbers share a national number only by misconfiguration;
	# never guess which country (and which geo rules) the reviewer meant.
	return suffix_matches[0] if len(set(suffix_matches)) == 1 else None
