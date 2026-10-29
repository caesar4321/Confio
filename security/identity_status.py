"""Who is verified: the one answer every caller asks.

A person can hold several personal documents: the primary one (from the
general Didit workflow: any country's ID, passport or residence permit) and
additional ones (another country's document, verified to open a local-money
rail). The default manager hides additional documents on purpose; plain "is
this person verified" questions read every document through the helpers
below. So:

- is_identity_verified: "Identidad verificada". Any CURRENT verified personal
  document, primary or additional. Badges, gates, profile, counts.
- rail_identity / has_rail_identity: a document ISSUED by one rail country,
  primary or additional. Issued, not "naming it as nationality or residence":
  a Colombian national's Peruvian residence permit would otherwise go to a
  Colombian order as a Colombian document. Read where a provider needs that country's document
  (Koywe's delegated KYC behind Recargar/Retirar). Until 2026-10 this was
  "the primary document", which matched the phone country only because the
  per-country Didit workflows forced it to.
- has_ever_passed_kyc: verified now or verified and later expired. Security
  links that exist because someone went through KYC (Confío Face, bans,
  same-person checks) — an expiring document never switches them off.
- identity_status / verified_at: what the app shows.
- is_business_verified: KYB, a different question (business-context rows).

Business-context rows (risk_factors.account_type='business') never count as a
person's KYC. The personal filter is null-safe: personal rows carry no
account_type key, and `.exclude(risk_factors__account_type='business')` drops
them (NOT (NULL = 'business') is NULL).
"""
from django.db.models import Q

from .models import PASSED_KYC, IdentityVerification

PERSONAL = Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business')
# Primary first, then the newest: the document that "is" the person when one is needed.
DOCUMENT_ORDER = ('is_additional_document', '-verified_at', '-updated_at', '-created_at')


def personal_documents(user):
    """Every personal document, additional ones included, any status."""
    return IdentityVerification.all_documents.filter(user=user).filter(PERSONAL)


def current_documents(user):
    """Verified personal documents, primary first."""
    return personal_documents(user).filter(status='verified').order_by(*DOCUMENT_ORDER)


def current_document(user):
    return current_documents(user).first()


def is_identity_verified(user) -> bool:
    return current_documents(user).exists()


def rail_identity(user, country=None):
    """A current verified document issued by `country` (ISO-2 or ISO-3;
    default: their primary rail country, ramps.rail_country), or None.
    National IDs and residence permits come before passports: most rails
    (Koywe outside Colombia) refuse a passport, and a person holding both
    should never be sent with the one that fails."""
    from security.geo import to_iso3
    code = str(country or '').strip().upper()
    if not code:
        from ramps.rail_country import primary_rail_country
        code = primary_rail_country(user) or ''
    iso3 = code if len(code) == 3 else to_iso3(code)
    if not iso3:
        return None
    matches = [doc for doc in current_documents(user).filter(document_issuing_country__iexact=iso3)
               if rail_accepts_document(iso3, doc.document_type)]
    return matches[0] if matches else None


# Koywe (ramps/koywe_client.py _resolve_document_type) takes a passport only
# for Colombia; everywhere else it needs the national ID or a residence permit.
PASSPORT_RAIL_COUNTRIES = frozenset({'COL'})


def rail_accepts_document(iso3: str, document_type) -> bool:
    is_passport = str(document_type or '').strip().lower() in ('passport', 'p')
    return not is_passport or str(iso3 or '').upper() in PASSPORT_RAIL_COUNTRIES


def has_rail_identity(user, country=None) -> bool:
    return rail_identity(user, country) is not None


def verified_document_countries(user) -> list[str]:
    """ISO-2 countries whose Recargar/Retirar rail accepts one of the person's
    current verified documents (a passport counts only where the rail takes
    one, rail_accepts_document), primary first."""
    from security.geo import to_iso2
    countries = []
    for issuing, document_type in current_documents(user).values_list('document_issuing_country', 'document_type'):
        if not rail_accepts_document(issuing, document_type):
            continue
        iso2 = to_iso2(issuing)
        if iso2 and iso2 not in countries:
            countries.append(iso2)
    return countries


def has_ever_passed_kyc(user) -> bool:
    return personal_documents(user).filter(PASSED_KYC).exists()


def identity_status(user) -> str:
    """verified > pending > rejected > unverified, over every personal document."""
    statuses = set(personal_documents(user).values_list('status', flat=True))
    for status in ('verified', 'pending', 'rejected'):
        if status in statuses:
            return status
    return 'unverified'


def verified_at(user):
    document = current_documents(user).order_by('-verified_at', '-updated_at', '-created_at').first()
    if not document:
        return None
    return document.verified_at or document.updated_at or document.created_at


def verified_document_of_country(user, country):
    """A current personal document tying the person to `country` (alpha-3):
    issued there, or naming it as nationality or residence."""
    country = (country or '').strip().upper()
    if not country:
        return None
    return current_documents(user).filter(
        Q(verified_country__iexact=country)
        | Q(verified_nationality__iexact=country)
        | Q(document_issuing_country__iexact=country)
    ).first()


def verified_user_ids(user_ids=None):
    """Users with a current verified personal document (distinct ids)."""
    rows = IdentityVerification.all_documents.filter(status='verified').filter(PERSONAL)
    if user_ids is not None:
        rows = rows.filter(user_id__in=user_ids)
    return rows.values_list('user_id', flat=True).distinct()


def business_kyb(business_id):
    if not business_id:
        return None
    return IdentityVerification.objects.filter(
        status='verified', risk_factors__account_type='business', risk_factors__business_id=str(business_id),
    ).order_by('-verified_at', '-updated_at', '-created_at').first()


def is_business_verified(business_id) -> bool:
    return business_kyb(business_id) is not None


def business_status(business_id) -> str:
    """verified > pending > rejected > unverified, over the business's KYB rows."""
    if not business_id:
        return 'unverified'
    statuses = set(IdentityVerification.objects.filter(
        risk_factors__account_type='business', risk_factors__business_id=str(business_id),
    ).values_list('status', flat=True))
    for status in ('verified', 'pending', 'rejected'):
        if status in statuses:
            return status
    return 'unverified'
