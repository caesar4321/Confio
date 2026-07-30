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


def check_savings_mint_eligibility(user, request_meta) -> bool:
    """The MINT-side geo stack (2026-07-30): phone country AND IP country.

    Since the phase-out, ramp deposits deliver raw USDT-BSC to everyone and
    THIS check is where geo-eligibility is actually enforced — on the vault
    subscribeAndMint relayed through SubmitBscTransaction / SponsorBscBatch.
    Ineligible users simply keep raw USDT ("Confío Dollar" in the app).

    Posture mirrors the presale geo stack (presale/geo_utils.py): the phone
    country fails CLOSED (is_ondo_eligible), the IP country fails OPEN when
    unresolvable — Cloudflare fronts prod so CF-IPCountry dominates, and an
    unresolvable IP shouldn't strand an attested-eligible user's mint.

    Gates the MINT only. Exits (redeemToUsdt, raw USDT transfers, off-ramps)
    are NEVER gated on this.
    """
    if not is_ondo_eligible(user):
        return False
    try:
        # Import-only reuse: geo_utils is presale-owned (shared home is a
        # flagged follow-up); a resolver crash counts as unresolvable.
        from presale.geo_utils import get_country_for_ip
        from security.request_utils import extract_client_ip_from_meta
        meta = request_meta or {}
        ip_country = get_country_for_ip(
            extract_client_ip_from_meta(meta),
            meta.get('HTTP_CF_IPCOUNTRY'),
        )
    except Exception:  # noqa: BLE001 — unresolvable IP fails open
        return True
    return ip_country is None or ip_country not in ONDO_BLOCKED
