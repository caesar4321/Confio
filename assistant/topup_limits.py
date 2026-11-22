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


def _limits(viewer):
    """(None, fiat, minimum, maximum, live, country) for a person whose top-up
    goes through Koywe now, else (why not, ...)"""
    from ramps.koywe import get_country_ramp_config, on_ramp_paused
    from ramps.koywe_client import KoyweClient, KoyweError
    from security.geo import country_of

    def no(why):
        return why, None, None, None, False, None

    if viewer.is_employee:
        return no('Las recargas las hace el dueño del negocio.')
    country = (country_of(viewer.user) or '').upper()
    config = get_country_ramp_config(country) or {}
    on_ramp = any(method.get('supports_on_ramp') for method in config.get('methods') or [])
    if not on_ramp or on_ramp_paused(country):
        # Not this provider's country (or its top-up is paused there): what
        # the approved answers say about that country's own way stands.
        return no('En su país la recarga no pasa por este proveedor ahora: no hay un mínimo que dar desde '
                  'aquí. Usa lo que dicen las respuestas aprobadas sobre cómo se recarga en su país.')
    fiat = config['fiat_currency']
    if fiat == 'USD':
        # Dollar accounts have no local-currency pair to read a minimum from.
        return no('No tengo el mínimo ahora. La app lo muestra al escribir el monto.')
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
        return no('No tengo el mínimo ahora. La app lo muestra al escribir el monto.')
    return None, fiat, minimum, maximum, live, country


def data(viewer):
    from .engine import CURRENCY_NAMES_ES

    why, fiat, minimum, maximum, live, _country = _limits(viewer)
    if why:
        return {'disponible': False, 'motivo': why}
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


# ── a top-up started from the chat ──────────────────────────────────────────
# The assistant leaves a card that opens "Recargar ahora" with the amount the
# person wrote already filled in: `{'type': 'do', 'target': 'top_up:BOB=200'}`.
# The order itself is still created by that screen, with every check it has
# (identity, address, the provider's quote, Confío Face); the card saves the
# typing, and the phone only fills the amount in when the screen is in that
# same currency.
PROPOSE = 'propose_topup'
PROPOSE_SPEC = {
    'type': 'function',
    'name': PROPOSE,
    'description': ('Cuando la persona quiere recargar con su banco local y escribió cuánto, en su moneda ("quiero '
                    'recargar 500 bolivianos"): deja una tarjeta que abre la recarga con ese monto ya escrito. '
                    'Solo con el monto que ella escribió, en su moneda local (no en dólares). Si no dijo el monto, '
                    'pregúntalo o abre la recarga con `navigate`.'),
    'parameters': {
        'type': 'object',
        'properties': {'amount': {'type': 'number', 'description': 'En la moneda local de la persona, como lo escribió.'}},
        'required': ['amount'],
        'additionalProperties': False,
    },
    'strict': True,
}
_DOLLARS = {'dolar', 'dolares', 'usd', 'us$', 'dollar', 'dollars', 'usdt', 'usdc', 'cusd'}


def offered(belt) -> bool:
    """Where the card can be drawn and "Recargar ahora" is this person's way
    to top up: the chat is Inicio, their own personal account, Koywe's
    top-up open in their country and not replaced by another rail."""
    from .prompts import conversation_home
    from .rails import DEFAULT_TOPUP_ENTRY, topup_entry

    viewer = belt.viewer
    if (not conversation_home(viewer.request_meta) or getattr(viewer, 'user', None) is None
            or viewer.account_type != 'personal' or viewer.is_employee):
        return False
    try:
        why, _fiat, _minimum, _maximum, _live, country = _limits(viewer)
        return not why and topup_entry(country, viewer.user, viewer.request_meta, viewer=viewer) is DEFAULT_TOPUP_ENTRY
    except Exception:  # noqa: BLE001 - no tool is always safe
        logger.warning('assistant: top-up card check failed', exc_info=True)
        return False


def _written(texts, amount):
    """How the person wrote this number in their own messages: 'local' (on
    its own, or with their currency), 'dollars' (every time with dollars),
    or '' (it is not there). The token must be a number and nothing else."""
    from payment_accounts.payment_intents import _amount_values, _fold

    seen = dollars = 0
    for text in texts:
        words = _fold(text).split()
        for index, raw in enumerate(words):
            token = raw.strip('.,;:!?¡¿()')
            lead = token.startswith(('us$', '$'))
            number = token.removeprefix('us$').removeprefix('$')
            if not number or not number[0].isdigit() or not all(ch.isdigit() or ch in '.,' for ch in number):
                continue
            try:
                values = set(_amount_values(number))
                if '.' in number and ',' in number:
                    # Both marks: the last one is the decimal ("1.500,50", "1,500.50").
                    mark = max(number.rfind('.'), number.rfind(','))
                    values = {Decimal(number[:mark].replace('.', '').replace(',', '') + '.' + number[mark + 1:])}
                if amount not in values:
                    continue
            except ArithmeticError:
                continue
            seen += 1
            near = {words[index + 1].strip('.,;:!?¡¿()')} if index + 1 < len(words) else set()
            if index + 2 < len(words) and words[index + 1] == 'de':
                near.add(words[index + 2].strip('.,;:!?¡¿()'))
            dollars += bool(lead and token.startswith('us$')) or bool(near & _DOLLARS)
    return '' if not seen else 'dollars' if seen == dollars else 'local'


def propose(belt, amount):
    from decimal import InvalidOperation

    from .engine import CURRENCY_NAMES_ES

    if any(str(action.get('target') or '').startswith('top_up:') for action in belt.result.actions):
        return {'ok': False, '_denied': True, 'motivo': 'Una tarjeta de recarga por respuesta.'}
    texts = belt.payment_texts
    if not texts:
        return {'ok': False, '_denied': True,
                'motivo': 'La persona debe escribir el monto en un mensaje. Mientras tanto abre la recarga con navigate.'}
    why, fiat, minimum, maximum, _live, _country = _limits(belt.viewer)
    if why:
        return {'ok': False, 'motivo': why}
    currency = CURRENCY_NAMES_ES.get(fiat, fiat)
    try:
        value = Decimal(str(amount)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return {'ok': False, '_denied': True, 'motivo': 'Falta el monto: pregúntaselo.'}
    how = _written(texts, value)
    if not how:
        return {'ok': False, '_denied': True,
                'motivo': f'Ese monto no está en su mensaje: pregúntale cuántos {currency} quiere recargar.'}
    if how == 'dollars':
        return {'ok': False, '_denied': True,
                'motivo': (f'Lo escribió en dólares, y la recarga se escribe en {currency}: no lo conviertas tú. '
                           f'Pregúntale cuántos {currency}, o abre la recarga con navigate para que vea el cambio.')}
    if value < Decimal(str(minimum)):
        return {'ok': False, 'motivo': f'El mínimo por recarga es {_amount(minimum)} {currency}.'}
    if maximum is not None and value > Decimal(str(maximum)):
        return {'ok': False, 'motivo': f'El máximo por recarga es {_amount(maximum)} {currency}.'}
    plain = f'{value:.2f}'.removesuffix('.00')
    label = f'Recargar {_amount(value)} {currency}'
    belt.result.actions.append({'type': 'do', 'target': f'top_up:{fiat}={plain}', 'label': label})
    return {'ok': True, 'tarjeta': label,
            'nota': ('Todavía no se creó nada: quedó una tarjeta bajo tu respuesta que abre la recarga con ese monto '
                     'ya escrito. Dile que la toque: ahí ve cuánto recibe y confirma. No digas cuánto le llegará '
                     'ni que la recarga ya está hecha.')}
