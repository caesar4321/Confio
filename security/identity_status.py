"""Who is verified: the one answer every caller asks.

A person can hold several personal documents: the primary one (their phone
country's, the one Didit's per-country workflow asks for) and additional ones
(a passport or ID from another country, verified to open a local-money rail).
The default manager hides additional documents on purpose; that is right for
the few providers that need the phone-country document and wrong for every
plain "is this person verified" question. So:

- is_identity_verified: "Identidad verificada". Any CURRENT verified personal
  document, primary or additional. Badges, gates, profile, counts.
- has_phone_country_identity / phone_country_identity: only the primary
  document. Read ONLY where a provider requires the phone-country document
  (Koywe's delegated KYC behind Recargar/Retirar).
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


def phone_country_identity(user):
    """The verified primary (phone-country) document, or None."""
    return (
        IdentityVerification.objects.filter(user=user, status='verified').filter(PERSONAL)
        .order_by('-verified_at', '-updated_at', '-created_at').first()
    )


def has_phone_country_identity(user) -> bool:
    return phone_country_identity(user) is not None


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
