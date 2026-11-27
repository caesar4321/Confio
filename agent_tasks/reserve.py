"""A reservation: a hotel room, a table, a bus or plane seat, an appointment, on the site the person named.

Founder, 2026-11-27: the agent books only what needs no card. It searches with the dates and people the
person said, fills the site's form, and stops at the button that makes the booking: the person approves
exactly that in the chat (the same card as a request about an order, manage.py), and it is pressed once.
A booking that asks for a card, even as a guarantee, is never made: the agent says so and the assistant can
write to the place on WhatsApp instead.

The guest's details (name, e-mail, phone and, for a ticket, the verified document and birth date) are typed
by code, never by a model, and only after the person approved that list for this site on a card. The model
only says which field is which. Anything else it types is a search: words of the person's own request,
dates, times and counts, never a long number.
"""
import logging
import re

from django.utils import timezone

from . import agent, guard, notes, sites
from .manage import answer as _answer, clean_answer
from .operate import (NOT_A_FORM, REFUSED, MAX_SAME_PRESS, _PAYMENT_FIELD, _identity, _label, _trace, count,
                      counted, sign_in)

logger = logging.getLogger(__name__)

# A first "Reservar" may only open the confirmation step: one more press, under its own approval.
MAX_BOOKINGS = 2
MAX_TYPED = 30
MAX_GUEST_FILLS = 6
MAX_ESCAPES = 6
# A card's holder field is a card's, whatever it is called beside it.
_CARD_HOLDER = re.compile(r'holder|cc[-_ ]?name|card[-_ ]?name|nombre (en|de) la tarjeta|nome (no|do) cartao|titular (de|da) (la )?(tarjeta|cartao)')
GUEST_KEYS = ('first_name', 'last_name', 'full_name', 'email', 'phone', 'document', 'birth_date', 'nationality',
              'address', 'city', 'state', 'postal_code', 'country')
_TYPED_KINDS = ('', 'text', 'search', 'number', 'date', 'time', 'tel')
# A field the model may never type into on its own: a person's details, a secret, a card, a code.
_PERSONAL = re.compile(r'e-?mail|correo|senha|password|contrasen|clave|tarjeta|card|cvv|cvc|cpf|cnpj|dni|cedula'
                       r'|pasaporte|passport|documento|document|rut\b|curp|nacimiento|birth|nome|nombre|name|apellido'
                       r'|sobrenome|telefono|telefone|phone|celular|movil|whatsapp|cupon|cupom|coupon|codigo|code')
_DATE = re.compile(r'\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}')
_CALENDAR_WORDS = set(
    'enero febrero marzo abril mayo junio julio agosto septiembre setiembre octubre noviembre diciembre '
    'janeiro fevereiro marco junho julho setembro outubro novembro dezembro january february march april may '
    'june july august september october november december jan feb mar apr jun jul aug sep sept oct nov dec '
    'ene abr ago dic lunes martes miercoles jueves viernes sabado domingo segunda terca quarta quinta sexta '
    'hoy manana am pm de del al y a para con en la el las los noche noches persona personas adulto adultos '
    'nino ninos crianca criancas habitacion habitaciones quarto quartos room rooms adults guests huespedes '
    'pasajero pasajeros passageiro passageiros ida vuelta volta mesa hs h'.split())


def reserving(task):
    return getattr(task, 'kind', 'buy') == 'reserve'


def payable_rail(task):
    """The way Confío pays this site's bookings now (Pix, SPEI, a Bolivian QR, Venezuela's Pago Móvil), or None:
    the site's country's rail, never one the person pays by hand."""
    from . import countries
    rail = countries.rail(task.country)
    return rail if rail is not None and rail.kind != 'manual' else None


def step(st, browser, reader, seen):
    """One step of a reservation."""
    task = st.task
    st.operating = True
    typed = (task.order or {}).get('guest_typed')
    if typed:
        # Her details are on this page now: no model ever reads them, in the text, a control or a picture.
        _hide(seen, task)
        seen.look = None
    else:
        seen.look = reader.picture   # what the judge sees: the page, with the control boxed
    _trace(st, seen)
    rail = payable_rail(task)
    if rail is not None and rail.method_id == 'mx_clabe':
        # Accounts written on pages before the booking is paid are never its own (spei._by_facts), as for an order.
        from . import spei
        known = (task.order or {}).get('seen_clabes') or []
        found = spei.clabes_in([seen.text]) - set(known)
        if found:
            st.save(order={**(task.order or {}), 'seen_clabes': [*known, *sorted(found)][-40:]})
    name, args = agent.reserve(task, seen, st.meter)
    if name == 'wait':
        st.delay = 2
        return st.remember('wait', 'ok')
    if name == 'close_popup':
        if count(task, 'escapes') >= MAX_ESCAPES:
            return st.remember('close_popup', 'refused: it did not close it; press its own close button or give up')
        browser.escape()
        browser.pump(1)
        return st.remember('close_popup', 'Escape pressed', counts=counted(task, 'escapes'))
    if name == 'give_up':
        reason = args.get('reason')
        why = notes.reason_text(args.get('why'))
        if (task.order or {}).get('submitted'):
            return st.stop('request_unclear', order={**(task.order or {}), 'why': why})
        if reason == 'needs_card':
            return st.stop('needs_card', order={**(task.order or {}), 'why': why})
        return st.stop('not_found' if reason == 'not_found' else 'cannot_do', order={**(task.order or {}), 'why': why})
    if name == 'sign_in':
        if not any(element.get('type') == 'password' or 'one-time-code' in str(element.get('autocomplete') or '')
                   for element in seen.elements):
            # A guest form has an e-mail field too: signing in there would type and send it unjudged.
            return st.remember('sign_in', 'refused: no password or code field here; fill_guest is for the guest')
        done = sign_in(st, browser, reader, seen, asked=True)
        return st.remember('sign_in', 'refused: no sign-in form on this page') if done is NOT_A_FORM else done
    if name == 'answer':
        return _answer(st, args.get('text'), seen)
    if name == 'cannot_pay':
        # Found, but Confío cannot pay it here (a card, or a way it does not pay): the options, and stop.
        if (task.order or {}).get('submitted'):
            # Something was sent already: never "nothing was booked".
            return st.stop('request_unclear')
        text, why = clean_answer(args.get('text'), seen)
        if not text:
            return st.remember('cannot_pay', f'refused: {why}')
        return st.stop('needs_card', order={**(task.order or {}), 'answer': text})
    if name == 'fill_guest':
        return fill_guest(st, reader, seen, args)
    element = seen.element(args.get('ref'))
    if element is None or element.get('disabled'):
        return st.remember(f'{name}'[:30], 'refused: no such control on this page')
    label = _label(element)
    where = st.fingerprint(seen.url)
    if name in ('type', 'choose') and ((task.order or {}).get('request_approved') or (task.order or {}).get('approved')):
        # A field changed after the person approved: what is booked may have changed, so it is asked again.
        st.save(order={**(task.order or {}), 'request_approved': None, 'approved': None})
    if name == 'type':
        return type_search(st, reader, seen, element, label, args.get('text'))
    if name == 'choose':
        return choose(st, reader, element, label, args.get('text'))
    if name == 'ready_to_book':
        return book(st, reader, browser, seen, element, label, where, args)
    if name == 'ready_to_pay':
        return pay(st, reader, browser, seen, element, label, where, args)
    if name != 'press':
        return st.remember(f'{name}'[:30], 'refused')
    did = f'press "{label}"'
    if (task.order or {}).get('request_approved') or (task.order or {}).get('approved'):
        # Anything pressed after the person approved may change what is booked: asked again.
        st.save(order={**(task.order or {}), 'request_approved': None, 'approved': None})
    if _judged(st, seen, element, label, did) is REFUSED:
        return None
    if sum(entry.get('at') == where and entry.get('did') == did[:120] for entry in (task.history or [])[-8:]) \
            >= MAX_SAME_PRESS:
        return st.remember(did, 'refused: already pressed twice here; do something else')
    st.save(history=[*(task.history or []), {'did': did[:120], 'result': 'pressed', 'at': where}][-st.HISTORY_KEPT:],
            steps=task.steps + 1, failures=0)
    refused = reader.click(element)
    if refused:
        st.save(history=(task.history or [])[:-1])
        return st.remember(did, f'refused: {refused}')
    browser.pump(2)
    return None


def _judged(st, seen, element, label, did):
    """As an order already placed (manage.py), with the reservation's words: what books is named with
    ready_to_book, never pressed; a card or the account is refused."""
    try:
        verdict, why = agent.judge(st.task, seen, element, st.meter)
    except agent.AgentUnavailable:
        verdict, why = 'unsure', 'the check could not run'
    if verdict == 'safe':
        return None
    if verdict == 'places_order':
        st.remember(did, f'refused: it makes the booking ({why}). Call ready_to_book with it.')
        return REFUSED
    if verdict == 'unsure':
        st.remember(did, f'refused: it is not clear what it does ({why}). If it makes the booking, call '
                         'ready_to_book with it; else find another way.')
        return REFUSED
    st.remember(did, f'refused: {verdict} ({why}). Never a card nor the account: if the booking needs a card, '
                     'call give_up with needs_card.')
    return REFUSED


# ------------------------------------------------------------------ what the model may type itself

def _fields_refusal(element):
    auto = str(element.get('autocomplete') or '')
    words = guard.fold(f"{element.get('name')} {element.get('label')} {element.get('placeholder') or ''}")
    if auto.startswith('cc-') or element.get('type') == 'password' or element.get('secret_form') \
            or _PAYMENT_FIELD.search(words):
        return 'a payment or secret field'
    if _PERSONAL.search(words) or _ADDRESS.search(words) or auto in (
            'email', 'tel', 'name', 'given-name', 'family-name', 'bday', 'country', 'country-name', 'postal-code') \
            or auto.startswith(('address', 'street', 'tel-', 'bday-')) or (element.get('type') or '') in ('email', 'tel'):
        return 'a field for the guest\'s details: use fill_guest'
    return ''


_ADDRESS = re.compile(r'direccion|address|calle|street|domicilio|endereco|postal|zip|\bcep\b')
_TIME_TOKEN = re.compile(r'\d{1,2}(:\d{2})?(hs|h|am|pm)')


def _plausible(date):
    """A real calendar date (2027-02-03, 03/02/2027, 3-2-27): a year of this era and a day and month that exist."""
    parts = [int(part) for part in re.split(r'[-/.]', date)]
    if len(parts) != 3:
        return False
    if len(re.split(r'[-/.]', date)[0]) == 4:
        year, first, second = parts
    else:
        first, second, year = parts
    year = year + 2000 if year < 100 else year
    return 2020 <= year <= 2035 and 1 <= first <= 31 and 1 <= second <= 31 and min(first, second) <= 12


def as_field_value(text, kind):
    """'2026-12-10' from '2026-12-10', '10/12/2026' or '10-12-26'; '21:00' from '21:00', '21h' or '9:30'. '' when it
    is not one (a date input takes only its ISO form)."""
    text = str(text or '').strip().lower()
    if kind == 'time':
        found = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?\s*(?:hs?|h)?', text)
        if not found or int(found.group(1)) > 23 or int(found.group(2) or 0) > 59:
            return ''
        return f'{int(found.group(1)):02d}:{int(found.group(2) or 0):02d}'
    found = re.fullmatch(r'(\d{4})-(\d{1,2})-(\d{1,2})', text)
    if found:
        year, month, day = (int(part) for part in found.groups())
    else:
        found = re.fullmatch(r'(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})', text)
        if not found:
            return ''
        day, month, year = (int(part) for part in found.groups())
        year = year + 2000 if year < 100 else year
    if not (2020 <= year <= 2035 and 1 <= month <= 12 and 1 <= day <= 31):
        return ''
    return f'{year:04d}-{month:02d}-{day:02d}'


def searchable(text, goal):
    """Text the model may type itself: words of the person's own request, dates, times and counts. Never a
    number of five digits or more that is not a date, and never a word she did not say."""
    text = ' '.join(str(text or '').split())[:60]
    if not text:
        return ''
    folded = guard.fold(text)
    if any(not _plausible(match.group(0)) for match in _DATE.finditer(folded)):
        return ''
    undated = _DATE.sub(' ', folded)
    # Counts, times and a date: never a run of digits that could be a card, a phone or a document.
    if re.search(r'\d{5,}', undated) or len(re.findall(r'\d', undated)) > 6:
        return ''
    for token in re.findall(r'[a-z0-9]+', undated):
        if re.search(r'[a-z]', token) and re.search(r'\d', token) and not _TIME_TOKEN.fullmatch(token):
            return ''
    said = set(re.findall(r'[a-z]{2,}', guard.fold(goal)))
    for word in re.findall(r'[a-z]{2,}', _DATE.sub(' ', folded)):
        if word not in said and word not in _CALENDAR_WORDS:
            return ''
    if '@' in text or re.search(r'https?:|www\.', folded):
        return ''
    return text


def type_search(st, reader, seen, element, label, text):
    task = st.task
    if count(task, 'typed') >= MAX_TYPED:
        return st.remember('type', 'refused: typed too often; book or give up')
    if element.get('tag') not in ('input', 'textarea') or (element.get('type') or '') not in _TYPED_KINDS:
        return st.remember('type', f'refused: "{label}" is not a text field')
    refusal = _fields_refusal(element)
    if refusal:
        return st.remember('type', f'refused: "{label}" is {refusal}')
    value = searchable(text, task.goal)
    if not value:
        return st.remember('type', 'refused: type only the person\'s own words, dates, times or counts')
    counts = counted(task, 'typed')
    kind = (element.get('type') or '').lower()
    if kind in ('date', 'time'):
        # The phone's own picker: its value is set as the field takes it (keys never reach it).
        value = as_field_value(value, kind)
        if not value:
            return st.remember('type', f'refused: write the {kind} as {"2026-12-10" if kind == "date" else "21:00"}',
                               counts=counts)
        done = reader.set_date(element, value)
        return st.remember(f'type "{label}"'[:60], f'refused: {done}' if done else f'set "{value}"', counts=counts)
    done = reader.type(element, value)
    return st.remember(f'type "{label}"'[:60], f'refused: {done}' if done else f'typed "{value}"', counts=counts)


def choose(st, reader, element, label, text):
    if element.get('tag') != 'select':
        return st.remember('choose', f'refused: "{label}" is not a dropdown; press its option instead')
    refusal = _fields_refusal(element)
    if refusal:
        return st.remember('choose', f'refused: "{label}" is {refusal}')
    value = searchable(text, st.task.goal)
    if not value:
        return st.remember('choose', 'refused: choose only the person\'s own words, dates, times or counts')
    done = reader.choose(element, value)
    return st.remember(f'choose "{label}"'[:60], f'refused: {done}' if done else f'chose "{value}"')


# ------------------------------------------------------------------ the guest's details

def guest_details(user):
    """The details code may type for the person, from their account and their verified identity: only
    what exists. {key: value}."""
    from security.identity_status import current_document
    details = {}
    document = current_document(user)
    first = str(getattr(document, 'verified_first_name', '') or '').strip() or str(user.first_name or '').strip()
    last = str(getattr(document, 'verified_last_name', '') or '').strip() or str(user.last_name or '').strip()
    if first:
        details['first_name'] = first.title() if first.isupper() else first
    if last:
        details['last_name'] = last.title() if last.isupper() else last
    if first or last:
        details['full_name'] = ' '.join(part for part in (details.get('first_name'), details.get('last_name')) if part)
    email = str(getattr(user, 'email', '') or '').strip()
    if '@' in email and not email.lower().endswith(('privaterelay.appleid.com', '.invalid')):
        details['email'] = email
    phone = re.sub(r'\D', '', str(getattr(user, 'phone_number', '') or ''))
    code = re.sub(r'\D', '', str(getattr(user, 'phone_country_code', '') or getattr(user, 'phone_country', '') or ''))
    if phone:
        details['phone'] = f'+{code}{phone}' if code and not phone.startswith(code) else (f'+{phone}' if code else phone)
    if document is not None:
        number = str(getattr(document, 'document_number', '') or '').strip()
        if number:
            details['document'] = number
        born = getattr(document, 'verified_date_of_birth', None)
        if born:
            details['birth_date'] = born.strftime('%d/%m/%Y')
        nationality = str(getattr(document, 'verified_nationality', '') or '').strip()
        if nationality:
            details['nationality'] = _country_name(nationality)
        for key, field in (('address', 'verified_address'), ('city', 'verified_city'), ('state', 'verified_state'),
                           ('postal_code', 'verified_postal_code'), ('country', 'verified_country')):
            value = ' '.join(str(getattr(document, field, '') or '').split())
            if value:
                details[key] = _country_name(value) if key == 'country' else value[:120]
    return details


def _country_name(value):
    """'AR' -> 'Argentina' (a site's dropdown shows names); anything else as written."""
    return notes.COUNTRY_NAMES.get(str(value).upper(), value) if len(str(value)) == 2 else value


# Each detail goes only into the site's own field for it: never a message to the host, a note, another field.
_FIELD_WORDS = {
    'first_name': r'nombre|name|first|given|primer|nome',
    'last_name': r'apellido|last|surname|family|sobrenome',
    'full_name': r'nombre|name|titular|huesped|guest|pasajero|passageiro|nome',
    'email': r'mail|correo',
    'phone': r'\btel\b|\btel\.|telefono|telefone|phone|celular|movil|whatsapp',
    'document': r'document|dni|cedula|\bci\b|pasaporte|passport|cpf|\brut\b|identidad|identificacion',
    'birth_date': r'nacimiento|birth|\bdob\b|nascimento|fecha de nac',
    'nationality': r'nacionalidad|nationality|nacionalidade|ciudadania',
    'address': r'direccion|address|calle|street|domicilio|endereco',
    'city': r'ciudad|city|localidad|cidade|municipio',
    'state': r'provincia|\bstate\b|\bestado\b(?! civil)|departamento',
    'postal_code': r'postal|zip|\bcep\b',
    'country': r'pais|country|\bregion\b',
}
_FIELD_AUTO = {'first_name': ('given-name',), 'last_name': ('family-name',), 'full_name': ('name',),
               'email': ('email',), 'phone': ('tel', 'tel-national'), 'birth_date': ('bday',),
               'address': ('street-address', 'address-line1'), 'city': ('address-level2',),
               'state': ('address-level1',), 'postal_code': ('postal-code',), 'country': ('country', 'country-name')}
_NOT_GUEST = re.compile(r'mensaje|message|comentario|comment|nota|note|solicitud|request|pedido especial|special'
                        r'|anfitrion|host|pregunta|question|cupon|cupom|coupon|promo|buscar|search|otro|other|'
                        r'acompanante|companion|segundo|second|adicional|civil|hora|llegada|arrival|horario'
                        r'|\b[2-9]\b|#\s?[2-9]')


def _field_is(key, element):
    auto = str(element.get('autocomplete') or '').lower()
    words = guard.fold(f"{element.get('name')} {element.get('label')} {element.get('placeholder') or ''}"
                       .replace('_', ' ').replace('-', ' ').replace('[', ' ').replace(']', ' '))
    if element.get('tag') == 'textarea' or _NOT_GUEST.search(words):
        return False
    if auto and any(auto == token or auto.endswith(' ' + token) for token in _FIELD_AUTO.get(key, ())):
        return True
    if key == 'email' and (element.get('type') or '') == 'email':
        return True
    if key == 'phone' and (element.get('type') or '') == 'tel':
        return True
    return bool(re.search(_FIELD_WORDS[key], words))


def guest_pattern(task):
    """What matches her typed details however a page writes them, or None (none were typed)."""
    if getattr(task, 'kind', 'buy') != 'reserve':
        return None
    keys = (getattr(task, 'order', None) or {}).get('guest_typed') or ()
    if not isinstance(keys, (list, tuple)) or not keys:
        return None
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.filter(pk=task.user_id).first()
    details = guest_details(user) if user is not None else {}
    parts = {'full_name': ('first_name', 'last_name', 'full_name')}
    hidden = ('first_name', 'last_name', 'full_name', 'email', 'phone', 'document', 'birth_date', 'address')
    values = [str(details[name]) for key in keys for name in parts.get(key, (key,))
              if name in hidden and name in details and len(str(details[name])) >= 3]
    if not values:
        return None
    pieces = []
    for value in sorted(values, key=len, reverse=True):
        digits = re.sub(r'\D', '', value)
        if len(digits) >= 6 and len(digits) >= len(re.sub(r'[\s+()./-]', '', value)) - 2:
            # A phone or a document, however the page writes it: "+591 7000 0009", "V-12.345.678".
            pieces.append(r'[^\w\s]{0,2}\s?'.join(digits[-8:]) if len(digits) > 8 else r'[\s.()-]{0,2}'.join(digits))
        else:
            pieces.append(rf'(?<!\w){re.escape(value)}(?!\w)')
    return re.compile('|'.join(pieces), re.I)


def _hide(seen, task):
    """Her typed details, wherever the page echoes them, become [dato]: the models and the trace never see them."""
    pattern = guest_pattern(task)
    if pattern is None:
        return
    seen.text = pattern.sub('[dato]', seen.text or '')
    seen.title = pattern.sub('[dato]', seen.title or '')
    for element in seen.elements:
        for key in ('label', 'placeholder', 'name'):
            if element.get(key):
                element[key] = pattern.sub('[dato]', str(element[key]))


_SHOWN = {'full_name': 'nombre', 'email': 'correo', 'phone': 'teléfono', 'document': 'documento',
          'birth_date': 'fecha de nacimiento', 'nationality': 'nacionalidad', 'address': 'dirección',
          'city': 'ciudad', 'state': 'provincia', 'postal_code': 'código postal', 'country': 'país'}
_ORDER = ('full_name', 'email', 'phone', 'document', 'birth_date', 'nationality', 'address', 'city', 'state',
          'postal_code', 'country')


def _masked(key, value):
    if key == 'document':
        return f'terminado en {value[-3:]}' if len(value) > 3 else value
    if key == 'email':
        name, _, host = value.partition('@')
        return f'{name[:2]}…@{host}'
    if key == 'phone':
        return f'terminado en {value[-4:]}'
    if key == 'address':
        return f'{value[:12]}…' if len(value) > 14 else value
    return value


def consent_text(keys, details, site):
    # first/last name are shown as the whole name.
    keys = set(keys) | ({'full_name'} if {'first_name', 'last_name'} & set(keys) else set())
    shown = [f'{_SHOWN[key]} ({_masked(key, details[key])})' for key in _ORDER if key in keys and key in details]
    return f'Tus datos para {site}: {", ".join(shown)}'


def fill_guest(st, reader, seen, args):
    """The site's form for the guest: the model names which field is which; code types the person's own
    details, only those they approved for this site on a card (once per task, for the keys it listed)."""
    task = st.task
    if count(task, 'guest_fills') >= MAX_GUEST_FILLS:
        return st.stop('cannot_do')
    from django.contrib.auth import get_user_model
    user = get_user_model().objects.filter(pk=task.user_id).first()
    details = guest_details(user) if user is not None else {}
    planned, refused = [], []
    for entry in (args.get('fields') or [])[:10]:
        key, element = str(entry.get('key') or ''), seen.element(entry.get('ref'))
        if key not in GUEST_KEYS or element is None or element.get('disabled') or element.get('search'):
            refused.append(f'{key}: no such field')
            continue
        auto = str(element.get('autocomplete') or '')
        # The field itself, by what it says to the person (a framework's internal name, "passengerCardForm", is
        # not a card), never its neighbours: a passenger form often holds a loyalty sign-in too.
        words = guard.fold(str(element.get('label') or ''))
        if auto.startswith('cc-') or element.get('type') == 'password' or _PAYMENT_FIELD.search(words) \
                or _CARD_HOLDER.search(guard.fold(f"{element.get('name')} {element.get('label')}")):
            return st.remember('fill_guest', f'refused: "{_label(element)}" is a payment or secret field')
        if element.get('tag') not in ('input', 'select', 'textarea') or (element.get('tag') == 'input' and (
                element.get('type') or '') not in ('', 'text', 'email', 'tel', 'date')):
            refused.append(f'{key}: not a text field')
            continue
        if not _field_is(key, element):
            refused.append(f'{key}: "{_label(element)[:40]}" is not that field')
            continue
        if key not in details:
            refused.append(f'{key}: Confío does not have it; give_up if the site requires it')
            continue
        planned.append((key, element))
    if not planned:
        return st.remember('fill_guest', f"refused: {'; '.join(refused) or 'name the fields'}"[:160])
    keys = sorted({key for key, _ in planned})
    order = dict(task.order or {})
    approved = order.get('guest_approved') or {}
    said_yes = order.get('request_approved') or {}
    if said_yes.get('kind') == 'guest' and said_yes.get('site') == task.site:
        # The person approved the card that listed these details for this site.
        approved = {'site': task.site, 'keys': sorted(set(said_yes.get('keys') or ()) | set(approved.get('keys') or ()))}
        order.update(guest_approved=approved, request_approved=None)
        st.save(order=order)
    if not (approved.get('site') == task.site and set(keys) <= set(approved.get('keys') or ())):
        # Asked for everything the form needs so far: the card names each detail and this site.
        wanted = sorted(set(keys) | set(approved.get('keys') or ()))
        what = consent_text(wanted, details, task.site)
        request = {'label': 'guest', 'what': what, 'button': '', 'kind': 'guest', 'keys': wanted, 'site': task.site}
        return st.hand_over('act', order={**order, 'request': request, 'request_approved': None},
                            body=notes.say(notes.NEEDS_PERSON['guest'], task).replace('{what}', what))
    counts = counted(task, 'guest_fills')
    # Written down before anything is typed: a step that fails halfway never shows the form to a model.
    order = dict(st.task.order or {})
    order['guest_typed'] = sorted(set(order.get('guest_typed') or ()) | {key for key, _ in planned})
    st.save(order=order)
    typed = []
    for key, element in planned:
        value = details[key]
        if key == 'birth_date' and element.get('type') == 'date':
            day, month, year = value.split('/')
            value = f'{year}-{month}-{day}'   # what a date input takes
        done = reader.choose(element, value) if element.get('tag') == 'select' else reader.type(element, value)
        if done:
            refused.append(f'{key}: {done}')
        else:
            typed.append(key)
    result = f"filled: {', '.join(typed) or 'nothing'}" + (f"; refused: {'; '.join(refused)}" if refused else '')
    # From now on no model sees this page's echo of them, nor a picture of the form (step, _hide). Only the keys
    # are kept on the task; the values are read again from her account when needed.
    order = dict(st.task.order or {})
    if order.get('request_approved') or order.get('approved'):
        order.update(request_approved=None, approved=None)   # the form changed after an approval of the booking
    return st.remember('fill_guest', result[:160], counts=counts, order=order)


# ------------------------------------------------------------------ a booking paid now, by the country's rail

def pay(st, reader, browser, seen, element, label, where, args):
    """A booking that must be paid now, paid the way Confío pays this country's stores: read like an order by a
    second model (paid with the rail and nothing else, its total on the page, this booking), approved on the
    order card, pressed once; its payment is then read off the site and paid as any order's (runner.after_checkout)."""
    from . import service
    from .operate import _reviewed, amount_of, breakdown
    task = st.task
    rail = payable_rail(task)
    if rail is None:
        return st.remember('ready_to_pay', 'refused: Confío cannot pay bookings on this site; call cannot_pay with '
                                           'the options and their prices')
    try:
        service.require_payable(task.account, task.user, task.country, st.app_meta())
    except service.TaskRefused as exc:
        return st.stop('no_rail' if exc.code == 'country' else 'cannot_pay')
    order = dict(task.order or {})
    if (order.get('submitted') or 0) >= MAX_BOOKINGS or task.checkout_at:
        return st.remember('ready_to_pay', 'refused: the booking was already sent; find its payment page')
    approved = order.get('approved') or {}
    what = guard.clean(agent.redact(str(args.get('what') or '')), 160)
    # The booking the person approved stands (a model never words it twice the same); the reader checks it.
    item = approved.get('item') if approved.get('button') == label and approved.get('page') == where else what
    if not item:
        return st.remember('ready_to_pay', 'refused: say what it books')
    total = guard.clean(agent.redact(args.get('total')), 40)
    amount = amount_of(total)
    read, why = _reviewed(st, seen, element, item, amount)
    if read is None:
        return st.remember('ready_to_pay', f'refused: {why}')
    mode, offer = service.pay_mode(task, st.app_meta())
    if rail.pay_before_order and mode == 'manual':
        # Venezuela pays before the booking exists, by the Cuenta inteligente only: never her own bank.
        return st.remember('ready_to_pay', 'refused: Confío cannot pay this booking now; call cannot_pay with the '
                                           'options and their prices')
    new = {'item': item, 'total': total, 'amount': format(amount, 'f'), 'button': label, 'page': where,
           'address': '', 'image': '', 'breakdown': breakdown(read, seen.text, amount), 'manual': mode == 'manual',
           'offer': offer, 'booking': True, 'seen_clabes': order.get('seen_clabes') or []}
    if not service.subscribed(task.user):
        # Paying for the person is Cuenta inteligente's (spec decision 37), as for a purchase.
        return st.hand_over('subscribe', order={**order, **new, 'approved': None}, body=notes.say(
            notes.NEEDS_PERSON['subscribe_booking'], task) + notes.breakdown_text(new))
    if not approved or amount_of(approved.get('total')) != amount or {
            key: approved.get(key) for key in ('item', 'manual', 'address', 'button', 'page')} != {
            'item': item, 'manual': mode == 'manual', 'address': '', 'button': label, 'page': where}:
        return st.hand_over('approve', order={**order, **new, 'approved': None}, body=notes.say(
            notes.NEEDS_PERSON['approve_booking_manual' if mode == 'manual' else 'approve_booking'], task)
            + notes.breakdown_text(new))
    if rail.pay_before_order:
        # Venezuela: nothing is pressed now. The site's Pago Móvil data on this page is read and paid; the
        # reference typed into its form then makes the booking (pagomovil.py), as for a purchase.
        from . import pagomovil
        return pagomovil.pay_first(st, browser, seen, {**order, **new, 'booked_button': label[:60]}, approved, amount,
                                   again='ready_to_pay')
    # Used once, and written down first: an answer lost on the way is never a second booking.
    st.save(order={**order, **new, 'approved': None, 'pressed': True, 'pressed_at': [st.same_page(seen.url)],
                   'submitted': (order.get('submitted') or 0) + 1, 'booked_button': label[:60]},
            phase='ordered', checkout_at=timezone.now(),
            history=[*(task.history or []), {'did': 'pressed the booking\'s pay button', 'result': total}
                     ][-st.HISTORY_KEPT:], steps=task.steps + 1, failures=0)
    refused = reader.click(element)
    if refused:
        return st.save(order={**order, **new, 'approved': approved}, phase='', checkout_at=None,
                       history=[*(task.history or []), {'did': 'the pay button', 'result': f'not pressed: {refused}'}
                                ][-st.HISTORY_KEPT:])
    browser.pump(4)
    return None


# ------------------------------------------------------------------ the button that books

_CARD_TEXT = re.compile(
    r'numero de (la )?tarjeta|card number|numero do cartao|\bcvv\b|\bcvc\b|fecha de vencimiento|expiry date'
    r'|validade do cartao|datos de (la |tu )?tarjeta|card details|dados do cartao|terminada en \d{4}'
    r'|ending in \d{4}|[•*]{3,}\s?\d{4}|(garantia|garantizar|garantizamos|guarantee)\w*'
    r'[^.]{0,60}(tarjeta|card|cartao)|(tarjeta|card|cartao)[^.]{0,60}(garantia|guarantee)'
    r'|tarjeta de (credito|debito) (para|como)|\b(visa|mastercard|amex|american express)\b[^.]{0,30}\d{4}')
# A booking this page pays now (a local rail's words): never pressed as one that needs no payment.
_PAID_NOW = re.compile(r'\bpix\b|\bspei\b|\bclabe\b|qr de pago|pagar con qr|pago movil')
_CONFIRMED = re.compile(r'reserva (confirmada|realizada|hecha|registrada)|(numero|codigo|n°|nro) de (reserva|confirmacion)'
                        r'|booking (confirmed|number|reference)|confirmation (number|code)|reserva confirmada'
                        r'|tu reserva esta confirmada|your booking is confirmed|reserva efetuada|reserva confirmada')
# "Sin tarjeta", "no credit card needed": the page saying it needs none is never a card by its words.
_NO_CARD = re.compile(r'(sin|no (se )?(necesita|requiere|pide|hace falta)|without|no|nao precisa de?|sem)\s+(\w+\s+){0,3}'
                      r'(tarjeta|credit card|card|cartao)')
_PAY_FRAME = re.compile(r'stripe|adyen|braintree|checkout\.com|mercadopago|paypal|worldpay|cybersource|payu|ebanx'
                        r'|dlocal|kushki|culqi|openpay|conekta|payment|pagamento|card|tarjeta')


def payment_frames(reader):
    """How many frames on the page are a payment house's (a card form drawn by Stripe, Adyen…): their text is
    not the page's, so only their address tells. None when it could not be read."""
    try:
        sources = reader._run("Array.from(document.querySelectorAll('iframe')).map(f => f.src || '')")
    except Exception:  # noqa: BLE001 - unknown is never "no card"
        return None
    if not isinstance(sources, list):
        return None
    return sum(bool(_PAY_FRAME.search(str(src).lower())) for src in sources)


def card_on_page(seen, reader=None):
    """A card anywhere on this page: a card field, a saved card, a guarantee, a payment house's frame."""
    for element in seen.elements:
        auto = str(element.get('autocomplete') or '')
        words = guard.fold(f"{element.get('name')} {element.get('label')}")
        if auto.startswith('cc-') or (element.get('tag') in ('input', 'iframe', 'select') and _PAYMENT_FIELD.search(words)):
            return True
    text = guard.fold(seen.text[:100000])
    if _CARD_TEXT.search(_NO_CARD.sub(' ', text)):
        return True
    if reader is not None:
        frames = payment_frames(reader)
        if frames is None or frames > 0:
            return True
    return False


def book(st, reader, browser, seen, element, label, where, args):
    """The button that makes the booking: no card on the page, read as booking by the judge, approved by
    the person in the chat as the card showed it, pressed once."""
    task = st.task
    if any(element.get('checked') and _PAID_NOW.search(guard.fold(str(element.get('label') or '')))
           for element in seen.elements):
        # The way to pay it now is chosen on this page (Pix, SPEI, a QR): it is paid, never booked as free.
        return st.remember('ready_to_book', 'refused: this page pays it now; use ready_to_pay, or cannot_pay')
    if card_on_page(seen, reader):
        return st.stop('needs_card', order={**(task.order or {}), 'why': 'la reserva pide una tarjeta'})
    try:
        verdict, why = agent.judge(task, seen, element, st.meter)
    except agent.AgentUnavailable:
        verdict, why = 'unsure', 'the check could not run'
    if verdict == 'card':
        return st.stop('needs_card', order={**(task.order or {}), 'why': 'la reserva pide una tarjeta'})
    if verdict != 'places_order':
        return st.remember('ready_to_book', f'refused: the second reader does not see it as the button that '
                                            f'makes the booking ({verdict}: {why})')
    what = guard.clean(agent.redact(str(args.get('what') or '')), 160) or 'la reserva'
    order = dict(task.order or {})
    sent = order.get('submitted') or 0
    if sent >= MAX_BOOKINGS or (sent and (guard.order_placed(seen) or _CONFIRMED.search(guard.fold(seen.text[:100000])))):
        # Booked already (or this page shows a booking made): never a second one, whatever its button says.
        return st.remember('ready_to_book', 'refused: the booking was already sent; read its result and answer')
    same = [other for other in seen.elements if _label(other) == label]
    request = {**_identity(element, label, where), 'what': what, 'button': label[:80], 'kind': 'book',
               'nth': next((index for index, other in enumerate(same) if other is element), 0),
               'href_full': str(element.get('href') or '')[:300]}
    approved = order.get('request_approved') or {}
    if approved and {**approved, 'what': ''} == {**request, 'what': ''}:
        # The same button on the same page: the model never words it twice the same, so the card's words stand,
        # and they are checked against this page again just below.
        request['what'] = what = approved.get('what')
    page = re.sub(r'\s+', ' ', guard.fold(seen.text[:100000]))
    missing = [n for n in re.findall(r'\d[\d.,/:-]*\d|\d', guard.fold(what)) if n not in page]
    if missing:
        # The card says only what this page shows: a price or a date it no longer shows is never approved.
        st.save(order={**order, 'request_approved': None})
        return st.remember('ready_to_book', f'refused: {missing[0]} is not on this page; name what it shows')
    if approved != request:
        # A second press says so: she knows one was already sent.
        body = (notes.say(notes.NEEDS_PERSON['book_again'], task).replace('{button}', str(order.get('booked_button') or ''))
                if sent else notes.say(notes.NEEDS_PERSON['book'], task)).replace('{what}', what)
        return st.hand_over('act', order={**order, 'request': request, 'request_approved': None}, body=body)
    if element.get('tag') == 'a':
        # A link only opens the site's next step: it never uses up the booking.
        st.save(order={**order, 'request_approved': None},
                history=[*(task.history or []), {'did': f'opened "{label}" (approved)',
                                                 'result': 'only the next step opened, nothing was booked: name '
                                                           'its button with ready_to_book'}][-st.HISTORY_KEPT:],
                steps=task.steps + 1, failures=0)
        refused = reader.click(element)
        if refused:
            return st.save(order={**(st.task.order or {}), 'request_approved': approved})
        browser.pump(3)
        return None
    st.save(order={**order, 'request_approved': None, 'submitted': (order.get('submitted') or 0) + 1,
                   'submitted_at': timezone.now().isoformat(), 'booked_button': label[:60]},
            history=[*(task.history or []), {'did': f'booked "{label}"', 'result': what}][-st.HISTORY_KEPT:],
            steps=task.steps + 1, failures=0)
    refused = reader.click(element)
    if refused:
        return st.save(order={**(st.task.order or {}), 'request_approved': approved,
                              'submitted': (order.get('submitted') or 0)},
                       history=[*(task.history or []), {'did': 'the booking', 'result': f'not sent: {refused}'}
                                ][-st.HISTORY_KEPT:])
    browser.pump(3)
    return None
