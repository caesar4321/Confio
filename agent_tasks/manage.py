"""An order already placed: its state, or a request about it (cancel, return, refund, claim).

The model finds the order on the store's own pages and does what the store asks
of a shopper there. A second model reads each press (agent.judge) and decides:
buying, a card and the account are refused; what sends a request is never
pressed by the model. It names it (submit_request), the judge confirms it is
one, the person approves exactly that in the chat, and it is pressed once.
What the person only wanted to know is answered in the chat with what the
store's page says. No word of the store's is matched in code.
"""
import logging
import re

from django.utils import timezone

from . import agent, guard, notes
from .operate import NOT_A_FORM, REFUSED, MAX_SAME_PRESS, _identity, _label, _trace, sign_in

logger = logging.getLogger(__name__)

# A request the person approved is pressed at most this often (a page that reloads the same form).
MAX_SUBMITS = 1


def managing(task):
    return getattr(task, 'kind', 'buy') == 'manage'


def step(st, browser, reader, seen):
    """One step on an order already placed."""
    task = st.task
    st.operating = True
    seen.look = reader.picture   # what the judge sees: the page, with the control boxed
    _trace(st, seen)
    name, args = agent.manage(task, seen, st.meter)
    if name == 'wait':
        st.delay = 2
        return st.remember('wait', 'ok')
    if name == 'give_up':
        reason = args.get('reason')
        submitted = (task.order or {}).get('submitted')
        # After a request was sent the person is told it may be on its way, never that nothing happened.
        return st.stop('request_unclear' if submitted else ('not_found' if reason == 'not_found' else 'cannot_do'),
                       order={**(task.order or {}), 'why': notes.reason_text(args.get('why'))})
    if name == 'sign_in':
        done = sign_in(st, browser, reader, seen, asked=True)
        return st.remember('sign_in', 'refused: no sign-in form on this page') if done is NOT_A_FORM else done
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
    if _judged_for_manage(st, seen, element, label, did) is REFUSED:
        return None
    if sum(entry.get('at') == where and entry.get('did') == did[:120] for entry in (task.history or [])[-8:]) \
            >= MAX_SAME_PRESS:
        return st.remember(did, 'refused: already pressed twice here; do something else')
    st.save(history=[*(task.history or []), {'did': did[:120], 'result': 'pressed', 'at': where}][-st.HISTORY_KEPT:],
            steps=task.steps + 1, failures=0)
    refused = reader.click(element)
    if refused:
        st.save(history=(task.history or [])[:-1])   # it never happened: not counted as a press
        return st.remember(did, f'refused: {refused}')
    browser.pump(2)
    return None


def _judged_for_manage(st, seen, element, label, did):
    """The judge decides. Safe is pressed; what sends a request goes to submit_request, where the person
    approves it; buying, a card and the account are refused."""
    try:
        verdict, why = agent.judge(st.task, seen, element, st.meter)
    except agent.AgentUnavailable:
        verdict, why = 'unsure', 'the check could not run'
    if verdict == 'safe':
        return None
    if verdict == 'request':
        st.remember(did, f'refused: it sends the request ({why}). Call submit_request with it.')
        return REFUSED
    if verdict == 'unsure':
        st.remember(did, f'refused: it is not clear what it does ({why}). If it sends the request the person '
                         'asked for, call submit_request with it; else find another way.')
        return REFUSED
    st.remember(did, f'refused: {verdict} ({why}). Never buy, never a card nor the account: find another way.')
    return REFUSED


def submit(st, reader, browser, seen, element, label, where, args):
    """The button that sends the request: named, approved by the person, pressed once."""
    task = st.task
    # The judge reads this button on this page: only one that sends a request about an order is ever named
    # to the person. Never one that buys, uses a card or changes the account.
    try:
        verdict, why = agent.judge(task, seen, element, st.meter)
    except agent.AgentUnavailable:
        verdict, why = 'unsure', 'the check could not run'
    if verdict != 'request':
        return st.remember('submit_request', f'refused: the second reader does not see it as the button that '
                                             f'sends the request ({verdict}: {why})')
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
    if approved and {**approved, 'what': ''} == {**request, 'what': ''}:
        request['what'] = approved.get('what')   # the same request: a model never words it twice the same
    if approved != request:
        # Named: the person approves exactly this (its words, this button, this page) in the chat.
        return st.hand_over('act', order={**order, 'request': request, 'request_approved': None},
                            body=notes.say(notes.NEEDS_PERSON['act'], task).replace('{what}', what))
    if element.get('tag') == 'a':
        # A link opens the store's form ("Cancelar productos"); it sends nothing. Pressed under this approval,
        # it never uses up the request: the form's own button is named and approved next (2026-11-24: the
        # approved link counted as sent, and the real "Solicitar cancelación" was then refused as a second one).
        st.save(order={**order, 'request_approved': None},
                history=[*(task.history or []), {'did': f'opened "{label}" (approved)',
                                                 'result': 'only the store\'s form opened, nothing was sent: name '
                                                           'its button with submit_request'}][-st.HISTORY_KEPT:],
                steps=task.steps + 1, failures=0)
        refused = reader.click(element)
        if refused:
            return st.save(order={**(st.task.order or {}), 'request_approved': approved})
        browser.pump(3)
        return None
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
        sent = notes.BOOKED if getattr(task, 'kind', 'buy') == 'reserve' else notes.SENT
        body = notes.say(sent, task) + ' ' + body
    return st.stop('answered', body=body, order={**(task.order or {}), 'answer': text})
