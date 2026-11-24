"""The agent signs in, does the checkout and places the order (founder,
2026-11-23: the person approves in the chat and is never sent to the store).

Real clicks, typing and the final button happen only here. Models read and decide; code checks facts
(founder, 2026-11-24: "give authority to decide for the judge model"). No word or address of a store's is
matched to decide what may be pressed.

  sign_in   on the store's own site only. The runner types the saved sign-in into the very field that
            holds the focus (a password only into a password field). No model sees it.
  checkout  the model that drives picks one control at a time; a second model (agent.judge) reads that
            press on that page and decides: safe is pressed; placing the order, a card, the account are
            not; unsure asks the person about that one step.
  _order    the button the driver names as final. A second model (agent.review) reads the page: is it the
            button that places the order, how is it paid, the total, the item, where it goes. Code checks
            the facts: both models read the same sum and it is written on the page; the address is on the
            page; the person approved this item, total, address and payer. Pressed once.
  after     once ordered, links the judge calls safe; a second model (agent.payment_page) says whether a
            page is the order's own payment page; what is paid is read by code (runner.after_checkout):
            one valid CLABE or the provider-checked QR, for exactly the approved amount, on a page new
            since the order.

What the checks rely on (phase, counts, the order and its approval) is kept
in columns of the task, never in its rolling history.
"""
import logging
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from django.utils import timezone

from . import agent, guard, notes, sites, vault

logger = logging.getLogger(__name__)

NOT_A_FORM = object()   # nothing to sign in to here: the caller goes on
MAX_SIGN_INS = 2        # full tries (a password typed) with one saved sign-in
MAX_ASKS = 2            # times the person is asked for their sign-in or a code
MAX_SAME_PRESS = 2
MAX_UNREAD = 3

_IDENTIFIER = re.compile(r'\b(e-?mail|correo|usuario|user(name)?|login|celular|telefono|phone|movil|cpf)\b')
_CODE = re.compile(r'\b(otp|verificacion|verification|codigo de (verificacion|seguridad|acceso)|security code)\b')
_NOT_A_CODE = re.compile(r'postal|cupon|coupon|promo|zip|cep|descuento|desconto|cvv|cvc|tarjeta|card')
_PAYMENT_FIELD = re.compile(r'cvv|cvc|tarjeta|cartao|card|vencimiento|expir')
_SUBMIT = re.compile(r'\b(continuar|continue|siguiente|next|entrar|ingresar|iniciar sesion|sign in|log in|acceder'
                     r'|verificar|verify|enviar|confirmar codigo)\b')
# Another way in (another account, another site): never the form's own button.
_ELSEWHERE = re.compile(r'\b(google|apple|facebook|microsoft|outlook|cuenta nueva|crear cuenta|criar conta'
                        r'|create account|registr\w*|cadastr\w*)\b')
# The approved order's final button: once, and once more when the store's last press only moved on a step.
MAX_FINAL_PRESSES = 2


def count(task, what):
    return int((task.counts or {}).get(what) or 0)


def counted(task, what):
    """The task's counts with one more of `what` (to save with the step)."""
    return {**(task.counts or {}), what: count(task, what) + 1}


def ordering(task):
    """From the cart on: the agent works the checkout."""
    return task.phase in ('ordering', 'ordered')


def ordered(task):
    return task.phase == 'ordered' or task.checkout_at is not None


def amount_of(text):
    """The number in a total as a store writes it ('R$ 1.234,56', '$1,249.00'), or None."""
    found = re.search(r'\d[\d.,]*\d|\d', str(text or ''))
    if not found:
        return None
    raw = found.group(0)
    if ',' in raw and '.' in raw:
        cut = max(raw.rfind(','), raw.rfind('.'))
    elif raw.count(',') == 1 and len(raw) - raw.rfind(',') == 3:
        cut = raw.rfind(',')
    elif raw.count('.') == 1 and len(raw) - raw.rfind('.') == 3:
        cut = raw.rfind('.')
    else:
        cut = -1
    whole = re.sub(r'[.,]', '', raw[:cut] if cut >= 0 else raw)
    try:
        return Decimal(f"{whole}.{raw[cut + 1:] if cut >= 0 else '00'}")
    except InvalidOperation:
        return None


def figure_on(page_text, amount):
    """A fact, not a reading: that amount is written on the page."""
    return amount is not None and any(amount_of(found.group(0)) == amount
                                      for found in re.finditer(r'\d[\d.,]*\d|\d', str(page_text or '')[:100000]))


def written_on(page_text, words):
    """A fact: those words are on the page as written (case, accents and spacing aside)."""
    squeeze = lambda value: re.sub(r'\s+', ' ', guard.fold(str(value or ''))).strip()  # noqa: E731
    return bool(squeeze(words)) and squeeze(words) in squeeze(str(page_text or '')[:100000])


# ------------------------------------------------------------------ sign-in

def _fields(seen):
    """(identifier, password, code) inputs on screen, each or None; None for all on a page with payment fields."""
    identifier = password = code = None
    for element in seen.elements:
        if element.get('tag') != 'input' or element.get('disabled') or not element.get('on_screen', True):
            continue
        kind, auto = element.get('type') or 'text', (element.get('autocomplete') or '')
        words = guard.fold(f"{element.get('name')} {element.get('label')}")
        if auto.startswith('cc-') or _PAYMENT_FIELD.search(words):
            return None, None, None   # a payment form: never a place for a sign-in
        if element.get('search'):
            continue
        if kind == 'password':
            password = password or element
        elif auto.split()[-1:] == ['one-time-code'] or (
                kind in ('text', 'tel', 'number') and _CODE.search(words) and not _NOT_A_CODE.search(words)
                and 0 < int(element.get('maxlength') or 0) <= 8):
            code = code or element
        elif kind in ('email', 'text', 'tel') and (
                auto.split()[-1:] in (['username'], ['email'], ['tel']) or kind == 'email' or _IDENTIFIER.search(words)):
            identifier = identifier or element
    return identifier, password, code


def _submit(seen):
    """The sign-in form's own button, never one that buys."""
    for element in seen.elements:
        parts = guard._parts(element)
        if (element.get('tag') == 'button' or (element.get('tag') == 'input' and element.get('type') == 'submit')) \
                and element.get('on_screen', True) and not element.get('disabled') \
                and not guard.final_looking(element) and element.get('action') \
                and any(_SUBMIT.search(part) for part in parts) and not any(_ELSEWHERE.search(p) for p in parts):
            return element
    return None


def sign_in(step, browser, reader, seen, asked=False):
    """Type the person's sign-in (or the code the store sent) into the store's
    own sign-in page. NOT_A_FORM when this is not one. `asked`: the model that
    drives the checkout read the page as the store asking for it."""
    task = step.task
    # Always a fact: the store's own site, never outside it.
    if not sites.within(seen.url, task.site):
        return NOT_A_FORM
    # Unasked, only at an address known as a sign-in. Asked, wherever the store put its form.
    if not asked and (not guard.login_address(seen.url) or guard.is_checkout(seen)):
        return NOT_A_FORM
    if re.search(r'regist|cadastr|signup|sign-up', urlsplit(seen.url).path.lower()):   # never a sign-up form
        return NOT_A_FORM
    identifier, password, code = _fields(seen)
    if password is not None and 0 < int(password.get('maxlength') or 0) <= 4:
        return NOT_A_FORM   # four hidden characters are a card's code, never a password
    if identifier is None and password is None and code is None:
        return NOT_A_FORM
    step.operating = True
    button = _submit(seen)
    if code is not None and password is None and identifier is None:
        typed = vault.take_code(task)
        if not typed:
            if count(task, 'asked_otp') >= MAX_ASKS:
                return step.stop('sign_in')
            return step.hand_over('otp', counts=counted(task, 'asked_otp'))
        step.save()
        refused = reader.type(code, typed) or (reader.click(button) if button else _enter(browser))
        return step.remember('typed the code', f'refused: {refused}' if refused else 'sent')
    saved = vault.get(task.user, task.site)
    if saved is not None and count(task, 'sign_ins') >= MAX_SIGN_INS:
        # It did not let us in with that: forgotten, and asked again.
        vault.forget(task.user, task.site)
        saved = None
    if saved is None:
        asked = count(task, 'asked_login')
        if asked >= MAX_ASKS:
            return step.stop('sign_in')
        return step.hand_over('login', body=notes.say(notes.NEEDS_PERSON['login_again' if asked else 'login'], task),
                              counts={**counted(task, 'asked_login'), 'sign_ins': 0})
    step.save()
    refused = ''
    if identifier is not None:
        refused = reader.type(identifier, saved['identifier'])
    if not refused and password is not None:
        refused = reader.type(password, saved['password'], secret=True)
    if not refused:
        refused = reader.click(button) if button else _enter(browser)
    # A try counts once the password was sent (an identifier-first page is half of one).
    counts = counted(task, 'sign_ins') if password is not None and not refused else (task.counts or {})
    return step.remember('typed the sign-in', f'refused: {refused}' if refused else 'sent', counts=counts)


def _enter(browser):
    browser.enter()
    browser.settle()
    return ''


# ----------------------------------------------------------------- checkout

def _label(element):
    return guard.clean(agent.redact(element.get('label')), 70)


def checkout(step, browser, reader, seen):
    """One step from the cart to the order, or after it. The model that drives reads the page and chooses;
    a second model reads each press (agent.judge) and the order itself (agent.review). Code decides nothing
    by a store's words: it checks facts (the store's own site, what the person approved, the figures)."""
    from . import service
    task = step.task
    step.operating = True
    after = ordered(task)
    seen.look = reader.picture   # what the second readers see: the page, with the control boxed
    if not ordering(task):
        try:
            # Nobody is asked to approve an order they could not pay here.
            service.require_payable(task.account, task.user, task.country, step.app_meta())
        except service.TaskRefused:
            return step.stop('cannot_pay')
        step.save(phase='ordering')
    _trace(step, seen)
    if not after:
        # Accounts written on pages before the order exists are never the order's own (spei._by_facts).
        from . import spei
        known = (task.order or {}).get('seen_clabes') or []
        found = spei.clabes_in([seen.text]) - set(known)
        if found:
            step.save(order={**(task.order or {}), 'seen_clabes': [*known, *sorted(found)][-40:]})
    name, args = agent.operate(task, seen, step.meter, after=after)
    if name == 'wait':
        step.delay = 2
        return step.remember('wait', 'ok')
    if name == 'give_up':
        reason = args.get('reason')
        return step.stop(reason if reason in step.GIVE_UP else 'cannot_do')
    if name == 'sign_in' and not after:
        done = sign_in(step, browser, reader, seen, asked=True)
        return step.remember('sign_in', 'refused: no sign-in form on this page') if done is NOT_A_FORM else done
    if name == 'order_placed' and not after:
        # The store says an order exists and nobody named it: said as it is, never paid as an approved one.
        return step.remember('the store shows an order as placed', 'not approved here', phase='ordered',
                             checkout_at=timezone.now(), order={**(task.order or {}), 'unapproved': True})
    if name == 'payment_shown' and after:
        if not sites.house_ticket(seen.url, task.site) and not sites.within(seen.url, task.site):
            return step.remember('payment_shown', 'refused: this is not the store\'s own page')
        try:
            # A second reader, apart from the one that drives: the store's own page for this order, never a
            # page a seller writes on. What is paid is then read by code off the screen.
            is_it, why = agent.payment_page(task, seen, step.meter)
        except agent.AgentUnavailable:
            is_it, why = False, 'the check could not run'
        if not is_it:
            return step.remember('payment_shown', f'refused: not this order\'s payment page ({why})')
        # The runner reads it off this tab, as it is on screen. No model reads a payment.
        return step.save(state='awaiting_code', reason='', shown_target=browser.target)
    element = seen.element(args.get('ref'))
    # Off screen is fine: the real click scrolls it into view and refuses it if anything covers it.
    if element is None or element.get('disabled'):
        return step.remember(f'{name}'[:30], 'refused: no such control on this page')
    label = _label(element)
    if name == 'ready_to_order' and not after:
        return _order(step, browser, reader, seen, element, label, args)
    if name == 'not_placed' and after:
        return _again(step, browser, reader, seen, element, label)
    if name != 'press':
        return step.remember(f'{name}'[:30], 'refused')
    did = f'press "{label}"'
    if element.get('tag') == 'a' and not guard.toggle_link(element.get('href')) \
            and not sites.within(element.get('href') or '', task.site, house=True):
        return step.remember(did, 'refused: it leaves the store')
    where = step.fingerprint(seen.url)
    allowed = (task.order or {}).get('allowed_step') or {}
    if allowed:
        # A yes is for the very next step only: used now or gone.
        step.save(order={**(task.order or {}), 'allowed_step': None})
    if allowed and not after and allowed == _identity(element, label, where):
        pass   # the person said yes to this very control on this very page ("¿Lo hago?")
    elif _judged(step, seen, element, label, did, where, after) is REFUSED:
        return None
    if sum(entry.get('at') == where and entry.get('did') == did[:120] for entry in (task.history or [])[-8:]) \
            >= MAX_SAME_PRESS:
        return step.remember(did, 'refused: already pressed twice here; do something else')
    history = [*(task.history or []), {'did': did[:120], 'result': 'pressed', 'at': where}][-step.HISTORY_KEPT:]
    if (task.order or {}).get('approved') and not after:
        # Anything pressed after the person approved may change what is bought: asked again at the final button.
        step.save(order={**(task.order or {}), 'approved': None})
    step.save(history=history, steps=task.steps + 1, failures=0)
    refused = reader.click(element)
    if refused:
        step.save(history=history[:-1])   # it never happened: not counted as a press of this control
        return step.remember(did, f'refused: {refused}')
    browser.pump(2)


REFUSED = object()


TRACE_KEPT = 12


def _trace(step, seen):
    """What this page held, as the browser read it: its address (no query), its controls, a little text."""
    parts = urlsplit(seen.url or '')
    page = {'url': f'{parts.hostname or ""}{parts.path[:200]}', 'title': str(seen.title or '')[:120],
            'text': agent.redact(seen.text[:1500]),
            'elements': [{key: (str(element.get(key))[:120] if key != 'href' else urlsplit(str(element.get(key) or '')).path[:120])
                          for key in ('ref', 'label', 'tag', 'type', 'role', 'href', 'checked', 'disabled', 'on_screen')
                          if element.get(key) not in (None, '')} for element in seen.elements[:150]]}
    step.save(trace=[*(step.task.trace or []), page][-TRACE_KEPT:])


def _identity(element, label, where):
    """What a yes is for: this control (its words, kind and target) on this page."""
    return {'label': label[:120], 'at': where, 'tag': str(element.get('tag') or ''), 'type': str(element.get('type') or ''),
            'href': urlsplit(str(element.get('href') or '')).path[:200]}


def _judged(step, seen, element, label, did, where, after=False):
    """None to press it, REFUSED when it was refused (and said so). The judge model decides: it reads the
    page and this one control, apart from the model that drives. No word of the store's is matched here."""
    try:
        verdict, why = agent.judge(step.task, seen, element, step.meter)
    except agent.AgentUnavailable:
        verdict, why = 'unsure', 'the check could not run'
    if verdict == 'safe':
        return None
    if after:
        step.remember(did, f'refused: {verdict} ({why}). Only the way to this order\'s payment page; if the store '
                           'did not place the order yet, call not_placed with its button.')
        return REFUSED
    if verdict == 'places_order':
        step.remember(did, f'refused: it places or pays the order ({why}). Call ready_to_order with it.')
        return REFUSED
    if verdict in ('card', 'account', 'request'):   # a request about an order is manage.py's, never a purchase's
        step.remember(did, f'refused: {why}. Never a card nor anything about the account: find another way.')
        return REFUSED
    # Unsure: never a dead end. The person says yes or no in the chat, once, for this very step.
    step.hand_over('step', order={**(step.task.order or {}), 'ask_step': _identity(element, label, where)},
                   body=notes.say(notes.NEEDS_PERSON['step'], step.task).replace('{step}', label[:80]))
    return REFUSED


_NOT_A_BUTTON = ('radio', 'checkbox', 'text', 'email', 'password', 'hidden', 'tel', 'number', 'search')


def _reviewed(step, seen, element, item, amount):
    """(the second model's reading, '') when it and the facts agree this button places this very order:
    this item and only it, paid the asked way, for exactly `amount`. Else (None, why)."""
    if element.get('tag') == 'a' and not guard.toggle_link(element.get('href')) \
            and not sites.within(element.get('href') or '', step.task.site, house=True):
        return None, 'it leaves the store'
    if element.get('type') in _NOT_A_BUTTON:
        return None, 'that is not a button'
    try:
        read = agent.review(step.task, seen, element, item, step.meter)
    except agent.AgentUnavailable:
        return None, 'the check could not run: try again'
    if not read['places_order']:
        return None, f'the second reader does not see it as the button that places the order ({read["why"]})'
    if amount is None or amount <= 0 or amount_of(read['total']) != amount or not figure_on(seen.text, amount):
        return None, f'the total must be the whole sum the page says the person pays (read there: "{read["total"]}")'
    if read['pays_with'] != 'asked':
        return None, (f'the order is not set to be paid the right way ({read["pays_with"]}: {read["why"]}). '
                      'Choose the right payment method first, never a card.')
    if not read['item_shown']:
        return None, f'the order must hold the item and only it ({read["why"]})'
    return read, ''


BREAKDOWN_KINDS = ('products', 'shipping', 'tax', 'discount', 'fee', 'other')


def breakdown(read, page_text, amount):
    """What makes up the total, as the second reader listed it: kept only when every figure is written on the
    page and they add up to exactly the total (a discount takes away). Else [] (the card shows the total alone)."""
    lines, sum_ = [], Decimal(0)
    for line in read.get('lines') or []:
        figure = amount_of(line.get('amount'))
        if line.get('kind') not in BREAKDOWN_KINDS or figure is None or not figure_on(page_text, figure):
            return []
        sum_ += -figure if line['kind'] == 'discount' else figure
        lines.append({'kind': line['kind'], 'amount': guard.clean(line['amount'], 24)})
    return lines if len(lines) >= 2 and sum_ == amount else []


def _order(step, browser, reader, seen, element, label, args):
    """The final button, named with the order's total. A second model reads the page (agent.review); code
    checks the facts; the person approves the purchase once; it is pressed only for what they approved."""
    from . import service
    task = step.task
    picked = (task.options or [{}])[0] if len(task.options or []) == 1 else {}
    approved = (task.order or {}).get('approved') or {}
    # The item the person approved stands (a model never words it twice the same); the reader checks it.
    item = picked.get('title') or approved.get('item') or guard.clean(agent.redact(args.get('item')), 120)
    if not item:
        return step.remember('ready_to_order', 'refused: name the item')
    total = guard.clean(agent.redact(args.get('total')), 40)
    amount = amount_of(total)
    read, why = _reviewed(step, seen, element, item, amount)
    if read is None:
        return step.remember('ready_to_order', f'refused: {why}')
    # Where it goes: what the second model copied, kept only if the page really writes it. Once approved,
    # the approved address stands while the page still writes it (a model never words it twice the same).
    if approved.get('address') and written_on(seen.text, approved.get('address')):
        address = approved['address']
    else:
        address = read['ship_to'] if written_on(seen.text, read['ship_to']) else ''
    where = step.fingerprint(seen.url)
    order = {'item': item, 'total': total, 'amount': format(amount, 'f'), 'button': label, 'page': where,
             'image': picked.get('image', ''), 'address': address,
             'breakdown': breakdown(read, seen.text, amount),
             'seen_clabes': (task.order or {}).get('seen_clabes') or []}
    # Who pays it is part of what they approve: said before they confirm, and asked again if it changed.
    mode, offer = service.pay_mode(task, step.app_meta())
    order = {**order, 'manual': mode == 'manual', 'offer': offer}
    # What the person approves is the purchase: this item, this total, this address, who pays.
    if not approved or amount_of(approved.get('total')) != amount or {
            key: approved.get(key) for key in ('item', 'manual', 'address')} != {
            'item': item, 'manual': mode == 'manual', 'address': address}:
        # A new order, or one that changed: the person is asked (again). Its note is fixed words:
        # what the store wrote is shown only on the card.
        return step.hand_over('approve', order=order, body=notes.say(
            notes.NEEDS_PERSON['approve_manual' if mode == 'manual' else 'approve'], task) + notes.breakdown_text(order))
    # Used once, and written down first: an answer lost on the way is never a second order.
    step.save(order={**order, 'pressed': True, 'pressed_at': [step.same_page(seen.url)]}, phase='ordered',
              checkout_at=timezone.now(),
              history=[*(task.history or []), {'did': 'pressed the final button', 'result': total}][-step.HISTORY_KEPT:],
              steps=task.steps + 1, failures=0)
    refused = reader.click(element)
    if refused:
        # Not clicked (covered, gone): no mouse event reached it, so no order. It keeps its approval.
        return step.save(order={**order, 'approved': approved}, phase='ordering', checkout_at=None,
                         history=[*(task.history or []), {'did': 'the final button', 'result': f'not pressed: {refused}'}
                                  ][-step.HISTORY_KEPT:])
    # Clicked: this page is never pressed on again (a slow store still places it). The order's pages are
    # looked for; if the store shows one more step for the same order instead, see _again.
    browser.pump(4)


def _again(step, browser, reader, seen, element, label):
    """The approved order's button led only to the store's next step ("Continuar" on its last page): the
    store's own final button on another page, for the same item, total and address. A page the order was
    pressed on is never pressed on again, whatever its button says by then (a slow store, a reload)."""
    task = step.task
    order = task.order or {}
    where = step.same_page(seen.url)
    pressed_at = order.get('pressed_at') or []
    if not order.get('pressed') or order.get('unapproved') or where in pressed_at \
            or len(pressed_at) >= MAX_FINAL_PRESSES:
        return step.remember('not_placed', 'refused: this order\'s button was already pressed: never twice. '
                                           'Find its payment page, or give_up.')
    try:
        amount = Decimal(str(order.get('amount')))
    except InvalidOperation:
        amount = None
    read, why = _reviewed(step, seen, element, order.get('item') or '', amount)
    if read is not None and order.get('address') and not written_on(seen.text, order.get('address')):
        read, why = None, 'the delivery address is not the one the person approved'
    if read is None:
        return step.remember('not_placed', f'refused: not the order the person approved ({why})')
    step.save(order={**order, 'pressed_at': [*pressed_at, where]}, checkout_at=timezone.now(),
              history=[*(task.history or []), {'did': f'pressed "{label}" (the approved order)',
                                               'result': order.get('total')}][-step.HISTORY_KEPT:],
              steps=task.steps + 1, failures=0)
    refused = reader.click(element)
    if refused:
        return step.save(order={**(step.task.order or {}), 'pressed_at': pressed_at},
                         history=[*(task.history or []), {'did': 'the final button', 'result': f'not pressed: {refused}'}
                                  ][-step.HISTORY_KEPT:])
    browser.pump(4)
