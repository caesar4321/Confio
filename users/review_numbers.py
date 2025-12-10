from __future__ import annotations

from functools import lru_cache
from typing import Iterable, List, Tuple

from django.conf import settings

from .phone_utils import normalize_any_phone


def review_test_pairs() -> List[Tuple[str, str]]:
	"""Return (phone_e164, code) tuples for configured reviewer phones."""
	if not getattr(settings, 'REVIEW_TEST_ENABLED', False):
		return []

	pairs: List[Tuple[str, str]] = []
	config = (
		('REVIEW_TEST_PHONE_E164', 'REVIEW_TEST_CODE'),
		('REVIEW_TEST_PHONE_E164_2', 'REVIEW_TEST_CODE_2'),
	)
	for phone_attr, code_attr in config:
		phone = getattr(settings, phone_attr, None)
		code = getattr(settings, code_attr, None)
		if phone and code:
			pairs.append((phone.strip(), str(code).strip()))
	return pairs


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


@lru_cache(maxsize=1)
def _review_phone_keys() -> set[str]:
	"""Cache canonical phone keys derived from configured review numbers."""
	keys: set[str] = set()
	for phone in _configured_review_numbers():
		normalized = normalize_any_phone(phone)
		if normalized:
			keys.add(normalized)
	return keys


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
			return review_phone
			
	return None
