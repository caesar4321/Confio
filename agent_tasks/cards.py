"""One general card for whatever the agent asks the person (docs/designs/agent-task-cards.md).

The server composes every question from a small, fixed vocabulary the app learns once: an icon, a title, a
picture, labelled lines, a total, one short notice and one or two buttons. A new job (a flight, a table, an
appointment) is a new composition here, never a new app build. Choosing products, typing a secret, an address
form, the Cuenta inteligente wait and the payment card stay native: those states have no general card.

A tap is answered by `answer`, with the card's `binding`: the server's own digest of everything that card
showed. It is recomputed from the task as it is now, so a tap approves what was seen or nothing, and the
action is then carried out by the same service call the older cards make, with the values that card showed.
Builds before the general card keep drawing today's fields; nothing changes for them.
"""
import json
import re

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from . import notes, service

VERSION = 1
# Icons the app knows (an unknown one is drawn as a generic icon there).
ICONS = ('bag', 'package', 'calendar', 'bed', 'bus', 'plane', 'table', 'user', 'help', 'bell')
# A screen an action opens in the app, never a call to the server: the app keeps its own list of these.
SCREENS = ('SmartAccountOffer',)

_BOOKING_ICONS = (
    (re.compile(r'\b(vuelo|vuelos|voo|voos|avion|aviao|aerolinea|pasaje aereo|flight)\b'), 'plane'),
    (re.compile(r'\b(bus|buses|autobus|onibus|omnibus|micro|pasaje|pasajes|boleto|boletos|passagem|camion)\b'), 'bus'),
    (re.compile(r'\b(hotel|hoteles|hostal|hostel|posada|alojamiento|habitacion|cabana|pousada|airbnb|noche|noches)\b'),
     'bed'),
    (re.compile(r'\b(restaurante|restaurant|mesa|cena|almuerzo|reserva para \d+|parrilla)\b'), 'table'),
)


def _fold(text):
    from . import guard
    return guard.fold(str(text or ''))


def _booking_icon(task):
    words = _fold(task.goal)
    return next((icon for pattern, icon in _BOOKING_ICONS if pattern.search(words)), 'calendar')


def _line(label, value):
    return {'label': str(label or '')[:40], 'value': str(value or '')[:200]}


def _action(action_id, label, style='primary', screen=None):
    return {'id': action_id, 'label': label, 'style': style, 'screen': screen}


def _count(value):
    try:
        return max(1, int(value or 1))
    except (TypeError, ValueError):
        return 1


def _order_card(task, reserve):
    order = task.order or {}
    if not order.get('total'):
        return None
    items = [one for one in (order.get('items') or []) if isinstance(one, dict)]
    lines = []
    if len(items) > 1 or (items and _count(items[0].get('quantity')) > 1):
        title = f"{sum(_count(one.get('quantity')) for one in items)} productos"
        lines += [_line('', f"{_count(one.get('quantity'))} × {one.get('title') or ''}") for one in items]
    else:
        title = str((items[0].get('title') if items else '') or order.get('item') or '')
    lines += [_line(notes.BREAKDOWN_LABELS[line['kind']].capitalize(),
                    ('- ' if line['kind'] == 'discount' else '') + str(line.get('amount') or ''))
              for line in (order.get('breakdown') or []) if line.get('kind') in notes.BREAKDOWN_LABELS]
    if order.get('address'):
        lines.append(_line('Envío a', order['address']))
    actions = []
    if task.reason == 'subscribe':
        actions += [_action('open_smart_account', 'Activar Cuenta inteligente', screen='SmartAccountOffer'),
                    _action('approve', 'Ya la activé: seguir', 'link')]
    else:
        actions.append(_action('approve', 'Confirmar reserva' if reserve else 'Confirmar pedido'))
        if order.get('address') and not reserve:
            actions.append(_action('change_address', 'Cambiar dirección', 'link'))
    return {'icon': _booking_icon(task) if reserve else 'bag', 'title': title, 'image': str(order.get('image') or ''),
            'lines': lines, 'total': {'label': 'Total', 'value': str(order['total']),
                                      'note': 'Lo pagas tú desde tu banco' if order.get('manual') else ''},
            'actions': actions}


def _request_card(task, reserve):
    order = task.order or {}
    request = order.get('request') or {}
    if not request.get('label') or not request.get('what'):
        return None
    kind = request.get('kind') if reserve else ''
    lines = [_line(f'Botón de {task.site}', f"«{request['button']}»")] if request.get('button') else []
    yes, no = {
        'guest': ('Sí, escríbelos', 'No, déjalo así'),
        'book': (('Sí, confirmar otra vez' if order.get('submitted') else 'Confirmar reserva'), 'No, déjalo así'),
    }.get(kind, ('Sí, envíala', 'No, déjalo así'))
    return {'icon': 'user' if kind == 'guest' else _booking_icon(task) if reserve else 'package',
            'title': str(request['what']), 'lines': lines,
            'actions': [_action('request_yes', yes), _action('request_no', no, 'link')]}


def _step_card(task):
    asked = (task.order or {}).get('ask_step') or {}
    if not asked.get('label'):
        return None
    return {'icon': 'help', 'title': f"«{str(asked['label'])[:80]}»",
            'actions': [_action('step_yes', 'Sí, hazlo'), _action('step_no', 'No', 'link')]}


def _notify_card(task):
    notify = str((task.order or {}).get('notify') or '')
    reserve = getattr(task, 'kind', 'buy') == 'reserve'
    where = ('este sitio' if reserve else 'esta tienda') if task.reason == 'payer_data' else (
        'reservas de aquí' if reserve else 'tiendas de aquí')
    if notify == 'no':
        return None
    if notify == 'yes':
        return {'icon': 'bell', 'title': f'¡Anotado! Te aviso apenas pueda pagar {where}.'}
    return {'icon': 'bell', 'title': f'¿Te aviso cuando pueda pagar {where}?',
            'actions': [_action('notify_yes', 'Sí, avísame'), _action('notify_no', 'Solo miraba', 'link')]}


def _compose(task):
    reserve = getattr(task, 'kind', 'buy') == 'reserve'
    if task.state == 'needs_person':
        if task.reason in ('approve', 'subscribe'):
            return _order_card(task, reserve)
        if task.reason == 'act':
            return _request_card(task, reserve)
        if task.reason == 'step':
            return _step_card(task)
        return None   # choose, login, otp, address, account_wait: native
    if task.state == 'stopped' and task.reason in service.NOTIFY_REASONS:
        return _notify_card(task)
    return None


def _binding(task, body):
    # What a tap carries out, in full (a line on the card may be cut): the order's total, address, item, button
    # and page, and the request's own words.
    order = task.order or {}
    acted = {key: order.get(key) for key in ('total', 'address', 'item', 'button', 'page')}
    acted['request'] = (order.get('request') or {}).get('what')
    acted['step'] = (order.get('ask_step') or {}).get('label')
    shown = json.dumps({'task': str(task.internal_id), 'state': task.state, 'reason': task.reason, 'card': body,
                        'acted': acted}, sort_keys=True, ensure_ascii=False, default=str)
    return salted_hmac('agent_tasks.cards', shown).hexdigest()[:40]


def card(task):
    """The general card for this task as it is now, or None (a native state, or nothing to ask)."""
    if task is None:
        return None
    body = _compose(task)
    if body is None:
        return None
    body = {'version': VERSION, 'icon': 'help', 'title': '', 'subtitle': task.site, 'image': '', 'lines': [],
            'total': None, 'notice': '', 'actions': [], 'status': task.state, 'reason': task.reason, **body}
    return {**body, 'binding': _binding(task, body)}


def answer(account, user, task_id, action, binding):
    """A tap on the general card: the card is built again from the task as it is now, and only a tap on the very
    card that was seen goes on, through the same call the older cards make with the values it showed."""
    task = service.get(account, user, task_id)
    if task.state == 'needs_person' and task.wait_until and task.wait_until <= timezone.now():
        # Expired, as the older cards end it (service._answered): never answered late.
        from . import runner
        runner.end(task, 'stopped', 'person_timeout', only={'state': 'needs_person'})
        raise service.TaskRefused('not_open')
    with transaction.atomic():
        # Held while the card is checked and the tap carried out: the agent cannot change the task in between,
        # so the service acts on the very task the card was built from.
        task = type(task).objects.select_for_update().get(pk=task.pk)
        if task.state == 'needs_person' and task.wait_until and task.wait_until <= timezone.now():
            raise service.TaskRefused('not_open')   # expired meanwhile: ended by the sweep, never answered late
        now = card(task)
        if now is None or not constant_time_compare(str(binding or ''), now['binding']):
            raise service.TaskRefused('not_open')   # the card they tapped is not the one this task shows now
        chosen = next((one for one in now['actions'] if one['id'] == action), None)
        if chosen is None or chosen.get('screen'):
            raise service.TaskRefused('not_open')   # an action the card did not offer, or one the app opens itself
        return _carry_out(account, user, task_id, task, action)


def _carry_out(account, user, task_id, task, action):
    order = task.order or {}
    if action == 'approve':
        return service.approve(account, user, task_id, total=str(order.get('total') or ''),
                               address=str(order.get('address') or ''))
    if action == 'change_address':
        return service.change_address(account, user, task_id)
    if action in ('request_yes', 'request_no'):
        return service.answer_request(account, user, task_id, action == 'request_yes',
                                      what=str((order.get('request') or {}).get('what') or ''))
    if action in ('step_yes', 'step_no'):
        return service.answer_step(account, user, task_id, action == 'step_yes')
    if action in ('notify_yes', 'notify_no'):
        return service.answer_notify(account, user, task_id, action == 'notify_yes')
    raise service.TaskRefused('not_open')
