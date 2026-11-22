"""A Gmail message reduced to the little text a model may see.

All of it is hostile input. Sizes are capped before any pattern runs and every
pattern here is linear on what it gets: one crafted mail must not hold a worker.
(html.parser is not used: on Python 3.10 it is quadratic on unclosed tags.)

Secrets have two separate defences, so neither has to be perfect:
- codes are MASKED in every mail, whatever it is (a false hit costs a number);
- a mail is DROPPED only when delivering a code or a reset is what it does
  (a false hit here would cost the bill, so this one is narrow).
"""
import base64
import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import getaddresses

from assistant.calendar_context import _HIDDEN

from . import config

MAX_PARTS = 20
MAX_TOTAL_BYTES = 200_000  # decoded, all parts together
MAX_DEPTH = 10
MAX_HEADER = 2000
MAX_BODY = 20_000
CODE = '[código]'

ADDRESS = re.compile(
    r"[A-Za-z0-9._%+'=&-]{1,64}@(?:[A-Za-z0-9-]{1,63}\.){1,8}[A-Za-z]{2,24}", re.ASCII)
_ADDRESS_IN_TEXT = re.compile(r'(?<![\w.+-])[\w.+-]{1,64}@[\w.-]{1,255}')
_URL = re.compile(r'(?<![\w+.-])[a-z][a-z0-9+.-]{0,15}://\S+|(?<!\w)www\.\S+', re.IGNORECASE)
# Searched inside one word at a time. The label after the dot is letters, so amounts and dates stay.
_SITE = re.compile(r'[^\W_]\.(?:xn--|[^\W\d_]{2})', re.IGNORECASE)
_NOT_SITES = {'ee.uu', 'ee.uu.', 'ee.uu,', '(ee.uu.)', '(ee.uu)'}
_DOTS = str.maketrans({chr(0x3002): '.', chr(0x2024): '.', chr(0xFF0E): '.', chr(0xFF61): '.'})

# Emoji joiner and presentation selector: kept, one at a time, so emoji and
# reply subjects survive. A run of them is a hidden channel and is dropped.
_JOINERS = {chr(0x200D), chr(0xFE0F)}
_MAX_MARKS = 4


def visible(value) -> str:
    out, marks, joiner = [], 0, False
    for char in str(value or ''):
        if char in _JOINERS:
            if not joiner and out:
                out.append(char)
                joiner = True
            continue
        category = unicodedata.category(char)
        if category in ('Cf', 'Cs') or _HIDDEN.match(char):
            continue
        if category[0] == 'M':
            marks += 1
            if marks > _MAX_MARKS:
                continue  # also keeps normalisation linear
        else:
            marks = 0
        joiner = False
        out.append(' ' if category == 'Cc' and char != '\n' else char)
    return unicodedata.normalize('NFC', ''.join(out))


def one_line(value, limit=200) -> str:
    return ' '.join(visible(str(value or '')[:MAX_HEADER * 2]).split())[:limit]


def _folded(value) -> str:
    return unicodedata.normalize('NFKC', value).translate(_DOTS)


def _is_site(word) -> bool:
    plain = _folded(word)
    return bool(_SITE.search(plain)) and plain.lower() not in _NOT_SITES


def redact_links(value) -> str:
    parts = re.split(r'(\s+)', _URL.sub('[enlace]', value))
    return ''.join('[enlace]' if part and not part.isspace() and _is_site(part) else part for part in parts)


def redact_for_answer(value) -> str:
    """An answer must not carry an address or a site planted in a mail."""
    folded = _folded(value) if '@' in _folded(value) else value
    return redact_links(_ADDRESS_IN_TEXT.sub('[correo]', folded))


# ---------------------------------------------------------------------- HTML

# html.unescape raises on references of thousands of digits.
_HUGE_REFERENCE = re.compile(r'&#(?:x[0-9a-f]{8,}|[0-9]{8,});?', re.IGNORECASE)
_TAG_NAME = re.compile(r'(/?)([a-z][a-z0-9]{0,15})', re.IGNORECASE)
_TAG_MARK = re.compile(r'[>"\']')
_QUOTED = re.compile(r'"[^"]*"|\'[^\']*\'')
_HIDDEN_ATTR = re.compile(r'(?<![\w-])hidden(?![\w-])', re.IGNORECASE)
_HIDDEN_STYLE = re.compile(
    r'(?<![\w-])(?:display\s{0,5}:\s{0,5}none|visibility\s{0,5}:\s{0,5}hidden'
    r'|opacity\s{0,5}:\s{0,5}0(?![\w.%])|max-height\s{0,5}:\s{0,5}0(?:px)?(?![\w.%]))', re.IGNORECASE)
_FONT_SIZE = re.compile(r'(?<![\w-])font-size\s{0,5}:\s{0,5}([0-9.]{1,6}|[a-z-]{1,12})', re.IGNORECASE)
_RAW = {name: re.compile(f'</{name}', re.IGNORECASE) for name in ('script', 'style', 'template', 'title')}
_FONT_SHORTHAND = re.compile(r'(?<![\w-])font\s{0,3}:[^;"\']{0,40}?(?<![\d.])([1-9]\d{0,2})(?:\.\d{1,2})?(?:px|pt|em|rem)', re.IGNORECASE)
# Opening one of these closes an open one of the same name.
_SELF_CLOSING = {'p', 'li', 'tr', 'td', 'th'}
_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}
_BREAK = {'br', 'p', 'div', 'tr', 'li', 'table', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}
_SPACE = {'td', 'th'}
_CLOSE_SEARCH = 256
_MAX_ATTRIBUTES = 8000


def _unescaped(value) -> str:
    return html.unescape(_HUGE_REFERENCE.sub('', value))


def _tag_end(markup, i) -> int:
    """The '>' that ends a tag, skipping quoted values. -1 when the tag never ends."""
    while True:
        mark = _TAG_MARK.search(markup, i)
        if not mark:
            return -1
        char = mark.group()
        if char == '>':
            return mark.start()
        # A quote opens a value only right after '='.
        before = markup[max(i, mark.start() - 6):mark.start()].rstrip()
        if not before.endswith('='):
            i = mark.end()
            continue
        closing = markup.find(char, mark.end())
        if closing < 0:
            return -1
        i = closing + 1


def html_to_text(markup) -> str:
    """Linear scan: every step moves forward, every search is a plain find.

    font-size:0 hides only until a descendant sets a size (MJML wraps every
    section that way). When that leaves nothing at all, the sizes came from a
    stylesheet we don't read: then font-size is ignored.
    """
    strict, loose = _scan(markup)
    return strict if strict.strip() else loose


def _scan(markup):
    strict, loose, open_tags = [], [], []
    hidden, i, end = 0, 0, len(markup)

    def zero():
        return bool(open_tags) and open_tags[-1][2]

    def emit(value, structural=False):
        if hidden:
            return
        loose.append(value)
        if structural or not zero():
            strict.append(value)

    while i < end:
        start = markup.find('<', i)
        if start < 0:
            start = end
        if not hidden and start > i:
            emit(_unescaped(markup[i:start]))
        if start >= end:
            break
        if markup.startswith('<!--', start):
            close = markup.find('-->', start + 4)
            if close < 0:
                break
            i = close + 3
            continue
        following = markup[start + 1:start + 2]
        if not (following.isalpha() or following in ('/', '!', '?')):
            emit('<')
            i = start + 1
            continue
        close = _tag_end(markup, start + 1)
        if close < 0:
            break  # an unfinished tag: nothing after it is text
        inside, i = markup[start + 1:min(close, start + 1 + _MAX_ATTRIBUTES)], close + 1
        match = _TAG_NAME.match(inside)
        if not match:
            continue
        closing, name = match.group(1), match.group(2).lower()
        if name in _BREAK:
            emit('\n', True)
        elif name in _SPACE:
            emit(' ', True)
        elif name == 'sup' and not closing and strict and strict[-1][-1:].isdigit():
            emit(',')  # 1.234<sup>56</sup> is 1.234,56
        if closing:
            lowest = max(len(open_tags) - _CLOSE_SEARCH, 0)
            for index in range(len(open_tags) - 1, lowest - 1, -1):
                if open_tags[index][0] == name:
                    hidden -= sum(1 for tag in open_tags[index:] if tag[1])
                    del open_tags[index:]
                    break
            continue
        if name in _RAW:
            found = _RAW[name].search(markup, i)
            if not found:
                break
            after = markup.find('>', found.end())
            if after < 0:
                break
            i = after + 1
        elif name not in _VOID:
            # HTML ignores '/>' on these: <div hidden/> opens a div.
            attributes = _unescaped(inside[match.end():])
            is_hidden = bool(_HIDDEN_STYLE.search(attributes) or _HIDDEN_ATTR.search(_QUOTED.sub('', attributes)))
            if name in _SELF_CLOSING and open_tags and open_tags[-1][0] == name:
                hidden -= open_tags.pop()[1]
            size = _FONT_SIZE.search(attributes) or _FONT_SHORTHAND.search(attributes)
            no_size = not size.group(1).strip('0.') if size else zero()
            open_tags.append((name, is_hidden, no_size))
            hidden += is_hidden
    return ''.join(strict), ''.join(loose)


# -------------------------------------------------------------------- secrets

_WORD = r'(?:c[oó]digo|code|clave|pin|nip|otp|senha|contrase[ñn]a|password|passcode|token|n[uú]mero de verifica\w{1,8})'
_CODE_WORD = re.compile(rf'\b{_WORD}\b', re.IGNORECASE)
# What a code looks like: 4–8 digits, 123-456, 4 8 2 9 1 3, or letters and digits mixed.
_TOKEN = re.compile(
    r'(?<![\w.,/$])(?<!\d[ -])(?:'
    r'(?!(?:19|20)\d\d(?!\d))\d{4,8}'
    r'|\d{3}[ -]\d{3}'
    r'|\d(?: \d){3,7}'
    r'|(?=[A-Z-]{0,11}\d)(?=[0-9-]{0,11}[A-Z])[A-Z0-9-]{5,12}'
    r')(?![\w/]|[.,]\d| \d)')
_MONEY_BEFORE = re.compile(
    r'(?:[$€]|\b(?:bs\.?|clp|cop|ars|usd|pyg|mxn|pen|brl|ves|uyu|gs\.?|s/|monto|total|valor|importe|amount'
    r'|cuota de|cuota|pagar|pague|saldo|pago de|m[ií]nimo|abono|deuda|l[ií]mite disponible|precio|pre[çc]o))[\s:]{0,4}$', re.IGNORECASE)
_MONEY_AFTER = re.compile(
    r'\s{0,2}(?:pesos|bs\b|usd|clp|cop|ars|reais|soles|d[oó]lares|bol[ií]vares|guaran[ií]es)', re.IGNORECASE)
_GIVEN_BEFORE = re.compile(r'\s{0,3}(?:es|is|é|e o|é o|como|as)\b', re.IGNORECASE)
_SIGN_IN = re.compile(
    r'iniciar sesi[oó]n|inicio de sesi[oó]n|\bsign[ -]in\b|\blog[ -]in\b|\blogin\b|para autorizar|to authorize'
    r'|fazer login|para entrar', re.IGNORECASE)
_PASSWORD_VALUE = re.compile(
    r'\b(?:contrase[ñn]a|password|senha|clave|pin|passcode)(?: temporal| tempor[aá]ria)?'
    r'\s{0,2}(?::|\bes\b|\bis\b|\bé\b)\s{0,3}(\S{4,64})', re.IGNORECASE)
AFTER, BEFORE = 50, 25
# 30-NOV-2026, 12DEC2026: how LATAM statements and tickets write dates.
_MONTH_DATE = re.compile(
    r'(?:[0-3]?\d-?)?(?:ENE|JAN|FEB|FEV|MAR|ABR|APR|MAY|MAI|JUN|JUL|AGO|AUG|SEP|SET|OCT|OUT|NOV|DIC|DEC|DEZ)-?\d{2,4}'
    r'|[0-3]?\d-?(?:ENE|JAN|FEB|FEV|MAR|ABR|APR|MAY|MAI|JUN|JUL|AGO|AUG|SEP|SET|OCT|OUT|NOV|DIC|DEC|DEZ)')
_PREFIXED_AMOUNT = re.compile(r'(?:Q|RD|BS|GS|S)\d{2,8}')
# The usual layout: a sentence about the code, then the code alone on its line or after a closing colon.
_LINE_CODE = re.compile(rf'(?:^|:)[ \t]{{0,3}}({_TOKEN.pattern})[ \t.]{{0,3}}$', re.MULTILINE)
LEAD = 240


def _line_codes(value):
    """(start, stop, the text leading up to it) for codes set apart from the sentence about them."""
    for match in _LINE_CODE.finditer(value):
        start, stop = match.span(1)
        lead = value[max(start - LEAD, 0):start].rstrip()
        previous = lead.rsplit('\n', 1)[-1]
        if _CODE_WORD.search(previous) and not _is_money(value, start, stop):
            yield start, stop, previous


def _is_money(value, start, stop) -> bool:
    token = value[start:stop]
    if _MONTH_DATE.fullmatch(token) or _PREFIXED_AMOUNT.fullmatch(token):
        return True  # a date or an amount: never a code
    return bool(_MONEY_BEFORE.search(value[max(start - 18, 0):start]) or _MONEY_AFTER.match(value, stop))


def mask_codes(value) -> str:
    """Runs on every mail, dropped or not: numbers beside a code word go."""
    tokens = [(m.start(), m.end()) for m in _TOKEN.finditer(value)]
    spans = []

    def mark(word_start, word_end, before_needs_link):
        nonlocal first
        while first < len(tokens) and tokens[first][1] < word_start - BEFORE:
            first += 1
        index = first
        while index < len(tokens) and tokens[index][0] <= word_end + AFTER:
            start, stop = tokens[index]
            index += 1
            if stop <= word_start and before_needs_link and not _GIVEN_BEFORE.match(value[stop:word_start]):
                continue
            if not _is_money(value, start, stop):
                spans.append((start, stop))
            if index - first > 20:
                break  # enough in one window

    for pattern, needs_link in ((_CODE_WORD, True), (_SIGN_IN, False)):
        first = 0
        for word in pattern.finditer(value) if tokens else ():
            mark(word.start(), word.end(), needs_link)
    for start, stop, _lead in _line_codes(value):
        spans.append((start, stop))
    for match in _PASSWORD_VALUE.finditer(value):
        secret = match.group(1)
        if any(char.isdigit() for char in secret) or any(char.isupper() for char in secret[1:]):
            spans.append(match.span(1))

    out, position = [], 0
    for start, stop in sorted(set(spans)):
        if start < position:
            position = max(position, stop)
            continue
        out.append(value[position:start])
        out.append(CODE)
        position = stop
    out.append(value[position:])
    return ''.join(out)


_AUTH_KIND = (r'(?:verifica\w{1,10}|seguridad|seguran[çc]a|acceso|acesso|autentica\w{1,10}|autoriza\w{1,8}'
              r'|login|inicio de sesi[oó]n|un solo uso|uso [uú]nico)')
# Nouns that make "tu código" an identifier, not a secret.
_ID_NOUN = (r'(?:pago|pagamento|pix|barra|reserva|cliente|promo|descuento|desconto|cupom|cup[oó]n|compra|socio'
            r'|deudor|cuenta|conta|instala|suministro|seguimiento|rastre|referencia|qr|boleto|localizador|cip|convenio|entrada|evento)')
_AUTH_SUBJECT = re.compile(
    rf'\b(?:c[oó]digo|code|clave|senha|contrase[ñn]a|passcode)\s+(?:de\s+|do\s+)?(?:{_AUTH_KIND}|din[aá]mica|temporal|tempor[aá]ria)'
    r'|\b(?:verification|security|login|log-in|sign-in|one-time|authentication|temporary|access)\s+(?:code|link|passcode|password)\b'
    r'|\b(?:reset|restable\w{1,8}|recuper\w{1,8}|redefin\w{1,8}|forgot|olvid\w{1,6}|esquec\w{1,6})\s+'
    r'(?:(?:your|tu|su|sua|la|de|a)\s+){0,2}(?:password|contrase[ñn]a|clave|senha)\b'
    r'|\bpassword reset\b|\bmagic link\b|\bclave din[aá]mica\b|\bOTP\b'
    rf'|\b(?:tu|su|seu) c[oó]digo\b(?! (?:(?:de|do|da) )?{_ID_NOUN})'
    r'|\bes tu c[oó]digo\b|\bis your (?:[\w.]{1,20} ){0,3}code\b|\byour code\b'
    r'|\b(?:enlace|link) (?:de |para )?(?:acceso|acesso|iniciar sesi[oó]n|login|sign in)\b',
    re.IGNORECASE)
# A phrase that hands a code over. It counts only with a code right beside it.
_DELIVERS_AFTER = re.compile(
    rf'\b(?:c[oó]digo|code|clave) (?:de |do )?{_AUTH_KIND}'
    r'|\b(?:verification|security|access|login|sign-in|one-time|authentication) (?:code|passcode|pin)\b'
    r'|\bclave din[aá]mica\b|\bOTP\b'
    r'|\b(?:tu|su|seu) c[oó]digo(?: (?:es|é))\b'
    rf'|\b(?:tu|su|seu) c[oó]digo (?:de |do )(?!{_ID_NOUN})[\w.-]{{1,20}} (?:es|é)\b'
    r'|\byour code(?: is)?\b'
    r'|\b(?:usa|use|usar|ingresa|ingrese|digite|enter) (?:el |o |the )?(?:c[oó]digo|code)\b',
    re.IGNORECASE)
_DELIVERS_BEFORE = re.compile(
    r'\bes tu c[oó]digo\b|\bis your (?:[\w.]{1,20} ){0,3}code\b|\b(?:é|e) (?:o )?seu c[oó]digo\b'
    r'|\bpara (?:iniciar sesi[oó]n|autorizar|fazer login)\b|\bto (?:sign in|log in|authorize)\b',
    re.IGNORECASE)
_CONFIRMATION = re.compile(
    r'\bc[oó]digo de confirma\w{1,8}|\bconfirmation code\b', re.IGNORECASE)
_RESET = re.compile(
    r'\b(?:restablecer|restablece|reset|redefinir|redefina|recuperar|recupera) '
    r'(?:(?:your|tu|su|sua|la|a) ){0,2}(?:password|contrase[ñn]a|clave|senha)\b'
    r'|\bmagic link\b|\bsign-in link\b|\blink de acesso\b|\benlace (?:de acceso|para iniciar sesi[oó]n)\b',
    re.IGNORECASE)
# "Nunca te pediremos tu clave" is advice. It stops at ':' so "no compartas este código: 4821" still counts.
_ADVICE = re.compile(
    r'\b(?:nunca|jam[aá]s|never|no|não|nao) (?:te |le |lhe |you |will |vamos |iremos )?'
    r'(?:compartas|comparta|compartir|compartilhe|pediremos|pedimos|pedir|solicitamos|solicitaremos|share|ask|informe|revele)'
    r'[^.:\n\d]{0,90}', re.IGNORECASE)
# In a bill, "usa el código" is a coupon or a payment reference and "código de acceso" a ticket or a
# door, unless it is the person's own code or it says it signs in, confirms or expires in minutes.
_WEAK_DELIVERY = re.compile(r'^(?:usa|use|usar|ingresa|ingrese|digite|enter)\b|acc?es[os]|autoriza', re.IGNORECASE)
_OWNED = re.compile(r'^(?:tu|su|seu|your)\b', re.IGNORECASE)
_AUTH_PURPOSE = re.compile(
    r'\bpara (?:iniciar sesi[oó]n|confirmar|verificar|autorizar|aprobar|aprovar|continuar|fazer login)'
    r'|\bto (?:sign in|log in|verify|authorize|confirm)\b'
    r'|\b(?:vence|expira|v[aá]lido por|expires) (?:en |em |in )?\d{1,3} ?min', re.IGNORECASE)
# Invoices print a "verification code" of their own.
_FISCAL = re.compile(r'\b(?:nota fiscal|nfs?-?e|danfe|cfdi|cufe|documento fiscal|factura electr[oó]nica)\b', re.IGNORECASE)
_NEED = re.compile(
    r'\b(?:facturas?|faturas?|invoice|bill|boletos?|boletas?|recibo|cuota|parcela|pagos?|pagamento|payment|due'
    r'|vence|vencen|vencimiento|vencimento|reservas?|reservaci[oó]n|reservation|booking|vuelo|voo|flight|check-in'
    r'|itiner[aá]\w{0,8}|pasajes?|passagem|entradas?|ingressos?|tickets?|departs|impuesto|imposto|alquiler|aluguel'
    r'|estado de cuenta|extracto|statement|nota fiscal|nfs?-?e|comprobante|comprovante|concierto|evento|total)\b', re.IGNORECASE)


def _delivers(value, fiscal, need) -> bool:
    for match in _DELIVERS_AFTER.finditer(value):
        said = match.group()
        if fiscal and 'verifica' in said.lower():
            continue
        if (need and _WEAK_DELIVERY.search(said) and not _OWNED.match(said)
                and not _AUTH_PURPOSE.search(value[match.start():match.end() + 120])):
            continue
        window = value[match.end():match.end() + 40]
        token = _TOKEN.search(window)
        if token and not _is_money(window, token.start(), token.end()):
            return True
    for match in _DELIVERS_BEFORE.finditer(value):
        if _TOKEN.search(value[max(match.start() - 24, 0):match.start()]):
            return True
    if not need:
        for _start, _stop, lead in _line_codes(value):
            if not re.search(rf'c[oó]digo (?:de |do |da )?{_ID_NOUN}', lead, re.IGNORECASE):
                return True
        for match in _CONFIRMATION.finditer(value):
            if _TOKEN.search(value[match.end():match.end() + 40]):
                return True
    return False


def carries_secret(subject, body) -> bool:
    """Only for mail whose job is the code or the reset. Everything else is kept, masked."""
    fiscal = bool(_FISCAL.search(subject) or _FISCAL.search(body))
    stated = _ADVICE.sub(' ', subject)
    found = _AUTH_SUBJECT.search(stated)
    if found:
        # With the words after it: "tu código" alone doesn't say of what.
        said = stated[found.start():found.end() + 20].lower()
        invoices_own = fiscal and 'verifica' in said
        # "Código de acceso para el concierto", "Factura: clave de acceso".
        ticket_or_bill = re.search(r'acceso|acesso|autoriza', said) and _NEED.search(subject)
        if not invoices_own and not ticket_or_bill:
            return True
    need = bool(_NEED.search(subject) or _NEED.search(body))
    said = _ADVICE.sub(' ', f'{subject}\n{body}')
    return _delivers(said, fiscal, need) or (not need and bool(_RESET.search(said)))


# ------------------------------------------------------------------- headers

def _decoded(value):
    raw = str(value or '')[:MAX_HEADER]
    try:
        return str(make_header(decode_header(raw)))[:MAX_HEADER]
    except Exception:  # noqa: BLE001 - a malformed header is shown as it came
        return raw


def addresses(value) -> list:
    """Bare addresses of a header. Empty when any of them is not a plain address."""
    raw = str(value or '')
    if len(raw) > MAX_HEADER:
        return []
    try:
        found = [address for _name, address in getaddresses([raw]) if address]
    except Exception:  # noqa: BLE001 - nested comments recurse until Python gives up
        return []
    return found if all(len(a) <= 254 and ADDRESS.fullmatch(a) for a in found) else []


# Cyrillic and Greek letters that draw like the ones in "confio".
_LOOKALIKE = str.maketrans({chr(code): plain for code, plain in (
    (0x0441, 'c'), (0x03F2, 'c'), (0x043E, 'o'), (0x03BF, 'o'), (0x0456, 'i'), (0x03B9, 'i'), (0x0578, 'n'),
    (0x03CC, 'o'), (0x0421, 'c'), (0x041E, 'o'), (0x039F, 'o'), (0x0406, 'i'), (0x0399, 'i'))})
_CONFIO = re.compile(r'(?<![^\W_])conf[ií]o(?![^\W_])', re.IGNORECASE)


@dataclass
class Mail:
    id: str
    thread_id: str
    headers: dict
    body: str
    sent_at: datetime
    sent: bool = False  # Gmail's own SENT label. The From header proves nothing.
    utc_offset: int = config.DEFAULT_OFFSET  # the reader's, set by whoever knows the person

    @property
    def sender(self):
        """The real address always shows. The chosen name is dropped if it imitates an address or a site."""
        found = addresses(self.headers.get('from'))
        if len(found) != 1:
            return '(remitente no válido)'
        try:
            name = getaddresses([str(self.headers.get('from', ''))[:MAX_HEADER]])[0][0]
        except Exception:  # noqa: BLE001 - as in addresses()
            name = ''
        name = one_line(_decoded(name), 120)
        plain = _folded(name)
        if not name or '@' in plain or '<' in plain:
            return found[0]
        domain = '.' + found[0].rpartition('@')[2].lower()
        for word in plain.split():
            # Booking.com may be named Booking.com. Nobody else may.
            if _is_site(word) and not domain.endswith('.' + word.lower().strip('.,()')):
                return found[0]
        return f'{name[:60]} <{found[0]}>'

    @property
    def subject(self):
        # No '=?': the email library would decode it into text the person was never shown.
        return one_line(_decoded(self.headers.get('subject')), 200).replace('=?', '= ?')

    @property
    def is_security(self) -> bool:
        return carries_secret(self.subject, self.body)

    @property
    def claims_confio(self) -> bool:
        shown = _folded(visible(_decoded(self.headers.get('from')))).translate(_LOOKALIKE)
        return bool(_CONFIO.search(shown))

    def for_model(self, limit) -> dict:
        # Masked over all of it, then cut: a cut first could split a code from its word.
        masked = mask_codes(f'{self.subject}\n{self.body}')
        subject, _, body = masked.partition('\n')
        return {'de': self.sender, 'asunto': redact_links(subject),
                # The day it arrived for this person, so "vence mañana" counts from the right one.
                'fecha': config.local_today(self.sent_at, self.utc_offset).isoformat(),
                'texto': redact_links(body)[:limit]}


# --------------------------------------------------------------------- parse

_CHARSET = re.compile(r'charset\s{0,3}=\s{0,3}"?([\w.:-]{1,30})', re.IGNORECASE)
_SAFE_CHARSET = re.compile(r'(?:iso-?8859-\d{1,2}|windows-125\d|cp125\d|latin-?1)$', re.IGNORECASE)
_STUB = re.compile(
    r'does not support html|not support html|view (?:this|it) (?:email|message|in)|no (?:puede|puedes|consigue)'
    r' (?:ver|visualizar)|n[ãa]o consegue visualizar|no soporta html|versi[oó]n html|ver (?:este correo|en el navegador)',
    re.IGNORECASE)


def _decode(raw: bytes, part) -> str:
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        pass
    for header in (part.get('headers') or [])[:30]:
        if str(header.get('name', '')).lower() != 'content-type':
            continue
        found = _CHARSET.search(str(header.get('value', ''))[:MAX_HEADER])
        if found and _SAFE_CHARSET.match(found.group(1)):
            try:
                return raw.decode(found.group(1), errors='replace')
            except LookupError:
                break
    return raw.decode('utf-8', errors='replace')


def _bodies(payload) -> list:
    found, left = [], MAX_TOTAL_BYTES
    queue, seen = [(payload, 0)], 0
    while queue and left > 0 and len(found) < MAX_PARTS and seen < 200:
        part, depth = queue.pop(0)
        seen += 1
        if not isinstance(part, dict) or part.get('filename') or depth > MAX_DEPTH:
            continue  # no attachments
        mime, data = part.get('mimeType'), (part.get('body') or {}).get('data')
        if mime in ('text/plain', 'text/html') and data:
            data = str(data)[:(left // 3) * 4]
            try:
                raw = base64.urlsafe_b64decode(data + '=' * (-len(data) % 4))
            except ValueError:
                continue
            left -= max(len(raw), 1)
            found.append((mime, _decode(raw, part)))
        queue.extend((child, depth + 1) for child in (part.get('parts') or [])[:MAX_PARTS])
    return found


def _tidy(value) -> str:
    lines = (' '.join(line.split()) for line in visible(value).split('\n'))
    return '\n'.join(line for line in lines if line)[:MAX_BODY]


def _best_body(plain, rich) -> str:
    """Many senders' plain part is a stub pointing at the HTML one."""
    if not rich:
        return plain
    words = _URL.sub('', plain).strip()
    stub = len(words) < 80 or (len(words) < 500 and (_STUB.search(words) or len(rich) >= 2 * len(words)))
    return rich if stub else plain


def parse(message) -> Mail:
    payload = message.get('payload') or {}
    headers = {}
    for header in (payload.get('headers') or [])[:200]:
        # Over the cap on purpose, so a too-long recipient header is refused instead of cut.
        headers.setdefault(str(header.get('name', '')).lower(), str(header.get('value', ''))[:MAX_HEADER * 4])
    found = _bodies(payload)
    plain = _tidy('\n'.join(body for mime, body in found if mime == 'text/plain'))
    rich = _tidy('\n'.join(html_to_text(body) for mime, body in found if mime == 'text/html'))
    try:
        sent_at = datetime.fromtimestamp(int(message.get('internalDate', 0)) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        sent_at = datetime.now(timezone.utc)
    return Mail(str(message.get('id', '')), str(message.get('threadId', '')), headers, _best_body(plain, rich),
                sent_at, sent='SENT' in (message.get('labelIds') or []))
