"""Crypto & metals: eligibility gates and the one-time risk disclosure.

A person confirms the disclosure once, before their first purchase. The app
shows the text served here (never hard-coded there), so the version accepted
is always the text read; the relay refuses a buy without it, so an older app
gets a readable refusal instead of a silent pass. Selling never asks and is
never gated by country: a holder can always leave.
"""
from django.conf import settings

ACK_VERSION = 1

DISCLOSURE_TITLE = 'Antes de tu primera compra de cripto u oro'
DISCLOSURE_POINTS = (
    'Las criptomonedas y el oro digital cambian de precio todo el tiempo, también de noche y en fines de '
    'semana. Puedes perder parte o todo lo que inviertas.',
    'Confío no emite estos activos. Bitcoin y Ethereum en BNB Chain son versiones respaldadas por Binance; '
    'el oro digital (XAUt) lo respalda Tether con oro físico; BNB se guarda como WBNB.',
    'Compras y vendes a través de PancakeSwap. El resultado final puede variar un poco respecto a la '
    'cotización; nunca más allá del límite que ves antes de confirmar.',
    'Los activos quedan en tu cuenta, no en Confío. Esto no es asesoría financiera.',
)

ACK_REQUIRED_CODE = 'crypto_ack_required'


def acknowledged(user) -> bool:
    from blockchain.models import CryptoRiskAcknowledgement

    return CryptoRiskAcknowledgement.objects.filter(user=user, version__gte=ACK_VERSION).exists()


def acknowledge(user) -> None:
    from django.utils import timezone

    from blockchain.models import CryptoRiskAcknowledgement

    CryptoRiskAcknowledgement.objects.update_or_create(
        user=user, defaults={'version': ACK_VERSION, 'acknowledged_at': timezone.now()})


def surfaces_enabled(user, meta) -> bool:
    """Discovery: the global switch plus the crypto country policy."""
    from .eligibility import CRYPTO_POLICY

    return bool(
        getattr(settings, 'CRYPTO_ENABLED', False)
        and CRYPTO_POLICY.evaluate(user, meta or {}).allowed
    )


def trading_ready() -> bool:
    return bool(
        getattr(settings, 'CRYPTO_TRADING_ENABLED', False)
        and getattr(settings, 'CRYPTO_SWAP_ROUTER_ADDRESS', '')
        and getattr(settings, 'CUSD_PLUS_7702_ENABLED', False)
        and getattr(settings, 'CUSD_PLUS_BATCH_DELEGATE_ADDRESS', '')
    )


def _canary_allows(user) -> bool:
    raw = getattr(settings, 'CRYPTO_BUY_ALLOWED_USER_IDS', '') or ''
    allowed = {part.strip() for part in str(raw).split(',') if part.strip()}
    return not allowed or str(getattr(user, 'id', '')) in allowed


def buy_enabled(user, meta) -> bool:
    return bool(
        trading_ready()
        and surfaces_enabled(user, meta)
        and getattr(settings, 'CRYPTO_BUY_ENABLED', True)
        and _canary_allows(user)
    )


def sponsor_gate(kind: str, user, meta, *, dollar: int | None = None) -> str | None:
    """Error code refusing a crypto batch, or None.

    Leaving crypto is never country-gated, but WHERE the proceeds land is:
    minting cUSD+ is an Ondo acquisition, so a sale into cUSD+ needs the
    savings mint eligibility; a sale into cUSD is always open."""
    if not trading_ready():
        return 'trade_not_available'
    if kind == 'crypto_sell':
        from .crypto_policy import DOLLAR_PLUS
        from .eligibility import check_savings_mint_eligibility

        if dollar == DOLLAR_PLUS and not check_savings_mint_eligibility(user, meta):
            return 'savings_not_available'
        return None
    if not buy_enabled(user, meta):
        return 'trade_not_available'
    if not acknowledged(user):
        return ACK_REQUIRED_CODE
    return None
