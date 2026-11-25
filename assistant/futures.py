"""The member's open Futuros positions, read for Confío IA.

"Dame una lectura de mis futuros" got "no puedo ver tus datos, escríbeme el
apalancamiento y el precio de liquidación" (2026-11-24): the assistant had no
read of positions the app shows on the next screen. Same rows and figures as
the Futuros screens (cusd_plus.perps_schema.position_rows), without the
inline reconcile those screens run: a chat read never moves a position.
"""
import logging

logger = logging.getLogger(__name__)

SIDE_ES = {'long': 'largo (gana si el precio sube)', 'short': 'corto (gana si el precio baja)'}
STATE_ES = {
    'open': 'abierta', 'funded': 'abriéndose', 'bridging': 'abriéndose (fondos en camino)',
    'returning': 'cerrándose (el dinero vuelve a tu saldo)', 'closed': 'cerrándose (el dinero vuelve a tu saldo)',
    'liquidated': 'liquidada (el dinero que quedó vuelve a tu saldo)', 'refunded': 'devolviéndose',
    'landed': 'cerrada (el dinero llegó a tu saldo)',
    'return_failed': 'cerrada; la devolución del dinero a tu saldo está pendiente de reintento',
}


def offered(viewer) -> bool:
    """Only for someone who has had a position: everyone else has nothing to read."""
    user = getattr(viewer, 'user', None)
    if user is None or getattr(viewer, 'account_type', '') != 'personal':
        return False
    from cusd_plus.perps_risk import platform_allowed
    if not platform_allowed(getattr(viewer, 'request_meta', None) or {}):
        return False  # iOS has no Futuros
    try:
        from blockchain.models import PerpPosition
        return PerpPosition.objects.filter(user=user).exclude(state__in=('cancelled', 'quoted')).exists()
    except Exception:  # noqa: BLE001 - unknown is not offered
        logger.warning('Confio Assistant: futures availability unknown', exc_info=True)
        return False


def _usd(value):
    return None if value is None else round(float(value), 2)


def _px(value):
    return None if value is None else float(f'{float(value):.6g}')


def futures_data(viewer):
    account = getattr(viewer, 'account', None)
    wallet = (getattr(account, 'bsc_address', '') or '').lower()
    if getattr(viewer, 'account_type', '') != 'personal' or not wallet:
        return {'disponible': False, 'motivo': 'Futuros es solo de la cuenta personal.'}
    try:
        from blockchain.models import PerpPosition
        from cusd_plus.perps_schema import position_rows
        rows = position_rows(viewer.user, wallet, reconcile=False)
    except Exception:  # noqa: BLE001 - never a guessed number
        logger.warning('Confio Assistant: futures read failed', exc_info=True)
        rows = None
    if rows is None:
        return {'disponible': False, 'motivo': 'No pude leer tus posiciones de Futuros ahora. Revísalas en Futuros.'}
    live = [r for r in rows if r.state not in PerpPosition.TERMINAL_STATES]
    return {
        'disponible': True,
        'posiciones': [
            {
                'activo': f'{r.name} ({r.ticker})',
                'lado': SIDE_ES.get(r.side, r.side),
                'apalancamiento': f'{r.leverage}x',
                'estado': STATE_ES.get(r.state, r.state),
                'puesto_usd': _usd(r.put_in_usd),
                'valor_ahora_usd': _usd(r.value_usd),
                'ganancia_no_realizada_usd': _usd(r.unrealized_pnl_usd),
                'precio_entrada': _px(r.entry_px),
                'precio_actual': _px(r.mark_px),
                'precio_liquidacion': _px(r.liquidation_px),
                'financiamiento_desde_apertura_usd': _usd(r.funding_usd),
                'take_profit': _px(r.take_profit_px) if r.protection_known else 'desconocido',
                'stop_loss': _px(r.stop_loss_px) if r.protection_known else 'desconocido',
                **({'entrada_limite_esperando_en': _px(r.resting_px)} if r.resting_px else {}),
            }
            for r in live
        ],
        'nota': ('Cifras de ahora; cambian con el precio. Solo información: la decisión de cerrar es suya, '
                 'desde Futuros.'),
    }
