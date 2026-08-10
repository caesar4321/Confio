# Ondo issuer geo-eligibility for cUSD+ (USDY) and tokenized stocks.
#
# Source of truth: Ondo's published eligibility docs (verified 2026-07-04,
# re-verified 2026-08-04 after the public BNB launch — UNCHANGED, and
# Venezuela is still absent from the prohibited list; both lists are
# identical for USDY and Ondo Global Markets):
#   https://docs.ondo.finance/general-access-products/usdy/faq/eligibility
#   https://docs.ondo.finance/ondo-global-markets/eligibility
# Mirrored in our Terms v1.4.0 (users/legal/documents.py, section 9).
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

from django.conf import settings

from security.geo import GeoPolicy

# Shown to blocked users by the app; also returned from gated mutations.
INELIGIBLE_MESSAGE = (
    'El ahorro con rendimiento y las acciones no están disponibles en tu '
    'país por requisitos del emisor (Ondo Finance).'
)


# The policy; the mechanism lives in security/geo.py, shared with presale.
# Ondo's IP list is the same as its phone list, and a missing phone country
# fails CLOSED — every active user completes phone verification, so an empty
# value means we cannot attest a jurisdiction.
ONDO_POLICY = GeoPolicy(
    name='ondo',
    phone_blocked=ONDO_BLOCKED,
    message=INELIGIBLE_MESSAGE,
    allow_missing_phone=False,
    ip_blocked=None,              # same list as phone
    ip_fails_open_on_error=True,  # a resolver outage must not strand an
                                  # attested-eligible user's mint
)


def _confio_stock_buy_blocked_countries():
    """Live ISO-2 entry-only overlay controlled by Confío operations."""
    configured = getattr(settings, 'CUSD_PLUS_STOCK_BUY_BLOCKED_COUNTRIES', ())
    if isinstance(configured, str):
        configured = configured.split(',')
    return frozenset(
        str(country).strip().upper()
        for country in configured
        if str(country).strip()
    )


STOCK_BUY_BLOCKED_MESSAGE = (
    'Las compras de acciones no están disponibles en tu país. '
    'Aún puedes vender tus posiciones existentes.'
)

CONFIO_STOCK_BUY_POLICY = GeoPolicy(
    name='confio_stock_buy',
    phone_blocked=_confio_stock_buy_blocked_countries,
    message=STOCK_BUY_BLOCKED_MESSAGE,
    allow_missing_phone=False,
    ip_blocked=_confio_stock_buy_blocked_countries,
    ip_fails_open_on_error=True,
)


def is_ondo_eligible(user) -> bool:
    """Phone country ONLY — the half-check.

    Correct where no request exists: a Celery scanner, or a payroll/send
    RECIPIENT (who is not the one making the call). Anywhere a request IS
    available use ONDO_POLICY.evaluate() — checking phone alone with a request
    in hand is what told users behind a blocked IP that they could save while
    the relay refused them.

    Exits (from_savings, sells) must NEVER be gated on this — funds are
    always withdrawable.
    """
    return ONDO_POLICY.phone_eligible(user)


def check_savings_mint_eligibility(user, request_meta) -> bool:
    """The MINT-side geo stack (2026-07-30): phone country AND IP country.

    Since the phase-out, ramp deposits deliver raw USDT-BSC to everyone and
    THIS check is where geo-eligibility is actually enforced — on the vault
    subscribeAndMint relayed through SubmitBscTransaction / SponsorBscBatch.
    Ineligible users simply keep raw USDT ("Confío Dollar" in the app).

    Phone fails CLOSED, IP fails OPEN when unresolvable — Cloudflare fronts
    prod so CF-IPCountry dominates, and an unresolvable IP shouldn't strand an
    attested-eligible user's mint. Both encoded in ONDO_POLICY above.

    Gates the MINT only. Exits (redeemToUsdt, raw USDT transfers, off-ramps)
    are NEVER gated on this.
    """
    return ONDO_POLICY.evaluate(user, request_meta or {}).allowed


def check_stock_buy_eligibility(user, request_meta) -> bool:
    """Issuer eligibility plus Confío's entry-only country overlay.

    This function must only gate stock purchases. Stock sells are exits and
    deliberately never call it.
    """
    meta = request_meta or {}
    return (
        ONDO_POLICY.evaluate(user, meta).allowed
        and CONFIO_STOCK_BUY_POLICY.evaluate(user, meta).allowed
    )
