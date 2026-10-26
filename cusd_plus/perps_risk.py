"""Futuros: gates and the one-time risk disclosure.

Same contract as crypto_risk: the app shows the text served here, the
version accepted is the text read, and the relay refuses an open without it.
Closing a position and bringing the money home never ask and are never gated
by country, canary or the open switch: a holder can always leave.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

ACK_VERSION = 1

DISCLOSURE_TITLE = 'Antes de tu primera operación con futuros'
DISCLOSURE_POINTS = (
    'Los futuros perpetuos usan apalancamiento: multiplica tus ganancias y también tus pérdidas. '
    'Si el precio va en tu contra, tu posición se liquida y puedes perder todo el margen que pusiste.',
    'Cada posición tiene su propio margen. Mientras está abierta pagas o cobras una tasa de '
    'financiamiento cada hora, y los precios se mueven las 24 horas, también de noche y en fines de semana.',
    'Confío no es un exchange ni un bróker: las órdenes se ejecutan en Hyperliquid, una plataforma que '
    'Confío no opera. El dinero queda en tu propia cuenta, firmado con tu llave.',
    'Al abrir, tu margen sale de tu saldo en dólares y cruza a Hyperliquid; al cerrar, vuelve. '
    'Cada salida y cada entrada pagan la comisión de 0,9% de Confío Dollar, y la transferencia entre '
    'redes tiene un costo pequeño que ves antes de confirmar.',
    'Esto no es asesoría financiera.',
)

ACK_REQUIRED_CODE = 'perps_ack_required'


def acknowledged(user) -> bool:
    from blockchain.models import PerpsRiskAcknowledgement

    return PerpsRiskAcknowledgement.objects.filter(user=user, version__gte=ACK_VERSION).exists()


def acknowledge(user) -> None:
    from django.utils import timezone

    from blockchain.models import PerpsRiskAcknowledgement

    PerpsRiskAcknowledgement.objects.update_or_create(
        user=user, defaults={'version': ACK_VERSION, 'acknowledged_at': timezone.now()})


def _is_ios(meta) -> bool:
    # The app sends X-Confio-Platform on every request (see security/face_client.py).
    return str((meta or {}).get('HTTP_X_CONFIO_PLATFORM', '') or '').strip().lower() == 'ios'


def platform_allowed(meta) -> bool:
    """PERPS_IOS_ENABLED is the store-review kill switch for new iOS opens."""
    return bool(getattr(settings, 'PERPS_IOS_ENABLED', True)) or not _is_ios(meta)


def country_allowed(user, meta) -> bool:
    """PERPS_POLICY, failing CLOSED: an IP lookup that raises refuses the
    open (closes are never country-gated, so nobody is stranded)."""
    from .eligibility import PERPS_POLICY

    try:
        return bool(PERPS_POLICY.evaluate(user, meta or {}).allowed)
    except Exception:  # noqa: BLE001 — money policy fails closed
        logger.warning('perps country check failed for user %s', getattr(user, 'id', None), exc_info=True)
        return False


def surfaces_enabled(user, meta) -> bool:
    """Discovery: the global switch, the platform switch, the country policy."""
    return bool(
        getattr(settings, 'PERPS_ENABLED', False)
        and platform_allowed(meta)
        and country_allowed(user, meta)
    )


def trading_ready() -> bool:
    return bool(
        getattr(settings, 'PERPS_TRADING_ENABLED', False)
        and getattr(settings, 'CUSD_PLUS_7702_ENABLED', False)
        and getattr(settings, 'CUSD_PLUS_BATCH_DELEGATE_ADDRESS', '')
    )


def _canary_allows(user) -> bool:
    raw = getattr(settings, 'PERPS_ALLOWED_USER_IDS', '') or ''
    allowed = {part.strip() for part in str(raw).split(',') if part.strip()}
    return not allowed or str(getattr(user, 'id', '')) in allowed


def open_enabled(user, meta) -> bool:
    return bool(
        trading_ready()
        and surfaces_enabled(user, meta)
        and getattr(settings, 'PERPS_OPEN_ENABLED', True)
        and _canary_allows(user)
    )


def open_gate(user, meta) -> str | None:
    """Error code refusing an open or a margin add, or None."""
    if not trading_ready() or not open_enabled(user, meta):
        return 'trade_not_available'
    if not acknowledged(user):
        return ACK_REQUIRED_CODE
    return None


def exit_gate() -> str | None:
    """Hyperliquid closes, cancels and margin removal: only the execution
    switch can stop them (an incident), never country, canary, ack or the
    BSC sponsorship settings. The BSC return batch has its own relay checks."""
    return None if getattr(settings, 'PERPS_TRADING_ENABLED', False) else 'trade_not_available'
