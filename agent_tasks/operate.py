"""The agent signs in, does the checkout and places the order (founder,
2026-11-23: the person approves in the chat and is never sent to the store).

Real clicks, typing and the final button happen only here, and what may be
done is decided by code, never by what a model was told:

  sign_in   only on the store's own sign-in address. The runner types the
            saved sign-in into the very field that holds the focus (a
            password only into a password field). No model sees it.
  checkout  a model picks one control at a time. On a checkout page it may
            click a choice, a link, or a button whose words are on a short
            list (guard.may_press); any other button there may be the one
            that buys, so it can only be *named*, with the total.
  _order    the named button is clicked only when: the page is a checkout,
            the store's local payment method is the selected one and no
            card is, the total stands beside a "total" label, and the
            person approved that item, that total, on that page. The
            approval is used once.
  after     once ordered, the model may only open the order's own pages; the
            payment data is read by the runner (runner.after_checkout) and
            must be for the approved total.

What the checks rely on (phase, counts, the order and its approval) is kept
in columns of the task, never in its rolling history.
"""
import logging
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin, urlsplit

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
# Where a checkout shows the way to pay it chose (Amazon's review page shows it as text).
_METHOD_LABEL = re.compile(r'(metodo|forma|medio|meio) de (pago|pagamento)|payment method|pagar con|pagando con')
# The country's own way to pay, as a checkout names it.
RAIL_WORDS = {'BR': re.compile(r'\bpix\b'), 'MX': re.compile(r'\b(spei|transferencia)\b'), 'BO': re.compile(r'\bqr\b')}


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


# What a checkout writes beside the sum the person pays.
_TOTAL_LABEL = re.compile(r'(?<!sub)\btotal\b|\bvoce pagara\b|\bpagaras\b|\bvas a pagar\b|\bvai pagar\b')
# A checked option naming another way to pay: the page's text never outweighs it.
_OTHER_METHOD = re.compile(r'\b(oxxo|boleto|efectivo|dinheiro|deposito|paypal|mercado ?pago|saldo|cuotas|parcel\w*'
                           r'|seven|7-eleven|kueski|aplazo|paycash|pse|nequi|yape|tigo|lotérica|loterica'
                           r'|contra ?entrega|cash)\b')
_GRAND_TOTAL =re.compile(r'\b(total (del pedido|de la orden|da compra|do pedido|a pagar|da sua compra|de tu compra)'
                          r'|order total|valor total|importe total|voce pagara|pagaras|vas a pagar|vai pagar)\b')


def total_on(page_text, total):
    """`total` is the page's grand total: the figure right after the LAST total-like label
    (a "Total de productos" or a "Total" before a discount is not the sum the person pays)."""
    text = guard.fold(page_text[:100000])
    amount = amount_of(total)

    def figures(labels):
        found = []
        for label in labels.finditer(text):
            # "Total (2 productos): $500": a count in brackets is not the figure.
            after = re.sub(r'\([^)]{0,30}\)', ' ', text[label.end():label.end() + 90])
            figure = re.match(r'[^\d]{0,40}?(\d[\d.,]*\d|\d)', after)
            if figure:
                found.append(amount_of(figure.group(1)))
        return found

    # A grand total's own words ("Total del pedido", "Você pagará"): every one of them must agree,
    # so a seller's title written with them is a second total and nothing is approved.
    strong = figures(_GRAND_TOTAL)
    if strong:
        return amount is not None and set(strong) == {amount}
    plain = figures(_TOTAL_LABEL)
    return amount is not None and bool(plain) and plain[-1] == amount


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


def sign_in(step, browser, reader, seen):
    """Type the person's sign-in (or the code the store sent) into the store's
    own sign-in page. NOT_A_FORM when this is not one."""
    task = step.task
    # Only the store's own sign-in address, reached by the store's own navigation: never a
    # checkout, never a page a seller could write on, never outside the store.
    if (not guard.login_address(seen.url) or guard.is_checkout(seen) or not sites.within(seen.url, task.site)
            or re.search(r'regist|cadastr|signup|sign-up', urlsplit(seen.url).path.lower())):   # never a sign-up form
        return NOT_A_FORM
    identifier, password, code = _fields(seen)
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
    """One step from the cart to the order, or after it: one control, or the order named for approval."""
    from . import service
    task = step.task
    step.operating = True
    after = ordered(task)
    on_checkout = guard.is_checkout(seen) or sites.within(seen.url, task.site, house=True) and not sites.within(
        seen.url, task.site)
    if not after and guard.order_placed(seen) and guard.order_address(seen.url) and on_checkout \
            and step.same_page(seen.url) not in (task.visited_pages or []):
        # The store says an order exists and nobody named it: said as it is, and its payment is looked for.
        return step.remember('the store shows an order as placed', 'not approved here', phase='ordered',
                             checkout_at=timezone.now(), order={**(task.order or {}), 'unapproved': True})
    if not ordering(task):
        try:
            # Nobody is asked to approve an order they could not pay here.
            service.require_payable(task.account, task.user, task.country, step.app_meta())
        except service.TaskRefused:
            return step.stop('cannot_pay')
        step.save(phase='ordering')
    name, args = agent.operate(task, seen, step.meter, after=after)
    if name == 'wait':
        step.delay = 2
        return step.remember('wait', 'ok')
    if name == 'give_up':
        reason = args.get('reason')
        return step.stop(reason if reason in step.GIVE_UP else 'cannot_do')
    if name == 'payment_shown' and after:
        if not guard.order_address(seen.url) or not sites.within(seen.url, task.site):
            return step.remember('payment_shown', 'refused: this is not the order\'s own page')
        # The runner reads it off this tab, as it is on screen. No model reads a payment.
        return step.save(state='awaiting_code', reason='', shown_target=browser.target)
    element = seen.element(args.get('ref'))
    if element is None or element.get('disabled') or not element.get('on_screen', True):
        return step.remember(f'{name}'[:30], 'refused: no such control on screen')
    label = _label(element)
    if name == 'ready_to_order' and not after:
        return _order(step, browser, reader, seen, element, label, args, on_checkout)
    if name != 'press':
        return step.remember(f'{name}'[:30], 'refused')
    did = f'press "{label}"'
    if element.get('tag') == 'a' and not sites.within(element.get('href') or '', task.site, house=True):
        return step.remember(did, 'refused: it leaves the store')
    if after:
        # Only the way to this order's pages: never a button, never anything that acts.
        if element.get('tag') != 'a' or not guard.may_press(element, on_checkout=False) \
                or guard.final_looking(element) \
                or not guard.order_address(urljoin(seen.url, element.get('href') or '')):
            return step.remember(did, 'refused: after the order only links to its pages may be opened')
    elif not guard.may_press(element, on_checkout=on_checkout):
        return step.remember(did, 'refused: not a control I may press here. If it places the order, '
                                  'call ready_to_order with it.')
    where = step.fingerprint(seen.url)
    if sum(entry.get('at') == where and entry.get('did') == did[:120] for entry in (task.history or [])[-8:]) \
            >= MAX_SAME_PRESS:
        return step.remember(did, 'refused: already pressed twice here; do something else')
    history = [*(task.history or []), {'did': did[:120], 'result': 'pressed', 'at': where}][-step.HISTORY_KEPT:]
    step.save(history=history, steps=task.steps + 1, failures=0)
    refused = reader.click(element)
    if refused:
        return step.remember(did, f'refused: {refused}')
    browser.pump(2)


def _method_refusal(task, seen):
    """'' when the store's local payment method is the one selected and no card is."""
    rail = RAIL_WORDS.get(task.country)
    if rail is None:
        return 'this store\'s country has no payment method here'
    chosen = [guard.fold(element.get('label')) for element in seen.elements if element.get('checked')]
    if any(guard.card_words(label) for label in chosen):
        return 'a card is selected: choose the local payment method'
    # Another way to pay ticked beside it (a balance, instalments): the order is not paid by the rail alone.
    if any(_OTHER_METHOD.search(label) and not rail.search(label) for label in chosen):
        return 'another payment method is selected: choose the local one'
    if any(rail.search(label) for label in chosen):
        return ''
    # A review page states the chosen method as text, beside its label: that block alone is read
    # (the rest of a page always offers cards, gift cards, instalments).
    text = guard.fold(seen.text[:100000])
    blocks = []
    for found in _METHOD_LABEL.finditer(text):
        if re.search(r'\b(cambiar|editar|alterar|change|modificar|trocar|elige|elegir|escolher|escolha|selecciona'
                     r'|seleciona|otro|outra|outro|otra|agregar|adicionar|add)\b\W*(el |la |o |a |tu |seu |sua )?$',
                     text[max(0, found.start() - 25):found.start()]):
            continue  # "Cambiar método de pago": a link, not the method
        block = text[found.end():found.end() + 120]
        # Only that method's own words: up to its "change" link or the next section's label.
        end = re.search(r'\b(cambiar|editar|alterar|change|modificar|trocar|total|subtotal|resumen|resumo|entrega)\b',
                        block)
        block = block[:end.start()] if end else block
        if re.search(r'[a-z]', block):
            blocks.append(block)   # an empty one is a heading whose method sits elsewhere
    if any(rail.search(block) for block in blocks) and not any(guard.card_words(block) for block in blocks):
        return ''
    return 'the local payment method is not the one selected'


def _order(step, browser, reader, seen, element, label, args, on_checkout):
    """The final button, named with the order's total. Asked of the person once;
    clicked only for what they approved, where they approved it."""
    task = step.task
    if not on_checkout or not guard.final_looking(element):
        return step.remember('ready_to_order', 'refused: that is not the final button of a checkout page')
    total = guard.clean(agent.redact(args.get('total')), 40)
    amount = amount_of(total)
    if amount is None or amount <= 0 or not total_on(seen.text, total):
        return step.remember('ready_to_order', 'refused: the total must be the figure beside the page\'s "total"')
    refused = _method_refusal(task, seen)
    if refused:
        return step.remember('ready_to_order', f'refused: {refused}')
    picked = (task.options or [{}])[0] if len(task.options or []) == 1 else {}
    item = picked.get('title') or guard.clean(agent.redact(args.get('item')), 120)
    words = [word for word in guard.fold(item).split() if len(word) >= 4][:6]
    if not item or (words and not any(word in guard.fold(seen.text[:100000]) for word in words)):
        return step.remember('ready_to_order', 'refused: the item is not on this page')
    where = step.fingerprint(seen.url)
    order = {'item': item, 'total': total, 'amount': format(amount, 'f'), 'button': label, 'page': where,
             'image': picked.get('image', '')}
    approved = (task.order or {}).get('approved') or {}
    if approved != {'total': total, 'button': label, 'page': where, 'item': item}:
        # A new order, or one that changed: the person is asked (again). Its note is fixed words:
        # what the store wrote is shown only on the card.
        return step.hand_over('approve', order=order)
    # Used once, and written down first: an answer lost on the way is never a second order.
    step.save(order={**order, 'pressed': True}, phase='ordered', checkout_at=timezone.now(),
              history=[*(task.history or []), {'did': 'pressed the final button', 'result': total}][-step.HISTORY_KEPT:],
              steps=task.steps + 1, failures=0)
    refused = reader.click(element)
    if refused:
        # Not clicked (covered, gone): no mouse event reached it, so no order. It keeps its approval.
        return step.save(order={**order, 'approved': approved}, phase='ordering', checkout_at=None,
                         history=[*(task.history or []), {'did': 'the final button', 'result': f'not pressed: {refused}'}
                                  ][-step.HISTORY_KEPT:])
    # Clicked: whatever the page shows next, it is never pressed again (a slow store still places it).
    # The order's pages are looked for; if none shows one, the person is told it may exist.
    browser.pump(4)
