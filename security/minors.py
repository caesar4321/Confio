"""Known minors: who they are, and the one refusal every gated action uses.

Policy ("Confío Minimum Age and Minors Policy", section 5, 2026-11-03):

- Identity verification is adults only (Didit "Confio General KYC + AML" v3
  declines every country under 18, before the selfie).
- A KNOWN minor is a person whose date of birth on file says under 18 today:
  their current verified document first (security.identity_status, the same
  document Comprar reads); without one, ANY decided attempt (verified,
  rejected, expired), because a rejected attempt keeps the OCR'd birth date
  (security/didit.py writes extracted fields on every decision). Attempts
  that never reached OCR carry PLACEHOLDER_BIRTH_DATE and never count.
- No birth date on file: never restricted here; the Terms' 18+ clause covers
  them.
- The limit lifts by itself on the 18th birthday. "Today" is the furthest-
  west date on Earth (UTC-12): one country can span several time zones, so
  this is the only date at which the birthday never arrives early. It can
  lift up to a day late, never early.
- Refused at the moment of the action, server-side: fiat ramps (Koywe,
  Transak, Guardarian), Cobre and Infinia local accounts and payments, VEXPay
  Pago Móvil, Bolivia QR (Mesa de Pagos), Confío Dollar+ and stock
  purchases, Futuros opens and the $CONFIO presale. Holding, Confío-to-Confío
  sends, QR payments, payroll receipts, USDT BEP-20, Emergency Exit and every
  EXIT (redeeming Dollar+, selling stocks, closing futures) stay open.

Under-the-country-minimum documents never get here: Didit's KYC workflow
declines them before the selfie (workflow v2, route_age).
"""
from __future__ import annotations

from datetime import date

ADULT_AGE = 18

# Approved by Julian 2026-11-03 ("Disponible desde los 18").
MINOR_MESSAGE = 'Esta función estará disponible cuando cumplas 18 años.'

# Machine-readable code for callers that return codes instead of copy.
MINOR_CODE = 'minor_restricted'

_CACHE_ATTR = '_confio_verified_age_cache'


def age_on(born: date | None, today: date) -> int | None:
    """Whole years between `born` and `today`, or None without a birth date."""
    if born is None:
        return None
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def local_today(country_code: str | None) -> date:
    """Today's date in that country; an unknown country takes the
    furthest-west date, so a birthday never arrives early."""
    from zoneinfo import ZoneInfo

    from django.utils import timezone
    from users.cashflow import TIMEZONE_BY_PHONE_COUNTRY

    name = TIMEZONE_BY_PHONE_COUNTRY.get((country_code or '').upper(), 'Etc/GMT+12')
    return timezone.now().astimezone(ZoneInfo(name)).date()


def verified_age(user, today: date) -> int | None:
    """Whole years since the birth date on the person's current verified
    document (primary first), or None when there is none."""
    from security.identity_status import current_document

    doc = current_document(user)
    return age_on(getattr(doc, 'verified_date_of_birth', None), today)


DECIDED_STATUSES = ('verified', 'rejected', 'expired')


def _identity_model():
    from security.models import IdentityVerification
    return IdentityVerification


def known_age(user, today: date) -> int | None:
    """The current verified document's age; without one, the YOUNGEST age any
    decided attempt shows (a rejected minor must not pass as unknown)."""
    from security.didit import PLACEHOLDER_BIRTH_DATE
    from security.identity_status import PERSONAL, current_document

    doc = current_document(user)
    born = getattr(doc, 'verified_date_of_birth', None)
    if born is not None and born != PLACEHOLDER_BIRTH_DATE:
        return age_on(born, today)
    # Every decided row, soft-deleted ones too: a deleted attempt still
    # recorded the birth date it read.
    births = (_identity_model().all_objects.filter(user=user).filter(PERSONAL)
              .filter(status__in=DECIDED_STATUSES, verified_date_of_birth__isnull=False)
              .exclude(verified_date_of_birth=PLACEHOLDER_BIRTH_DATE)
              .values_list('verified_date_of_birth', flat=True))
    ages = [age_on(born, today) for born in births]
    return min(ages) if ages else None


def is_known_minor(user) -> bool:
    """True for a person whose birth date on file says under 18 today in
    their own country. No birth date on file is NOT a minor.

    Memoized on the user object for the current date: one request evaluates
    several policies (Ondo, perps, stock buys) for the same person."""
    # A saved User only: unsaved and stand-in users (anonymous, namespaces,
    # mocks) have no verified document to read.
    from django.contrib.auth import get_user_model
    if not isinstance(user, get_user_model()) or not isinstance(user.pk, int):
        return False
    today = local_today(None)  # furthest-west date: never early
    cached = getattr(user, _CACHE_ATTR, None)
    if cached is not None and cached[0] == today:
        age = cached[1]
    else:
        age = known_age(user, today)
        try:
            setattr(user, _CACHE_ATTR, (today, age))
        except AttributeError:  # pragma: no cover - slotted/proxy objects
            pass
    return age is not None and age < ADULT_AGE


def minor_refusal(user) -> str | None:
    """MINOR_MESSAGE when this action is closed to the person, else None."""
    return MINOR_MESSAGE if is_known_minor(user) else None
