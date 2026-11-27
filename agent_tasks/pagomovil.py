"""Venezuelan store purchases paid by Pago Móvil, before the order exists (design 2026-11-25).

SPEI is: approve, press the final button, the store shows a CLABE, Confío pays. Pago Móvil is the other way
round: the checkout shows the store's Pago Móvil data and a form BEFORE the order exists; the payer pays, then
types the payment's reference into the form, and submitting it places the order. So:

  pay_first   at the approved order's final button (operate._order) nothing is pressed. A model reads the
              step (agent.read_pagomovil): the store's bank, phone, cédula or RIF, the bolívares and the
              form's fields. Code checks each value is written on the page, the amount is the approved one,
              and two pictures agree (read). A form that asks the PAYER's own phone, bank, document or name
              (or anything but the reference, the date and the amount) is stopped before any money moves:
              Confío's payouts carry no payer of the person's (stop `payer_data`). Else the account pays
              (runner.Step.pay_read -> account_pay.pay); the funding leg calls service.store_paid.
  report      a fresh browser session goes back to the same checkout's Pago Móvil step (agent.report), reads
              it again (the amount must still be what was paid, to the same store data), and CODE types the
              reference (and the date or amount when asked) into the fields the reader named; the store's
              final button is pressed through the same second reader as any order (operate._reviewed), once.
              A second reader confirms the order exists (agent.placed): done. A session that fails is tried
              again (AGENT_TASKS_MAX_REPORT_TRIES), never after the final press; then the person is given the
              reference and the store's data to report it themselves, and ops are told (report_failed).

No word of a store's is matched to decide anything here: models read, code checks facts.
"""
import logging
import re
import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from . import agent, conf, countries, guard, notes, operate, sites

logger = logging.getLogger(__name__)

# What a form may ask to report a payment Confío made: nothing about the payer.
REPORTABLE = frozenset({'reference', 'date', 'amount'})
_TYPABLE = ('text', 'number', 'tel', 'date', 'search', '')


def _fold(text):
    text = unicodedata.normalize('NFKD', str(text or '')).encode('ascii', 'ignore').decode().lower()
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', text).split())


def bank_code(written):
    """The SUDEBAN code of the bank the page names: its 4-digit code, or a name that is one of ours alone."""
    from ramps import ve_pagomovil
    codes = {code for code in re.findall(r'(?<!\d)(0\d{3})(?!\d)', str(written or '')) if code in ve_pagomovil.BANK_NAMES}
    if len(codes) == 1:
        return codes.pop()
    if codes:
        return ''
    words = set(_fold(written).split()) - {'banco', 'de', 'del', 'la', 'el', 'bank'}
    if not words:
        return ''
    found = [code for code, name in ve_pagomovil.BANKS if words <= set(_fold(name).split())]
    return found[0] if len(found) == 1 else ''


def _text(shot):
    return '\n'.join(str(node) for node in (shot.text or ()))


def _one(task, seen, shot, meter):
    """(facts, '') off one picture, or (None, why). Every value the model copied must be written there."""
    from ramps import ve_pagomovil
    text = _text(shot)
    if shot.text is None or not text.strip():
        return None, 'screen'
    read = agent.read_pagomovil(task, seen, text, meter)
    if not read['shown']:
        return None, 'code'
    for key in ('bank', 'phone', 'document', 'amount'):
        if not read[key] or not operate.written_on(text, read[key]):
            return None, 'code'
    amount = operate.amount_of(read['amount'])
    if amount is None or amount <= 0 or not operate.figure_on(text, amount):
        return None, 'code'
    try:
        phone = ve_pagomovil.normalize_phone(read['phone'])
        cedula = ve_pagomovil.normalize_cedula(read['document'])
    except ve_pagomovil.VePagoMovilError:
        return None, 'code'
    bank = bank_code(read['bank'])
    if not bank:
        return None, 'code'
    holder = read['holder'] if read['holder'] and operate.written_on(text, read['holder']) else ''
    asks, refs = set(), {}
    for field in read['fields']:
        if field['asks'] not in agent.FIELD_ASKS:
            return None, 'code'
        if not field['required'] and field['asks'] not in REPORTABLE:
            continue   # an optional field about the payer is left empty
        asks.add(field['asks'])
        if isinstance(field['ref'], int) and not isinstance(field['ref'], bool):
            refs.setdefault(field['asks'], field['ref'])
    return {'bank_code': bank, 'phone': phone, 'cedula': cedula, 'holder': holder,
            'amount_ves': format(amount, 'f'), 'amount_text': read['amount'], 'asks': sorted(asks),
            'refs': refs}, ''


def read(task, seen, shots, meter):
    """(facts, '') when two pictures of the step read the same, else (None, why). The amount is not compared
    here: the caller holds it against what the person approved, or what was paid."""
    if not shots or len(shots) < 2:
        return None, 'screen'
    from .reserve import guest_pattern
    hidden = guest_pattern(task)
    if hidden is not None:
        # A booking's form holds her details: the reader sees each picture's words without them.
        from dataclasses import replace
        shots = [replace(shot, text=tuple(hidden.sub('[dato]', str(node)) for node in shot.text))
                 if shot.text is not None else shot for shot in shots]
    if not sites.within(shots[0].url, task.site, house=True):
        return None, 'offsite'
    try:
        first, why = _one(task, seen, shots[0], meter)
        if why:
            return None, why
        second, why = _one(task, seen, shots[1], meter)
    except agent.AgentUnavailable:
        return None, 'unavailable'
    if why:
        return None, why
    keep = ('bank_code', 'phone', 'cedula', 'amount_ves', 'asks')
    if {key: first[key] for key in keep} != {key: second[key] for key in keep}:
        return None, 'screen'
    return first, ''


def request_of(details):
    """What the payment card is prepared with: the store's Pago Móvil and the exact bolívares, no reference."""
    return {'amount_local': details['amount_ves'], 'cedula': details['cedula'], 'phone': details['phone'],
            'bank_code': details['bank_code'], 'holder_name': details.get('holder') or ''}


def code_of(details):
    """What a hold keeps as this payment's 'code' (account_pay.new_hold): never sent to the rail."""
    return f"pagomovil:{details['bank_code']}:{details['phone']}:{details['cedula']}"


# ------------------------------------------------------------------ before the order: read, then pay

def pay_first(step, browser, seen, order, approved, amount, again='ready_to_order'):
    """The approved order's final button is on screen and is NOT pressed: its Pago Móvil step is read and paid.
    `again` is the tool the driver names it with (a booking's is ready_to_pay)."""
    from .runner import same_page
    task = step.task
    rail = countries.rail(task.country)
    details, why = read(task, seen, browser.capture(browser.target), step.meter)
    if not why and Decimal(details['amount_ves']) != amount:
        why = 'amount'
    if why:
        if operate.count(task, 'unread') >= operate.MAX_UNREAD:
            return step.stop('pay_unread')
        return step.remember(again, f'refused: the store\'s Pago Móvil data for exactly this total is not '
                                    f'readable on this page ({why}). Choose Pago Móvil so the store shows its '
                                    f'data, then call {again} again',
                             counts=operate.counted(task, 'unread'), order={**order, 'approved': approved})
    shown = {key: value for key, value in details.items() if key != 'refs'}
    if set(details['asks']) - REPORTABLE:
        # The store matches its payment by the payer: Confío's payout carries none of the person's.
        return step.stop('payer_data', order={**order, 'approved': None, 'pagomovil': shown})
    if 'reference' not in details['asks']:
        return step.stop('payer_data', order={**order, 'approved': None, 'pagomovil': shown})
    # Money may move from here: an order may follow, so a new purchase never sets this one aside.
    step.save(order={**order, 'approved': None, 'pay_first': True, 'pagomovil': shown,
                     'pay_page': same_page(seen.url)}, phase='paying', checkout_at=timezone.now(),
              history=[*(task.history or []), {'did': 'read the Pago Móvil step', 'result': 'paying it'}
                       ][-step.HISTORY_KEPT:], steps=task.steps + 1, failures=0)
    return step.pay_read(rail, code_of(details), request_of(details))


# ------------------------------------------------------------------ after paying: report the reference

# A booking's dates, room and guest form live only in its browser session: kept open from the Pago Móvil step
# through the payment, so the reference is typed on that very tab. A payment that outlives it is not made.
SESSION_LEFT = timedelta(minutes=10)


def keeps_session(task):
    return getattr(task, 'kind', 'buy') == 'reserve' and bool((task.order or {}).get('pay_first'))


def pay_window():
    """How long a booking's session must still last when it is paid: the slowest payout the funding leg waits for
    (settled, then parked for review: each up to VE_PURCHASE_PAYOUT_WAIT_MINUTES), and the report after it."""
    from payment_accounts import purchase_funding_ve
    return 2 * purchase_funding_ve._payout_wait() + timedelta(minutes=20)


def session_alive(task, left=SESSION_LEFT):
    return bool(task.session_id) and task.session_expires_at is not None \
        and task.session_expires_at > timezone.now() + left


def reporting(task):
    return task.phase == 'report'


def report_step(step, browser, reader, seen):
    task = step.task
    order = task.order or {}
    step.operating = True
    if (order.get('guest_typed') or ()) and getattr(task, 'kind', 'buy') == 'reserve':
        # A booking's form holds her details: no model reads them, in the text, a control or a picture.
        from .reserve import _hide
        _hide(seen, task)
        seen.look = None
    else:
        seen.look = reader.picture
    operate._trace(step, seen)
    if operate.count(task, 'report_steps') >= int(conf.get('AGENT_TASKS_REPORT_STEPS')):
        return retry(step, 'too_long')
    counts = operate.counted(task, 'report_steps')
    pressed = bool((order.get('report') or {}).get('pressed'))
    name, args = agent.report(task, seen, step.meter, after=pressed)
    if name == 'wait':
        step.delay = 2
        return step.remember('wait', 'ok', counts=counts)
    if name == 'give_up':
        return retry(step, 'gave_up')
    if pressed and name == 'order_placed':
        try:
            is_it, why = agent.placed(task, seen, step.meter)
        except agent.AgentUnavailable:
            is_it, why = False, 'the check could not run'
        if not is_it:
            return step.remember('order_placed', f'refused: not the store\'s confirmation ({why})', counts=counts)
        return done(step)
    if pressed:
        return step.remember(f'{name}'[:30], 'refused: the reference was sent; nothing else is pressed', counts=counts)
    if name == 'sign_in':
        signed = operate.sign_in(step, browser, reader, seen, asked=True)
        if signed is operate.NOT_A_FORM:
            return step.remember('sign_in', 'refused: no sign-in form on this page', counts=counts)
        return signed
    element = seen.element(args.get('ref'))
    if element is None or element.get('disabled'):
        return step.remember(f'{name}'[:30], 'refused: no such control on this page', counts=counts)
    if name == 'payment_step':
        return _submit(step, browser, reader, seen, element, counts)
    if name != 'press':
        return step.remember(f'{name}'[:30], 'refused', counts=counts)
    return _press(step, reader, seen, element, counts)


def _press(step, reader, seen, element, counts):
    """A press on the way back to the step: only one the judge calls safe. Never the person's to decide here."""
    task = step.task
    label = guard.clean(agent.redact(element.get('label')), 70)
    did = f'press "{label}"'
    if element.get('tag') == 'a' and not guard.toggle_link(element.get('href')) \
            and not sites.within(element.get('href') or '', task.site, house=True):
        return step.remember(did, 'refused: it leaves the store', counts=counts)
    try:
        verdict, why = agent.judge(task, seen, element, step.meter)
    except agent.AgentUnavailable:
        verdict, why = 'unsure', 'the check could not run'
    if verdict != 'safe':
        hint = ' Name it with payment_step.' if verdict == 'places_order' else ''
        return step.remember(did, f'refused: {verdict} ({why}).{hint}', counts=counts)
    where = step.fingerprint(seen.url)
    if sum(entry.get('at') == where and entry.get('did') == did[:120] for entry in (task.history or [])[-8:]) \
            >= operate.MAX_SAME_PRESS:
        return step.remember(did, 'refused: already pressed twice here; do something else', counts=counts)
    history = [*(task.history or []), {'did': did[:120], 'result': 'pressed', 'at': where}][-step.HISTORY_KEPT:]
    step.save(history=history, steps=task.steps + 1, failures=0, counts=counts)
    refused = reader.click(element)
    if refused:
        step.save(history=history[:-1])
        return step.remember(did, f'refused: {refused}', counts=counts)
    step.delay = 2
    return None


def _typed_value(ask, paid, details, field):
    if ask == 'reference':
        return str(paid.get('reference') or '')
    if ask == 'amount':
        return re.sub(r'[^\d.,]', '', details.get('amount_text') or '')
    when = paid.get('paid_at')
    try:
        moment = datetime.fromisoformat(str(when)) if when else timezone.now()
    except ValueError:
        moment = timezone.now()
    from zoneinfo import ZoneInfo
    if timezone.is_aware(moment):
        moment = moment.astimezone(ZoneInfo('America/Caracas'))
    return moment.strftime('%Y-%m-%d' if field.get('type') == 'date' else '%d/%m/%Y')


def _submit(step, browser, reader, seen, element, counts):
    """The paid order's Pago Móvil step: read again, the same store data and the bolívares that were paid,
    the reference typed by code into the field the reader named, the final button pressed once."""
    from .runner import same_page
    task = step.task
    order = task.order or {}
    paid = order.get('paid') or {}
    details, why = read(task, seen, browser.capture(browser.target), step.meter)
    if why:
        return step.remember('payment_step', f'refused: the Pago Móvil step could not be read here ({why})',
                             counts=counts)
    before = order.get('pagomovil') or {}
    try:
        paid_ves = Decimal(str(paid.get('paid_ves')))
    except (InvalidOperation, TypeError):
        paid_ves = None
    if paid_ves is None or Decimal(details['amount_ves']) != paid_ves:
        return step.stop('report_failed', order={**order, 'report_why': 'amount'})
    if any(details[key] != before.get(key) for key in ('bank_code', 'phone', 'cedula')):
        return step.stop('report_failed', order={**order, 'report_why': 'payee'})
    if set(details['asks']) - REPORTABLE or 'reference' not in details['asks']:
        return step.stop('report_failed', order={**order, 'report_why': 'fields'})
    try:
        amount = Decimal(str(order.get('amount')))
    except (InvalidOperation, TypeError):
        return step.stop('report_failed', order={**order, 'report_why': 'amount'})
    cart = operate.chosen_cart(task)
    item = operate._review_list(cart) if cart else str(order.get('item') or '')
    reviewed, why = operate._reviewed(step, seen, element, item, amount)
    if reviewed is None:
        return step.remember('payment_step', f'refused: {why}', counts=counts)
    if order.get('address') and not operate.written_on(seen.text, order.get('address')):
        return step.remember('payment_step', 'refused: the delivery address is not the one the person approved',
                             counts=counts)
    step.save(counts=counts)
    for ask in ('reference', 'date', 'amount'):
        if ask not in details['asks']:
            continue
        field = seen.element(details['refs'].get(ask))
        if field is None or field.get('tag') not in ('input', 'textarea') or field.get('disabled') \
                or str(field.get('type') or '') not in _TYPABLE:
            return step.remember('payment_step', f'refused: the {ask} field could not be found', counts=counts)
        refused = reader.type(field, _typed_value(ask, paid, details, field))
        if refused:
            return step.remember('payment_step', f'refused: the {ask} was not typed ({refused})', counts=counts)
    label = guard.clean(agent.redact(element.get('label')), 70)
    # Written down first: an answer lost on the way is never a second report.
    step.save(order={**order, 'report': {'pressed': True, 'at': same_page(seen.url)}},
              history=[*(task.history or []), {'did': f'sent the reference with "{label}"',
                                               'result': order.get('total') or ''}][-step.HISTORY_KEPT:],
              steps=task.steps + 1, failures=0)
    refused = reader.click(element)
    if refused:
        return step.save(order={**order, 'report': {}},
                         history=[*(task.history or []), {'did': 'the final button', 'result': f'not pressed: {refused}'}
                                  ][-step.HISTORY_KEPT:])
    browser.pump(4)
    return None


def done(step):
    from .runner import close_session
    task = step.task
    step.save(state='payment_ready', reason='reported', wait_until=None)
    close_session(task)
    text = notes.reported_text(task)
    notes.post(task, text, 'reported', push='payment', push_body=notes.say(notes.REPORTED_PUSH, task))


def retry(step, why):
    """This session could not report it: a fresh one, a few times. Never after the final press (a second
    submit could be a second order): then, and after the last try, the person reports it (report_failed)."""
    from .runner import Lost, close_session
    task = step.task
    tries = operate.count(task, 'report_tries') + 1
    logger.info('agent task %s: report try %s ended: %s', task.internal_id, tries, why)
    if (task.order or {}).get('report', {}).get('pressed') or tries >= int(conf.get('AGENT_TASKS_MAX_REPORT_TRIES')):
        return step.stop('report_failed', order={**(task.order or {}), 'report_why': str(why)[:40]})
    close_session(task)
    try:
        step.save(state='queued', reason='', wait_until=None, session_id='', connect_url='', session_expires_at=None,
                  counts={**(task.counts or {}), 'report_tries': tries, 'report_steps': 0},
                  order={**(task.order or {}), 'kept_tab': False})   # a fresh session opens the site again
    except Lost:
        raise
    step.delay = 30
    return None


def alert(task, reason):
    """Paid at the store and not reported: ops are told with what the person was told."""
    paid = (task.order or {}).get('paid') or {}
    try:
        from config.ops_alerts import send_ops_alert
        send_ops_alert(f'Compra VE {task.internal_id} en {task.site}: pagada por Pago Móvil (ref '
                       f"{paid.get('reference') or '?'}, Bs {paid.get('paid_ves') or '?'}) y no reportada a la tienda "
                       f'({reason}). La persona recibió los datos para reportarla.',
                       dedupe_key=f'agent_report_failed:{task.pk}', dedupe_seconds=86400)
    except Exception:  # noqa: BLE001 - the person is told either way
        logger.exception('agent report alert failed')
