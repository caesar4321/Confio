from __future__ import annotations

from functools import lru_cache
from typing import Iterable

from django.conf import settings

from .phone_utils import normalize_any_phone


def _configured_review_numbers() -> Iterable[str]:
	"""Return the raw E.164 numbers configured for reviewer testing."""
	if not getattr(settings, 'REVIEW_TEST_ENABLED', False):
		return []

	phones = []
	for attr in ('REVIEW_TEST_PHONE_E164', 'REVIEW_TEST_PHONE_E164_2'):
		value = getattr(settings, attr, None)
		if value:
			phones.append(value.strip())
	return phones


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
