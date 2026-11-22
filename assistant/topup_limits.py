"""The least and the most one top-up can be, where it goes through Koywe
("Recargar ahora" with a local bank): the same figures the top-up screen
enforces (ramps.schema.resolve_ramp_availability), read from the provider
(cached there for hours) with the last known ones as fallback.

So that "¿cuál es el mínimo para recargar?" gets a number in the person's
own currency instead of "the app shows it"."""
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

SPEC = {
    'type': 'function',
    'name': 'get_topup_limits',
    'description': ('Monto mínimo y máximo de una recarga con banco local ("Recargar ahora") en el país de la '
                    'persona, en su moneda, según el proveedor de recargas. Úsala cuando pregunte cuánto es lo '
                    'mínimo (o lo máximo) que puede recargar.'),
    'parameters': {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False},
    'strict': True,
}


def _amount(value):
    """1000 → '1.000'; 350 → '350'; 0.5 → '0,50' (Spanish separators)."""
    value = Decimal(str(value))
    whole = value == value.to_integral_value()
    text = f'{value:,.0f}' if whole else f'{value:,.2f}'
    return text.replace(',', ' ').replace('.', ',').replace(' ', '.')


def data(viewer):
    from ramps.koywe import get_country_ramp_config, on_ramp_paused
    from ramps.koywe_client import KoyweClient, KoyweError
    from security.geo import country_of

    from .engine import CURRENCY_NAMES_ES

    if viewer.is_employee:
        return {'disponible': False, 'motivo': 'Las recargas las hace el dueño del negocio.'}
    country = (country_of(viewer.user) or '').upper()
    config = get_country_ramp_config(country) or {}
    on_ramp = any(method.get('supports_on_ramp') for method in config.get('methods') or [])
    if not on_ramp or on_ramp_paused(country):
        # Not this provider's country (or its top-up is paused there): what
        # the approved answers say about that country's own way stands.
        return {'disponible': False,
                'motivo': 'En su país la recarga no pasa por este proveedor ahora: no hay un mínimo que dar desde '
                          'aquí. Usa lo que dicen las respuestas aprobadas sobre cómo se recarga en su país.'}
    fiat = config['fiat_currency']
    if fiat == 'USD':
        # Dollar accounts have no local-currency pair to read a minimum from.
        return {'disponible': False, 'motivo': 'No tengo el mínimo ahora. La app lo muestra al escribir el monto.'}
    live, limits = True, {}
    try:
        # The pair limits alone (one cached read): the full estimate the screen
        # also asks for is several provider calls, too slow inside a chat turn.
        limits = KoyweClient().get_public_ramp_limits(fiat_symbol=fiat) or {}
    except KoyweError as exc:
        logger.warning('assistant: Koywe limits unavailable for %s: %s', fiat, exc)
    except Exception:  # noqa: BLE001 - an answer with the last known figure beats no answer
        logger.exception('assistant: Koywe limits failed for %s', fiat)
    minimum = limits.get('on_ramp_min_amount')
    maximum = limits.get('on_ramp_max_amount')
    if minimum is None:
        live, minimum = False, config.get('on_ramp_min_amount')
        maximum = maximum if maximum is not None else config.get('on_ramp_max_amount')
    if minimum is None:
        return {'disponible': False, 'motivo': 'No tengo el mínimo ahora. La app lo muestra al escribir el monto.'}
    currency = CURRENCY_NAMES_ES.get(fiat, fiat)
    out = {
        'disponible': True,
        'minimo_por_recarga': f'{_amount(minimum)} {currency}',
        'dato': 'leído del proveedor' if live else 'último valor conocido: puede haber cambiado, dilo',
        'nota': ('Es el mínimo de UNA recarga con banco local ("Recargar ahora"), no el de usar Confío: con saldo '
                 'en la app todo lo demás tiene sus propios mínimos. Da la cifra en su moneda tal cual; no la '
                 'pases a dólares ni calcules cuánto llegaría. La app no deja escribir un monto menor.'),
    }
    if maximum is not None:
        out['maximo_por_recarga'] = f'{_amount(maximum)} {currency}'
    return out
