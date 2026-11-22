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
    goes through Koywe now, else (why not, ...). Read once per turn: several
    tools ask, and a provider that is down must not be waited for each time."""
    cached = getattr(viewer, '_topup_limits', None)
    if cached is None:
        cached = _read_limits(viewer)
        try:
            viewer._topup_limits = cached
        except Exception:  # noqa: BLE001 - a viewer that cannot hold it just reads again
            pass
    return cached


def _read_limits(viewer):
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
# The assistant leaves the top-up form under its answer, with the amount the
# person wrote already filled in: `{'type': 'form', 'target': 'topup:BOB=200'}`
# (with no amount it is `ask_details` with the form `topup`). The person sees
# what they get and creates the order there; the phone runs every check the
# top-up screen has (identity, address, the provider's quote, Confío Face)
# and the server enforces them again. The amount is filled in only when the
# form is in that same currency.
PROPOSE = 'propose_topup'
PROPOSE_SPEC = {
    'type': 'function',
    'name': PROPOSE,
    'description': ('Cuando la persona quiere recargar con su banco local y escribió cuánto, en su moneda ("quiero '
                    'recargar 500 bolivianos"): deja bajo tu respuesta el formulario de recarga con ese monto ya '
                    'escrito, para que la cree aquí mismo. Solo con el monto que ella escribió, en su moneda local '
                    '(no en dólares). Si no dijo el monto, deja el formulario vacío con `ask_details` (topup).'),
    'parameters': {
        'type': 'object',
        'properties': {'amount': {'type': 'number', 'description': 'En la moneda local de la persona, como lo escribió.'}},
        'required': ['amount'],
        'additionalProperties': False,
    },
    'strict': True,
}
# Every way people write dollars around a number: "50 dólares", "USD 50",
# "US$ 50", "$us 50" (Bolivia), "50 dls", "50 en dólares", "50 de mis dólares".
_DOLLARS = {'dolar', 'dolares', 'usd', 'us$', '$us', 'u$s', 'us', 'usd$', 'dls', 'dolaritos', 'verdes', 'dollar',
            'dollars', 'usdt', 'usdc', 'cusd'}
_GLUED = ('us$', '$us', 'u$s', 'usd', '$')
# Where the peso sign is not the country's own, a bare "$" means dollars.
_DOLLAR_SIGN_IS_FOREIGN = {'BOB', 'PEN', 'BRL', 'VES', 'PYG', 'GTQ'}
_NO = {'no', 'ni', 'nunca', 'sin', 'tampoco'}
_EDGE = '.,;:!?¡¿()"\''
CARD_HOURS = 24


def offered(belt) -> bool:
    """Where the form can be drawn and "Recargar ahora" is this person's way
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


def _written(texts, amount, fiat=''):
    """How the person wrote this number in what they asked: 'local' (on its
    own, or with their currency), 'dollars' (every time with a dollar word or
    sign near it), or '' (it is not there as a number of its own, or they
    denied it: "no 500, mejor 400")."""
    from payment_accounts.payment_intents import _amount_values, _fold

    seen = dollars = 0
    for text in texts:
        words = [_fold(raw).strip(_EDGE) for raw in text.split()]
        for index, token in enumerate(words):
            sign = next((mark for mark in _GLUED if token.startswith(mark) and token != mark), '')
            tail = next((mark for mark in _GLUED if not sign and token.endswith(mark) and token != mark), '')
            number = token[len(sign):] if sign else token[:-len(tail)] if tail else token
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
            before = words[max(0, index - 3):index]
            if set(before) & _NO:
                continue
            seen += 1
            glued = sign or tail
            near = set(words[max(0, index - 2):index] + words[index + 1:index + 4])
            dollars += bool((glued and (glued != '$' or fiat in _DOLLAR_SIGN_IS_FOREIGN)) or near & _DOLLARS
                            or ('$' in near and fiat in _DOLLAR_SIGN_IS_FOREIGN))
    return '' if not seen else 'dollars' if seen == dollars else 'local'


def propose(belt, amount):
    from decimal import InvalidOperation

    from .engine import CURRENCY_NAMES_ES

    if any(action.get('type') == 'form' for action in belt.result.actions):
        return {'ok': False, '_denied': True, 'motivo': 'Ya hay un formulario en esta respuesta: uno a la vez.'}
    texts = belt.payment_texts
    if not texts:
        return {'ok': False, '_denied': True,
                'motivo': 'La persona debe escribir el monto en un mensaje. Deja el formulario vacío con ask_details (topup).'}
    why, fiat, minimum, maximum, _live, _country = _limits(belt.viewer)
    if why:
        return {'ok': False, 'motivo': why}
    currency = CURRENCY_NAMES_ES.get(fiat, fiat)
    try:
        value = Decimal(str(amount)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return {'ok': False, '_denied': True, 'motivo': 'Falta el monto: pregúntaselo.'}
    # A request, not a question or a pasted text (as for a trade card).
    from .trades import _requests
    texts = _requests(texts)
    if not texts:
        return {'ok': False, '_denied': True,
                'motivo': 'Eso fue una pregunta, no un pedido: respóndela. Si quiere recargar, deja el formulario '
                          'vacío con ask_details (topup).'}
    how = _written(texts, value, fiat)
    if not how:
        return {'ok': False, '_denied': True,
                'motivo': f'Ese monto no está en su mensaje: pregúntale cuántos {currency} quiere recargar.'}
    if how == 'dollars':
        return {'ok': False, '_denied': True,
                'motivo': (f'Lo escribió en dólares, y la recarga se escribe en {currency}: no lo conviertas tú. '
                           f'Pregúntale cuántos {currency}, o deja el formulario vacío con ask_details (topup): ahí ve '
                           'cuánto recibe según lo que pague.')}
    if value < Decimal(str(minimum)):
        return {'ok': False, 'motivo': f'El mínimo por recarga es {_amount(minimum)} {currency}.'}
    if maximum is not None and value > Decimal(str(maximum)):
        return {'ok': False, 'motivo': f'El máximo por recarga es {_amount(maximum)} {currency}.'}
    plain = f'{value:.2f}'.removesuffix('.00')
    label = f'Recargar {_amount(value)} {currency}'
    belt.result.actions.append({'type': 'form', 'target': f'topup:{fiat}={plain}', 'label': label})
    return {'ok': True, 'formulario': label,
            'nota': ('Todavía no se creó nada: quedó el formulario de recarga bajo tu respuesta con ese monto ya '
                     'escrito. Dile que elija cómo paga y toque Crear recarga: ahí ve cuánto recibe, y las '
                     'instrucciones para pagar quedan en la conversación. No digas cuánto le llegará ni que la '
                     'recarga ya está hecha.')}


# ── the order a form created ────────────────────────────────────────────────
# The form's message keeps the order it created, so the conversation shows
# that order again after the app restarts (never the form, ready to create a
# second one), and a form is live for a day only.

def _form_message(user, message_id):
    from inbox.models import SupportMessage

    try:
        message = SupportMessage.objects.filter(pk=int(message_id), conversation__user=user).first()
    except (TypeError, ValueError):
        return None
    if message is None or message.sender_type == 'USER':
        return None
    actions = (message.metadata or {}).get('actions') or []
    mine = any(isinstance(a, dict) and a.get('type') == 'form' and str(a.get('target') or '').split(':')[0] == 'topup'
               for a in actions)
    return message if mine else None


def _order_row(user, order_id):
    from ramps.models import RampTransaction

    return RampTransaction.objects.filter(
        provider='koywe', direction='ON_RAMP', provider_order_id=str(order_id or ''), actor_user=user,
    ).exclude(provider_order_id='').first()


def attach(user, message_id, order_id, method_code='', method_display=''):
    """The form of this message created this order. Kept once; only the
    person's own form and their own order."""
    import re

    from inbox.models import SupportMessage

    message = _form_message(user, message_id)
    if message is None or (message.metadata or {}).get('topup_order') or _order_row(user, order_id) is None:
        return False
    code = method_code if re.fullmatch(r'[A-Za-z0-9_-]{1,24}', method_code or '') else ''
    display = ' '.join(str(method_display or '').split())[:40]
    metadata = {**(message.metadata or {}), 'topup_order': {'id': str(order_id), 'method': code, 'method_name': display}}
    SupportMessage.objects.filter(pk=message.pk).update(metadata=metadata)
    return True


def card(user, message_id):
    """(state, order) for the form of this message: 'order' with what the
    card needs, 'none' (the form is live), 'expired' or 'gone'."""
    from datetime import timedelta

    from django.utils import timezone

    message = _form_message(user, message_id)
    if message is None:
        return 'gone', None
    kept = (message.metadata or {}).get('topup_order') or {}
    row = _order_row(user, kept.get('id')) if kept.get('id') else None
    if row is not None:
        return 'order', {
            'order_id': row.provider_order_id, 'country_code': row.country_code, 'fiat_currency': row.fiat_currency,
            'fiat_amount': None if row.fiat_amount is None else f'{row.fiat_amount.normalize():f}',
            'payment_method_code': kept.get('method') or '', 'payment_method_display': kept.get('method_name') or '',
        }
    if timezone.now() - message.created_at > timedelta(hours=CARD_HOURS):
        return 'expired', None
    return 'none', None
