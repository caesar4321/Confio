"""Which country's rails a user sees first in Recibir/Enviar.

The phone prefix used to decide this alone. Without a phone, and with people
who live in one country and hold another's documents, the answer is an
ORDER, not a single country:

1. the country they last picked in the rail list (`preferred_rail_country`);
2. where they live (`security.geo.country_of`): a QR is paid where you are;
3. countries of their verified Didit documents: the primary first, then
   additional ones, newest first;
4. the device's region, when the client sends it.

The first entry is "their" rail country wherever one country is needed
(Bolivia QR, Koywe defaults). Lists of rails still show every country; this
only decides what comes first.
"""
from security.geo import country_of, normalize_country, to_iso2


def _document_countries(user) -> list[str]:
    from django.contrib.auth import get_user_model
    if not isinstance(user, get_user_model()) or not user.pk:
        return []
    from security.identity_status import current_documents
    countries = []
    for issuing in current_documents(user).values_list('document_issuing_country', flat=True):
        iso2 = to_iso2(issuing)
        if iso2:
            countries.append(iso2)
    return countries


def _text(value) -> str | None:
    return value if isinstance(value, str) else None


def rail_countries(user, device_region: str | None = None) -> list[str]:
    if not user:
        return []
    ordered = [
        normalize_country(_text(getattr(user, 'preferred_rail_country', None))),
        normalize_country(country_of(user)),
        *_document_countries(user),
        normalize_country(device_region),
    ]
    seen, result = set(), []
    for country in ordered:
        if country and country not in seen:
            seen.add(country)
            result.append(country)
    return result


def primary_rail_country(user) -> str | None:
    countries = rail_countries(user)
    return countries[0] if countries else None


def is_real_country(code) -> bool:
    country = normalize_country(code)
    if not country:
        return False
    import pycountry
    return pycountry.countries.get(alpha_2=country) is not None
