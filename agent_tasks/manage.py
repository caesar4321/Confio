"""An order already placed: its state, or a request about it (cancel, return, refund, claim).

The model finds the order on the store's own pages and does what the store asks
of a shopper there. The click judge reviews each press, and code's floor holds
as on a purchase: never buying, never a card, never the account. What sends a
request is never pressed by the model: it names it (submit_request), the person
approves exactly that in the chat, and it is pressed once. What the person only
wanted to know is answered in the chat with what the store's page says.
"""
import logging
import re

from django.utils import timezone

from . import agent, guard, notes
from .operate import REFUSED, MAX_SAME_PRESS, _identity, _judged, _label, _trace

logger = logging.getLogger(__name__)

# A request the person approved is pressed at most this often (a page that reloads the same form).
MAX_SUBMITS = 1


def managing(task):
    return getattr(task, 'kind', 'buy') == 'manage'


def step(st, browser, reader, seen):
    """One step on an order already placed."""
    task = st.task
    st.operating = True
    _trace(st, seen)
    if guard.is_checkout(seen) or _cart(seen.url):
        # Helping with an order never goes near buying: a cart or a checkout ends it, whatever led there.
        return st.stop('request_unclear' if (task.order or {}).get('submitted') else 'cannot_do')
    name, args = agent.manage(task, seen, st.meter)
    if name == 'wait':
        st.delay = 2
        return st.remember('wait', 'ok')
    if name == 'give_up':
        reason = args.get('reason')
        submitted = (task.order or {}).get('submitted')
        # After a request was sent the person is told it may be on its way, never that nothing happened.
        return st.stop('request_unclear' if submitted else ('not_found' if reason == 'not_found' else 'cannot_do'))
    if name == 'answer':
        return answer(st, args.get('text'), seen)
    element = seen.element(args.get('ref'))
    if element is None or element.get('disabled'):
        return st.remember(f'{name}'[:30], 'refused: no such control on this page')
    label = _label(element)
    where = st.fingerprint(seen.url)
    if name == 'submit_request':
        return submit(st, reader, browser, seen, element, label, where, args)
    if name != 'press':
        return st.remember(f'{name}'[:30], 'refused')
    did = f'press "{label}"'
    if (task.order or {}).get('request_approved'):
        # Anything pressed after the person approved may change what is sent: asked again.
        st.save(order={**(task.order or {}), 'request_approved': None})
    # (A link only opens the store's request page: "Devolver o reemplazar artículos" is pressed.)
    if (_sends_request(element) and element.get('tag') != 'a') or (_request_form(seen) and _a_sender(element)):
        # A request form: only what edits or chooses is pressed; any button that may send it is the person's.
        return st.remember(did, 'refused: it may send the request. Call submit_request with it.')
    if _judged_for_manage(st, seen, element, label, did, where) is REFUSED:
        return None
    if sum(entry.get('at') == where and entry.get('did') == did[:120] for entry in (task.history or [])[-8:]) \
            >= MAX_SAME_PRESS:
        return st.remember(did, 'refused: already pressed twice here; do something else')
    st.save(history=[*(task.history or []), {'did': did[:120], 'result': 'pressed', 'at': where}][-st.HISTORY_KEPT:],
            steps=task.steps + 1, failures=0)
    refused = reader.click(element)
    if refused:
        return st.remember(did, f'refused: {refused}')
    browser.pump(2)
    return None


# A cancellation, a return, a refund, a claim: the words that send one (beside the judge's own reading).
_REQUEST_WORDS = re.compile(r'\b(cancelar (el |la |mi |este |los |las )?(pedido|compra|orden|producto|articulos?)'
                            r'|cancel (the |this )?(order|items?)|cancelar (articulos )?seleccionados'
                            r'|solicitar (la |una )?(devolucion|devolucao|cancelacion|cancelamento|reembolso)'
                            r'|devolver (el |este |los )?(producto|articulo)s?|return items?|devolver|devolucao'
                            r'|enviar (la )?solicitud|confirmar (la )?(cancelacion|devolucion|devolucao|cancelamento)'
                            r'|request (a )?(refund|return)|reembolsar|abrir (un )?reclamo|iniciar (una )?devolucion'
                            r'|si,? cancelar)\b')
# A page that writes a request: its reason, its refund, a return or a cancellation.
_FORM_WORDS = re.compile(r'\b(motivo|razon|reason|devolucion|devolucao|cancelacion|cancelamento|reembolso|refund'
                         r'|reclamo|return)\b')


def _sends_request(element):
    return any(_REQUEST_WORDS.search(part) for part in guard._parts(element))


def _request_form(seen):
    return bool(_FORM_WORDS.search(guard.fold(seen.text[:100000])))


def _a_sender(element):
    """A button that may send the form it sits in: anything but a link, a choice, or an edit or choice by
    its whole words (guard._FINAL_SAFE)."""
    if element.get('tag') == 'a' or element.get('tag') == 'select' or element.get('type') in ('radio', 'checkbox') \
            or element.get('role') in ('radio', 'checkbox', 'option', 'tab'):
        return False
    parts = guard._parts(element)
    return not (parts and all(guard._FINAL_SAFE.fullmatch(part) for part in parts))


def _cart(url):
    return bool(re.search(r'/(cart|carrito|carrinho|cesta|basket|checkout)\b', guard.urlsplit(url or '').path.lower()))


def _judged_for_manage(st, seen, element, label, did, where):
    """The purchase's floor and judge, read for an order already placed: a request goes to submit_request,
    never pressed; buying, a card and the account are refused as on a purchase."""
    hard = guard.hard_refusal(element, on_checkout=True, page=seen)   # no way into a checkout is exempt here
    if hard:
        st.remember(did, f'refused: {hard}. Never buy, never a card nor the account: find another way.')
        return REFUSED
    try:
        verdict, why = agent.judge(st.task, seen, element, st.meter)
    except agent.AgentUnavailable:
        verdict, why = 'unsure', 'the check could not run'
    if verdict == 'safe' and not (_request_form(seen) and _a_sender(element)):
        return None
    if verdict in ('safe', 'request'):
        st.remember(did, f'refused: it sends the request ({why}). Call submit_request with it.')
        return REFUSED
    if verdict == 'unsure' and all(guard._FINAL_SAFE.fullmatch(part) for part in guard._parts(element) or ['x']):
        return None
    st.remember(did, f'refused: {verdict} ({why}). Find another way.')
    return REFUSED


def submit(st, reader, browser, seen, element, label, where, args):
    """The button that sends the request: named, approved by the person, pressed once."""
    task = st.task
    hard = guard.hard_refusal(element, on_checkout=True, page=seen)
    # "Confirmar cancelación" reads as a final word: it is a request where nothing on the page is bought.
    if hard == 'places_order' and _sends_request(element) and not guard.final_step(seen.text, seen.elements):
        hard = ''
    if hard in ('card', 'places_order') or (hard and not _sends_request(element)):
        return st.remember('submit_request', f'refused: that is {hard}, never a request to send')
    if not _sends_request(element):
        try:
            verdict, _ = agent.judge(task, seen, element, st.meter)
        except agent.AgentUnavailable:
            verdict = 'unsure'
        if verdict != 'request':
            return st.remember('submit_request', 'refused: that is not the button that sends the request')
    what = guard.clean(agent.redact(str(args.get('what') or '')), 120) or 'la solicitud'
    same = [other for other in seen.elements if _label(other) == label]
    request = {**_identity(element, label, where), 'what': what, 'button': label[:80],
               'nth': next((index for index, other in enumerate(same) if other is element), 0),
               'href_full': str(element.get('href') or '')[:300],
               'chosen': sorted(_label(other)[:60] for other in seen.elements if other.get('checked'))[:12]}
    order = dict(task.order or {})
    if (order.get('submitted') or 0) >= MAX_SUBMITS:
        return st.remember('submit_request', 'refused: the request was already sent; read its result and answer')
    approved = order.get('request_approved') or {}
    if approved != request:
        # Named: the person approves exactly this (its words, this button, this page) in the chat.
        return st.hand_over('act', order={**order, 'request': request, 'request_approved': None},
                            body=notes.say(notes.NEEDS_PERSON['act'], task).replace('{what}', what))
    # Used once, and written down first: an answer lost on the way is never a second request.
    st.save(order={**order, 'request_approved': None, 'submitted': (order.get('submitted') or 0) + 1,
                   'submitted_at': timezone.now().isoformat()},
            history=[*(task.history or []), {'did': f'sent "{label}"', 'result': what}][-st.HISTORY_KEPT:],
            steps=task.steps + 1, failures=0)
    refused = reader.click(element)
    if refused:
        # Not clicked: no request left. It keeps its approval.
        return st.save(order={**(st.task.order or {}), 'request_approved': approved,
                              'submitted': (order.get('submitted') or 0)},
                       history=[*(task.history or []), {'did': 'the request', 'result': f'not sent: {refused}'}
                                ][-st.HISTORY_KEPT:])
    browser.pump(3)
    return None


_LINKS = re.compile(r'(https?://\S+|www\.\S+|\b[\w-]+\.(com|net|org|ly|io|me|co|mx|br|ar|ve|bo|pe|cl|link|app)\b\S*'
                    r'|@\w+|\[([^\]]*)\]\([^)]*\)|[*_`#>]+)', re.I)
_PHONE = re.compile(r'\+?\d[\d\s().-]{7,}\d')


def answer(st, text, seen=None):
    """What the person asked, as the store's page says it: ends the task, in the chat. No link, phone, handle
    or formatting survives (a seller's message is on that page too), and every number in it must be the
    page's own."""
    text = agent.redact(str(text or ''))
    text = _PHONE.sub('', _LINKS.sub(lambda m: m.group(3) or '', text))
    text = guard.clean(' '.join(text.split()), 400).replace('<', '‹').replace('>', '›')
    if not text:
        return st.remember('answer', 'refused: say it in one or two sentences, with only what this page shows')
    if seen is not None:
        page = re.sub(r'\s+', ' ', guard.fold(seen.text[:100000]))
        missing = [n for n in re.findall(r'\d[\d.,/:-]*\d|\d', text) if n not in page]
        if missing:
            return st.remember('answer', f'refused: {missing[0]} is not on this page; say only what it shows')
    task = st.task
    body = notes.say(notes.MANAGED, task).replace('{text}', text)
    if (task.order or {}).get('submitted'):
        # Sent: said in code's words; the page's own reading follows, never instead.
        body = notes.say(notes.SENT, task) + ' ' + body
    return st.stop('answered', body=body, order={**(task.order or {}), 'answer': text})
