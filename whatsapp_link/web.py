"""What Confío does in WhatsApp Web, and nothing more.

Every function takes a connected agent_tasks.cdp.Page on web.whatsapp.com.
The page's own scripts do the work; we click, type and read what is on
screen like a person would. Nothing here opens a chat to read it (that
would send the person's read receipts): the chat list is read as it is.

Selectors are WhatsApp Web's as seen on 2026-11-23. When WhatsApp changes
its page, reads come back empty and screen() answers 'unknown': nothing is
guessed, the sync backs off.
"""
import random
import re
import time
from urllib.parse import urlsplit

from agent_tasks.cdp import CdpError

HOME = 'https://web.whatsapp.com/'
HOSTS = ('web.whatsapp.com',)
CODE = re.compile(r'^[A-Z0-9]{8}$')
MAX_ROWS = 40
MAX_NAME, MAX_PREVIEW = 120, 300


class WebError(Exception):
    """WhatsApp Web did not do what was asked. `code`: a short reason."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def allowed(url, _method='GET'):
    """Documents only from WhatsApp Web: a link in a message never takes the browser elsewhere."""
    parts = urlsplit(str(url or ''))
    return parts.scheme == 'https' and parts.hostname in HOSTS or str(url).startswith(('about:blank', 'blob:'))


# One expression reads the screen: which of WhatsApp Web's screens is up.
_SCREEN = r'''(() => {
  const text = (document.body && document.body.innerText) || '';
  if (document.querySelector('#pane-side, [aria-label="Chat list"]')) return 'chats';
  if (/Enter code on phone|Enter this code on your phone|Link with phone number/i.test(text)
      && !/Scan to log in/i.test(text) && document.querySelector('[aria-details], [data-link-code]')) return 'code';
  if (/Enter code on phone|Enter this code on your phone/i.test(text)) return 'code';
  if (/Enter phone number|Type your phone number/i.test(text)) return 'phone';
  if (/Scan to log in|Log in with phone number|Link with phone number|Use WhatsApp on your computer/i.test(text))
    return 'login';
  if (/Loading your chats|Loading messages/i.test(text)) return 'loading';
  return 'unknown';
})()'''


def screen(page) -> str:
    """chats | code | phone | login | loading | unknown."""
    try:
        return str(page.evaluate(_SCREEN) or 'unknown')
    except CdpError:
        return 'unknown'


def wait_for(page, wanted, seconds) -> str:
    """Waits for one of `wanted`, answering the browser meanwhile; returns the last screen seen."""
    deadline = time.monotonic() + seconds
    seen = screen(page)
    while seen not in wanted and time.monotonic() < deadline:
        page.pump(1.0)
        seen = screen(page)
    return seen


def _box(page, expression):
    """The centre of the element `expression` finds, or None. The expression returns an element."""
    found = page.evaluate(f'''(() => {{
      const el = ({expression});
      if (!el) return null;
      el.scrollIntoView({{block: 'center'}});
      const r = el.getBoundingClientRect();
      return r.width && r.height ? [r.left + r.width / 2, r.top + r.height / 2] : null;
    }})()''')
    return found if isinstance(found, list) and len(found) == 2 else None


def _press(page, expression, code):
    point = _box(page, expression)
    if point is None:
        raise WebError(code)
    page.click(*point)
    page.pump(0.8)


def _button(label_pattern):
    return (f"[...document.querySelectorAll('[role=button], button')]"
            f".find(e => /{label_pattern}/i.test((e.innerText || e.getAttribute('aria-label') || '').trim()))")


def _pace(low=0.06, high=0.16):
    time.sleep(random.uniform(low, high))


def type_like_a_person(page, text):
    """A few characters at a time. A new line is Shift+Enter: Enter alone sends."""
    for number, line in enumerate(str(text).split('\n')):
        if number:
            for kind in ('keyDown', 'keyUp'):
                page.call('Input.dispatchKeyEvent', {'type': kind, 'key': 'Enter', 'code': 'Enter',
                                                     'windowsVirtualKeyCode': 13, 'modifiers': 8})
            _pace()
        for start in range(0, len(line), 6):
            page.insert(line[start:start + 6])
            _pace()


# ------------------------------------------------------------------ linking

def ask_for_code(page, phone_digits) -> str:
    """From the login screen to the 8-character code, for the international number `phone_digits`."""
    seen = wait_for(page, ('login', 'phone', 'code', 'chats'), 30)
    if seen == 'chats':
        raise WebError('already_linked')
    if seen == 'login':
        _press(page, _button('^(Log in|Link) with phone number'), 'no_phone_option')
        seen = wait_for(page, ('phone', 'code'), 15)
    if seen == 'phone':
        _press(page, "document.querySelector('input[aria-label*=\"phone number\" i], input[type=text]')",
               'no_phone_field')
        page.evaluate("(() => { const i = document.activeElement; if (i && i.select) i.select(); })()")
        page.insert('+' + phone_digits)
        _pace(0.4, 0.9)
        typed = re.sub(r'\D', '', page.evaluate("(document.activeElement || {}).value || ''") or '')
        if typed != phone_digits:
            raise WebError('phone_mismatch')  # never ask WhatsApp to prompt anyone else's phone
        _press(page, _button('^Next$'), 'no_next')
        seen = wait_for(page, ('code',), 25)
    if seen != 'code':
        if re.search(r'invalid|not valid|isn.t valid', page.evaluate('document.body.innerText') or '', re.I):
            raise WebError('phone_invalid')
        raise WebError(f'screen_{seen}')
    code = read_code(page)
    if not code:
        raise WebError('no_code')
    # The field comes prefilled from the browser's location: the screen must name the person's own number.
    # Exactly the number: a location prefix left in front of it (+49 591…) is another number.
    shown = {re.sub(r'\D', '', token) for token in
             re.findall(r'\+\d[\d \-().\u00a0]{6,24}\d', page.evaluate('document.body.innerText') or '')}
    if phone_digits not in shown:
        raise WebError('phone_mismatch')
    return code


_CODE = r'''(() => {
  // The code is drawn one character per cell: the first group of 8 single characters.
  const groups = new Map();
  for (const el of document.querySelectorAll('span, div')) {
    if (el.children.length) continue;
    const t = (el.innerText || '').trim();
    if (!/^[A-Z0-9]$/.test(t)) continue;
    let holder = el.parentElement;
    for (let i = 0; i < 3 && holder && holder.innerText.replace(/[\s-]/g, '').length < 8; i++)
      holder = holder.parentElement;
    if (!holder) continue;
    if (!groups.has(holder)) groups.set(holder, []);
    groups.get(holder).push(t);
  }
  for (const chars of groups.values()) if (chars.length === 8) return chars.join('');
  const m = ((document.body && document.body.innerText) || '').match(/\b([A-Z0-9]{4})-([A-Z0-9]{4})\b/);
  return m ? m[1] + m[2] : '';
})()'''


def read_code(page) -> str:
    code = str(page.evaluate(_CODE) or '').upper()
    return code if CODE.match(code) else ''


def refresh_code(page) -> bool:
    """WhatsApp lets a code lapse; a button asks for a new one. True when pressed."""
    point = _box(page, _button('get new code|refresh|try again|generate new code'))
    if point is None:
        return False
    page.click(*point)
    page.pump(2.0)
    return True


# ------------------------------------------------------------------ reading

_ROWS = r'''((max) => {
  const pane = document.querySelector('#pane-side, [aria-label="Chat list"]');
  if (!pane) return null;
  const rows = [...pane.querySelectorAll('[role="listitem"], [role="row"]')];
  const out = [];
  for (const row of rows.slice(0, max)) {
    const titled = [...row.querySelectorAll('span[title]')];
    const name = titled.length ? titled[0].getAttribute('title') : '';
    if (!name) continue;
    const badge = row.querySelector('[aria-label*="unread message" i]');
    const unread = badge ? parseInt((badge.getAttribute('aria-label').match(/\d+/) || ['1'])[0], 10) : 0;
    const preview = titled.length > 1 ? titled[titled.length - 1].getAttribute('title') : '';
    // Only WhatsApp's own group marks: a preview like "Total: 50 Bs" is not a group.
    const group = !!row.querySelector('[data-icon="default-group"], [data-icon="group"], [data-icon*="community" i]');
    const times = [...row.querySelectorAll('div, span')].map(e => e.children.length ? '' : (e.innerText || '').trim())
      .filter(t => /^(\d{1,2}:\d{2}(\s?[AP]M)?|Yesterday|Today|\d{1,2}\/\d{1,2}\/\d{2,4}|[A-Z][a-z]+day)$/.test(t));
    out.push({name, preview, unread, group, time: times[0] || ''});
  }
  return out;
})'''


def unread_chats(page) -> list:
    """[{name, preview, unread, group, time}] for chats with unread messages, as the list shows them."""
    rows = page.evaluate(f'{_ROWS}({MAX_ROWS})')
    if rows is None:
        raise WebError('no_chat_list')
    found = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get('unread'):
            continue
        found.append({'name': str(row.get('name') or '')[:MAX_NAME], 'preview': str(row.get('preview') or '')[:MAX_PREVIEW],
                      'unread': min(int(row.get('unread') or 1), 999), 'group': bool(row.get('group')),
                      'time': str(row.get('time') or '')[:20]})
    return found


# ------------------------------------------------------------------ sending

_HEADER = "document.querySelector('#main header span[title], #main header [title]')"
_COMPOSER = ("document.querySelector('#main footer div[contenteditable=\"true\"], "
             "footer div[contenteditable=\"true\"][role=textbox]')")


def open_chat_by_name(page, name):
    """Opens the one chat whose name is exactly `name`. Two of them, or none: refused."""
    _press(page, "document.querySelector('#side div[contenteditable=\"true\"], [aria-label=\"Search input textbox\"], "
                 "div[contenteditable=\"true\"][data-tab=\"3\"]')", 'no_search')
    page.evaluate("document.execCommand('selectAll', false, null)")
    type_like_a_person(page, name)
    page.pump(2.5)
    titles = f'''[...document.querySelectorAll('#pane-side [role="listitem"], #pane-side [role="row"]')]
        .map(row => row.querySelector('span[title]')).filter(e => e && e.getAttribute('title') === {_js(name)})'''
    matches = page.evaluate(f'{titles}.length')
    if matches != 1:
        raise WebError('chat_ambiguous' if matches else 'chat_not_found')
    _press(page, f'{titles}[0]', 'chat_not_found')
    page.pump(1.5)
    if (page.evaluate(f'({_HEADER} || {{}}).getAttribute ? {_HEADER}.getAttribute("title") : ""') or '') != name:
        raise WebError('wrong_chat')


def open_chat_by_number(page, digits):
    page.goto(f'{HOME}send?phone={digits}')
    seen = wait_for(page, ('chats',), 40)
    if seen != 'chats':
        raise WebError('no_chat_list')
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        page.pump(1.0)
        # The refusal first: its popup can sit over a chat that was already open.
        text = page.evaluate('''[...document.querySelectorAll('[role="dialog"], [data-animate-modal-popup]')]
            .map(e => e.innerText).join(' ')''') or ''
        if re.search(r'invalid|not on WhatsApp|isn.t on WhatsApp', text, re.I):
            raise WebError('number_not_on_whatsapp')
        if _box(page, _COMPOSER) is not None:
            page.pump(1.5)
            header = re.sub(r'\D', '', page.evaluate(f'({_HEADER} || {{}}).textContent || ""') or '')
            # A saved contact shows a name; a number shown must be this one.
            if len(header) >= 8 and header != digits:
                raise WebError('wrong_chat')
            return
    raise WebError('no_composer')


# Failures that happen before Enter: nothing left the browser.
BEFORE_ENTER = frozenset({'no_composer', 'composer_not_empty', 'typed_mismatch', 'not_wanted'})
CONFIRM_SECONDS = 15
_OUT = "document.querySelectorAll('#main .message-out').length"


def _composer_text(page):
    return page.evaluate(f'({_COMPOSER} || {{}}).innerText || ""') or ''


def _clear_composer(page):
    """What Confío typed and did not send is taken back: the person's WhatsApp keeps no half message of ours."""
    try:
        if _box(page, _COMPOSER) is not None:
            page.click(*_box(page, _COMPOSER))
            page.evaluate("document.execCommand('selectAll', false, null); document.execCommand('delete')")
    except CdpError:
        pass


def send_text(page, body, still_wanted=lambda: True, progress=None):
    """Types `body` in the open chat and presses Enter once. True only when a new sent bubble
    appeared and the box is empty; False when it is unknown."""
    _press(page, _COMPOSER, 'no_composer')
    if _composer_text(page).strip():
        # Only Confío types in this browser: what is there is a try of ours that never left. Taken back.
        _clear_composer(page)
        if _composer_text(page).strip():
            raise WebError('composer_not_empty')
    _pace(1.5, 3.5)
    before = page.evaluate(_OUT) or 0
    try:
        type_like_a_person(page, body)
        _pace(0.8, 1.6)
        if comparable(_composer_text(page)) != comparable(body):
            raise WebError('typed_mismatch')
        if not still_wanted():
            raise WebError('not_wanted')
    except BaseException:
        _clear_composer(page)
        try:
            grew = (page.evaluate(_OUT) or 0) > before
        except CdpError:
            grew = True  # cannot tell: never claim nothing left
        if grew:
            raise WebError('partial_sent') from None  # a line went out: unknown, never resent
        raise
    if progress is not None:
        progress['enter'] = True  # from here on, whatever happens, it may have gone out
    page.enter()
    deadline = time.monotonic() + CONFIRM_SECONDS
    while time.monotonic() < deadline:
        page.pump(1.0)
        if (page.evaluate(_OUT) or 0) > before and not _composer_text(page).strip():
            return True
    _clear_composer(page)
    return False


def comparable(value):
    """Text as the box shows it: WhatsApp draws emoji as pictures, so they are left out of the comparison."""
    import unicodedata
    kept = ''.join(ch for ch in unicodedata.normalize('NFC', str(value or ''))
                   if unicodedata.category(ch) not in ('So', 'Sk', 'Cs', 'Mn', 'Cf'))
    return re.sub(r'\s+', ' ', kept).strip()


def signed_in_number(page) -> str:
    """The number this WhatsApp Web is signed in as (its own id in local storage), digits only, or ''."""
    value = page.evaluate('''(() => { for (const k of ['last-wid-md', 'last-wid']) {
        const v = localStorage.getItem(k); if (v) return v; } return ''; })()''') or ''
    found = re.match(r'"?(\d{8,15})[:@]', str(value))
    return found.group(1) if found else ''


def log_out(page):
    """Menu → Log out → Log out: the device leaves the person's Linked devices list."""
    _press(page, "document.querySelector('[aria-label=\"Menu\"], span[data-icon=\"menu\"]')", 'logout')
    _press(page, _button('^Log out$'), 'logout')
    page.pump(1.0)
    _press(page, _button('^Log out$'), 'logout')
    page.pump(3.0)


def _js(value):
    import json
    return json.dumps(str(value))
