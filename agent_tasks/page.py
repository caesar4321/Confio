"""What one step reads from a page, and the two ways it touches it.

The scripts run in an isolated world, so the page's own JavaScript cannot
change what they report. Elements are chosen by number, never by
coordinates. The check that a control is still what was judged and the act
on it are one evaluation: the page cannot change between the two, and
nothing else can be under a pointer, because there is no pointer.

Values of text fields are never read: they are where passwords, documents and
card numbers are typed. A payment code is never looked for in a page at all:
anyone who can write in a page could plant one (qr.py reads the screen).
"""
import base64
import io
import json
import re
from dataclasses import dataclass, field

from .cdp import CdpError

WORLD = 'confio_task'
MAX_ELEMENTS = 260
MAX_TEXT = 60000
MAX_LABEL = 300
# What must still be true of a control when it is acted on.
BOUND = ('tag', 'type', 'role', 'name', 'label', 'href', 'action', 'method', 'disabled', 'nested', 'secret_form', 'search', 'new_window', 'scripted')

_READ = r'''(() => {
  const clean = v => String(v || '').replace(/\u0000/g, '').replace(/\s+/g, ' ').trim();
  const seen = el => {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    return el.checkVisibility ? el.checkVisibility({opacityProperty: true, visibilityProperty: true}) : true;
  };
  const buttonInput = el => el.tagName === 'INPUT' && ['button', 'submit', 'reset', 'image'].includes(el.type);
  const searchNames = ['q', 'as_word', 'search', 'query', 'busca', 'k', 'field-keywords', 's', 'term'];
  const address = v => {
    try { return new URL(v, document.baseURI).href; } catch (e) { return 'invalid:'; }
  };
  // Prototype methods: a field named "getAttribute" shadows the form's own.
  const attr = (el, name) => Element.prototype.getAttribute.call(el, name);
  const describe = el => {
    const tag = el.tagName.toLowerCase();
    const parts = [];
    if (tag !== 'input' && tag !== 'textarea') parts.push(el.innerText);
    for (const a of ['aria-label', 'title', 'placeholder', 'alt']) parts.push(el.getAttribute(a));
    for (const id of clean(el.getAttribute('aria-labelledby')).split(' ')) {
      const by = id && document.getElementById(id);
      if (by) parts.push(by.innerText);
    }
    if (buttonInput(el)) parts.push(el.value);
    if (el.labels) for (const l of el.labels) parts.push(l.innerText);
    for (const img of el.querySelectorAll('img[alt]')) parts.push(img.getAttribute('alt'));
    const label = [...new Set(parts.map(clean).filter(Boolean))].join(' | ');
    const form = el.form || (['input', 'button'].includes(tag) ? null : el.closest('form'));
    const type = (attr(el, 'type') || '').toLowerCase();
    // Only these send their form; a type=button beside the buy button does not.
    const sends = !!form && (tag === 'button' ? (type === '' || type === 'submit')
      : tag === 'input' ? !['button', 'reset', 'checkbox', 'radio'].includes(type) : false);
    const nested = !!(el.parentElement && el.parentElement.closest(
      'a[href],button,label,summary,[role=button],[role=link],[onclick]'));
    return {
      tag, type, role: el.getAttribute('role') || '', nested,
      name: clean([el.getAttribute('name'), el.id].join(' ')).slice(0, 120),
      autocomplete: (el.getAttribute('autocomplete') || '').toLowerCase(),
      label: label.slice(0, __MAX_LABEL__), cut: label.length > __MAX_LABEL__,
      href: tag === 'a' ? el.href : '',
      // A product's picture, for the card the person picks from: an address, never loaded here.
      image: (() => {
        const img = tag === 'a' ? el.querySelector('img') : null;
        const src = img ? String(img.currentSrc || img.src || '') : '';
        return /^https:\/\//.test(src) ? src.slice(0, 600) : '';
      })(),
      // getAttribute, not form.action: a field named "action" would shadow the property.
      action: sends ? address(attr(el, 'formaction') || attr(form, 'action') || document.baseURI) : '',
      method: sends ? String(attr(el, 'formmethod') || attr(form, 'method') || 'get').toLowerCase() : '',
      // Attributes a generic delegated script turns into a request.
      // On it or on anything around it: delegated scripts read their orders from ancestors too.
      scripted: (() => {
        for (let node = el; node && node !== document.body; node = node.parentElement)
          if ([...Element.prototype.getAttributeNames.call(node)].some(name =>
              /^(data-(hx-|url|href|method|remote|action|confirm|post|request|endpoint|params)|hx-|up-|wire:|x-on:)/.test(name)))
            return true;
        return [...Element.prototype.getAttributeNames.call(el), ...(form ? Element.prototype.getAttributeNames.call(form) : [])]
          .some(name => /^on/.test(name));
      })(),
      // A form with no target of its own opens where the page's <base target> says.
      // The agent's tab is top-level: _top and _parent are that same tab.
      new_window: !!sends && !['', '_self', '_top', '_parent'].includes(String(attr(el, 'formtarget') || attr(form, 'target') ||
        (document.querySelector('base[target]') || {getAttribute: () => ''}).getAttribute('target') || '').toLowerCase()),
      secret_form: !!(form && Element.prototype.querySelector.call(form, 'input[type=password],input[autocomplete^="cc-"]')),
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
      // A chosen option (a payment method, an address): what the checkout will use.
      checked: !!el.checked || ['aria-checked', 'aria-selected'].some(a => el.getAttribute(a) === 'true') ||
        (tag === 'label' && !!(el.control && el.control.checked)),
      maxlength: Number(el.getAttribute('maxlength')) || 0,
      search: tag === 'input' && (el.type === 'search' || el.getAttribute('role') === 'searchbox' ||
        !!el.closest('[role=search]') || searchNames.includes(el.getAttribute('name') || '')),
    };
  };
  const found = [...document.querySelectorAll('a[href],button,input:not([type=hidden]),div[role=button],span[role=button],' +
      'select,label[for],[role=radio],[role=checkbox],[role=option],[role=tab]')]
    .filter(seen);
  let picked = found;
  if (found.length > __MAX_ELEMENTS__) {
    const controls = new Set(found.filter(el => el.tagName !== 'A'));
    let room = __MAX_ELEMENTS__ - controls.size;
    picked = found.filter(el => controls.has(el) || room-- > 0).slice(0, __MAX_ELEMENTS__);
  }
  globalThis.picked = picked;
  globalThis.describe = describe;
  globalThis.seen = seen;
  const elements = picked.map((el, ref) => {
    const r = el.getBoundingClientRect();
    const on_screen = r.right > 0 && r.left < innerWidth && !el.closest('[inert],[aria-hidden=true]');
    return {ref, on_screen, ...describe(el)};
  });
  let text = document.body ? document.body.innerText.replace(/\u0000/g, '') : '';
  for (const el of document.querySelectorAll('[contenteditable]:not([contenteditable=false])')) {
    const typed = el.innerText.trim();
    if (typed.length > 2) text = text.split(typed).join('[campo]');  // typed by the person, like a field's value
  }
  const solved = [...document.querySelectorAll(
    'textarea[name=g-recaptcha-response],textarea[name=h-captcha-response],input[name=cf-turnstile-response]')]
    .some(el => !!el.value);
  const captcha = !solved && [...document.querySelectorAll('iframe')].some(f => {
    const r = f.getBoundingClientRect();
    return r.width > 120 && r.height > 60 && seen(f) && !/size=invisible/.test(f.src) &&
      /recaptcha\/(api2|enterprise)\/(anchor|bframe)|hcaptcha\.com|challenges\.cloudflare\.com|arkoselabs|funcaptcha|captcha-delivery/i.test(f.src);
  });
  const secret = [...document.querySelectorAll(
    'input[type=password],input[autocomplete="one-time-code"]')].some(seen);
  return {url: location.href, title: clean(document.title).slice(0, 200), text: text.slice(0, __MAX_TEXT__),
          elements, captcha, secret};
})()'''

# The shared head of both acts: the very control that was judged, on the very page.
_SAME = r'''
  const el = (globalThis.picked || [])[__REF__];
  if (!el || !el.isConnected || !globalThis.seen(el)) return 'gone';
  if (location.href !== __URL__) return 'changed';
  const now = globalThis.describe(el), was = __WAS__;
  if (Object.keys(was).some(key => now[key] !== was[key])) return 'changed';
'''

# Not a click: the form is sent as a browser sends it, with no click or submit
# event, so no script of the page (or of a seller's markup) runs on it.
_PRESS = '(() => {' + _SAME + r'''
  const form = el.form;
  if (!form) return 'not_a_form';
  for (const name of ['formaction', 'formmethod', 'formtarget', 'formenctype'])
    if (Element.prototype.hasAttribute.call(el, name)) return 'changed';  // it would send elsewhere than judged
  let extra = null;
  if (el.name) {
    // What the button itself adds (a store can tell "add to cart" from "buy now" by it).
    extra = document.createElement('input');
    extra.type = 'hidden'; extra.name = el.name; extra.value = el.value;
    form.appendChild(extra);
  }
  try {
    HTMLFormElement.prototype.submit.call(form);
  } finally {
    if (extra) extra.remove();
  }
  return '';
})()'''

# Where a control is on screen, for a real click (a checkout's and a sign-in's
# controls answer scripts, not forms). `clear` empties a field first.
_POINT = '(() => {' + _SAME + r'''
  el.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
  const r = el.getBoundingClientRect();
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  // What a click there would really hit: a banner or a widget over it is not this control.
  const hit = document.elementFromPoint(x, y);
  if (!hit || !(hit === el || el.contains(hit) || (hit.closest && hit.closest('label') && el.labels &&
      [...el.labels].includes(hit.closest('label'))))) return 'covered';
  // Inside this control, another button or link would take the click (a tab or a row that holds the final button).
  const inner = hit.closest && hit.closest('button, a[href], input[type=submit], input[type=button], [role=button]');
  if (inner && inner !== el && el.contains(inner)) return 'covered';
  // Nor a control that sits inside a button or link: the click would be that one's.
  const outer = el.parentElement && el.parentElement.closest('button, a[href], [role=button]');
  if (outer) return 'covered';
  // A label clicks its control: never one that is a button.
  if (el.tagName === 'LABEL' && el.control && (el.control.tagName === 'BUTTON' ||
      ['submit', 'button', 'image'].includes((el.control.type || '').toLowerCase()))) return 'covered';
  if (__CLEAR__) {
    if (el.tagName !== 'INPUT') return 'not_a_field';
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, '');
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.focus();
  }
  return {x, y};
})()'''

# Where a control is on screen, for a picture of it. 'secret' when a password, a one-time code or a card
# field is on screen: those are never pictured.
_BOX = '(() => {' + _SAME + r'''
  const vv = window.visualViewport;
  if (vv && Math.abs(vv.scale - 1) > 0.01) return 'zoomed';
  if (__SCROLL__) el.scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});
  for (const field of document.querySelectorAll('input')) {
    const r = field.getBoundingClientRect();
    if (!(r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth)) continue;
    const type = (field.getAttribute('type') || '').toLowerCase();
    const auto = (field.getAttribute('autocomplete') || '').toLowerCase();
    if (type === 'password' || auto.includes('one-time-code') || auto.startsWith('cc-')) return 'secret';
  }
  const r = el.getBoundingClientRect();
  return {x: r.left, y: r.top, w: r.width, h: r.height, vw: innerWidth, vh: innerHeight};
})()'''
PICTURE_WIDTH = 1280   # wide enough to read a checkout's small print
PICTURE_SECONDS = 5    # a picture is a help: never worth a step's time

# After the click that focuses a field: it, and nothing else, has the focus (and a password goes only into a password field).
_FOCUSED = r'''(() => {
  const el = (globalThis.picked || [])[__REF__];
  return !!el && document.activeElement === el && (!__SECRET__ || el.type === 'password');
})()'''

_SEARCH = '(() => {' + _SAME + r'''
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, __TEXT__);
  if (el.form && el.name) {
    // A GET form is only an address: built here and opened like a link, so
    // nothing the page hung on typing or submitting runs.
    const to = new URL(now.action);
    // This box only: a page-wide form would carry whatever else was typed in it.
    to.search = new URLSearchParams([[el.name, el.value]]).toString();
    return {open: to.href};
  }
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  // Handlers of those events ran: look again before anything is sent.
  const then = globalThis.describe(el);
  if (Object.keys(was).some(key => then[key] !== was[key])) return 'changed';
  if (el.form) return 'changed';  // a box its form would not send
  else {
    for (const type of ['keydown', 'keyup'])
      el.dispatchEvent(new KeyboardEvent(type, {key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}));
  }
  return '';
})()'''


def _script(template, **values):
    values = {'MAX_ELEMENTS': MAX_ELEMENTS, 'MAX_TEXT': MAX_TEXT, 'MAX_LABEL': MAX_LABEL, **values}
    # One pass: a page's words that look like a slot ("__URL__") are never filled in.
    return re.sub(r'__([A-Z]+(?:_[A-Z]+)*)__',
                  lambda slot: json.dumps(values[slot.group(1)]) if slot.group(1) in values else slot.group(0),
                  template)


@dataclass
class Snapshot:
    url: str = ''
    title: str = ''
    text: str = ''
    elements: list = field(default_factory=list)
    captcha: bool = False
    secret: bool = False

    def element(self, ref):
        if isinstance(ref, int) and not isinstance(ref, bool) and 0 <= ref < len(self.elements):
            return self.elements[ref]
        return None


class Reader:
    """Reads and touches one page, over one connection, for one step."""

    def __init__(self, page):
        self.page, self._context, self._url = page, None, ''
        self.address = None  # where a form's search goes

    def _world(self):
        # A world belongs to one document: after a navigation it is made again.
        frame = self.page.call('Page.getFrameTree')['frameTree']['frame']['id']
        self._context = self.page.call(
            'Page.createIsolatedWorld', {'frameId': frame, 'worldName': WORLD})['executionContextId']

    def read(self) -> Snapshot:
        self._world()
        data = self._run(_script(_READ))
        if not isinstance(data, dict):
            raise CdpError('page could not be read')
        self._url = data.get('url') or ''
        return Snapshot(**{key: data[key] for key in Snapshot.__dataclass_fields__ if key in data})

    def _run(self, expression, *, gesture=False, seconds=None):
        out = self.page.call('Runtime.evaluate', {
            'expression': expression, 'contextId': self._context, 'returnByValue': True, 'userGesture': gesture},
            **({'seconds': seconds} if seconds else {}))
        if out.get('exceptionDetails'):
            raise CdpError('page script failed')
        return (out.get('result') or {}).get('value')

    def _act(self, template, element, **values):
        done = self._run(_script(template, REF=element['ref'], URL=self._url,
                                 WAS={key: element[key] for key in BOUND if key in element}, **values), gesture=True)
        if isinstance(done, dict) and done.get('open'):
            self.address = str(done['open'])
            return ''
        if done != '':
            return str(done or 'changed')
        self.page.settle()
        return ''

    def press(self, element) -> str:
        """'' when its form was sent, else why it was not."""
        return self._act(_PRESS, element)

    def _point(self, element, clear=False):
        at = self._run(_script(_POINT, REF=element['ref'], URL=self._url, CLEAR=bool(clear),
                               WAS={key: element[key] for key in BOUND if key in element}), gesture=True)
        return at if isinstance(at, dict) and 'x' in at else str(at or 'changed')

    def click(self, element) -> str:
        """'' when the control was clicked for real, else why not."""
        at = self._point(element)
        if not isinstance(at, dict):
            return at
        self.page.click(at['x'], at['y'])
        self.page.settle()
        return ''

    def picture(self, element):
        """A JPEG of the page as it is on screen, with that control inside a red box, or None. For the
        models that judge a press (agent.judge, agent.review): they see what the person would. None on a
        page with a password, code or card field on screen, when the page moved while it was taken, or on
        any failure."""
        try:
            from PIL import Image, ImageDraw

            def where(scroll):
                return self._run(_script(_BOX, REF=element['ref'], URL=self._url, SCROLL=scroll,
                                         WAS={key: element[key] for key in BOUND if key in element}),
                                 seconds=PICTURE_SECONDS)
            box = where(True)
            if not isinstance(box, dict) or not box.get('vw') or box.get('w', 0) <= 0 or box.get('h', 0) <= 0:
                return None
            data = self.page.call('Page.captureScreenshot', {'format': 'jpeg', 'quality': 75,
                                                             'captureBeyondViewport': False},
                                  seconds=PICTURE_SECONDS)['data']
            # The same control at the same place before and after: else the box would sit on something else.
            if where(False) != box:
                return None
            image = Image.open(io.BytesIO(base64.b64decode(data))).convert('RGB')
            scale = image.width / float(box['vw'])
            draw = ImageDraw.Draw(image)
            left, top = box['x'] * scale - 4, box['y'] * scale - 4
            right, bottom = (box['x'] + box['w']) * scale + 4, (box['y'] + box['h']) * scale + 4
            draw.rectangle((max(left, 0), max(top, 0), min(right, image.width - 1), min(bottom, image.height - 1)),
                           outline=(255, 0, 0), width=max(3, round(3 * scale)))
            if image.width > PICTURE_WIDTH:
                image = image.resize((PICTURE_WIDTH, round(image.height * PICTURE_WIDTH / image.width)))
            out = io.BytesIO()
            image.save(out, format='JPEG', quality=75)
            return out.getvalue()
        except (CdpError, OSError, ValueError, KeyError, TypeError, ArithmeticError, ImportError):
            return None   # a picture is a help, never a reason to stop: the readers go on with the text

    def type(self, element, text, *, secret=False) -> str:
        """'' when `text` was typed into that very field (emptied first), else why
        not. Nothing is typed unless the field itself holds the focus; a
        `secret` only into a password field."""
        at = self._point(element, clear=True)
        if not isinstance(at, dict):
            return at
        self.page.click(at['x'], at['y'])
        if self._run(_script(_FOCUSED, REF=element['ref'], SECRET=bool(secret))) is not True:
            return 'not_focused'
        self.page.insert(text)
        return ''

    def landed_on_a_page(self) -> bool:
        """After a press: an HTML page, not a cart's JSON or an error."""
        try:
            self._world()
            kind = self._run("[document.contentType, document.title, document.body ? document.body.innerText.slice(0, 200) : '']")
        except CdpError:
            return False
        if not isinstance(kind, list) or len(kind) != 3:
            return False
        content_type, title, start = (str(value or '') for value in kind)
        # A product title says "500 ml"; an error page's title is the status itself.
        error = re.match(r'\s*(?:http\s*|(?:erro|error)\s*)?(4\d\d|5\d\d)(?!\s*(?:ml|g|kg|w|gb|mb|mm|cm|l)\b)\b',
                         title, re.I)
        # JSON shown as a page opens with {" or [{ / [" / [1: "[Promoção] Frete" is text.
        bare_json = re.match(r'\s*(\{\s*["}]|\[\s*([\[{"\]\d-]|true|false|null))', start)
        return content_type == 'text/html' and not bare_json and not error

    def search(self, element, text) -> str:
        return self._act(_SEARCH, element, TEXT=text)
