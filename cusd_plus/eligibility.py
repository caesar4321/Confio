# Ondo issuer geo-eligibility for cUSD+ (USDY) and tokenized stocks.
#
# Source of truth: Ondo's published eligibility docs (verified 2026-07-04,
# both lists are identical for USDY and Ondo Global Markets):
#   https://docs.ondo.finance/general-access-products/usdy/faq/eligibility
#   https://docs.ondo.finance/ondo-global-markets/eligibility
# Mirrored in our Terms v1.3.1 (users/legal/documents.py, section 9).
#
# Signal: User.phone_country (2-letter ISO, set at phone verification).
# Ondo also prohibits the occupied Ukraine regions (Crimea/DNR/LNR/Kherson/
# Zaporizhzhia/Sevastopol) — a phone country code cannot resolve regions, and
# Ukraine proper is NOT prohibited, so UA is not blocked here; that residual
# screening happens at the issuer's KYC layer.

# Entirely prohibited by the issuer.
ONDO_PROHIBITED = frozenset({
    'US', 'CA', 'AF', 'BY', 'KP', 'CU', 'IR', 'LY', 'MM', 'RU', 'SY',
    'SO', 'SD', 'SS',
})

# Available only to qualified/professional investors under local law.
# Confío is a retail app and does not verify investor accreditation, so
# these are treated as ineligible.
_EEA = frozenset({
    'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR', 'DE', 'GR',
    'HU', 'IE', 'IT', 'LV', 'LT', 'LU', 'MT', 'NL', 'PL', 'PT', 'RO', 'SK',
    'SI', 'ES', 'SE', 'IS', 'LI', 'NO',
})
ONDO_QUALIFIED_ONLY = _EEA | frozenset({'BR', 'GB', 'CH', 'HK', 'SG', 'MY'})

ONDO_BLOCKED = ONDO_PROHIBITED | ONDO_QUALIFIED_ONLY

# Shown to blocked users by the app; also returned from gated mutations.
INELIGIBLE_MESSAGE = (
    'El ahorro con rendimiento y las acciones no están disponibles en tu '
    'país por requisitos del emisor (Ondo Finance).'
)


def is_ondo_eligible(user) -> bool:
    """Whether the user may ENTER cUSD+ / stocks positions.

    Missing phone country fails closed: every active user goes through phone
    verification, so an empty value means we cannot attest a jurisdiction.
    Exits (from_savings, sells) must NEVER be gated on this — funds are
    always withdrawable.
    """
    country = (getattr(user, 'phone_country', None) or '').strip().upper()
    if not country:
        return False
    return country not in ONDO_BLOCKED
