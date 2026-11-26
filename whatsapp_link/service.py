"""The person's WhatsApp link: pairing, what arrives, unlinking, sending.

The person's own WhatsApp is linked as one more device in whatsapp-bridge (whatsapp_bridge/, Go, whatsmeow),
on our own host: one device per person, never shared. Only the number the person types can be linked, and a
pairing code for someone else's number is how WhatsApp accounts get stolen, so: one Confío account per number,
a few prompts a day per number, the signed-in number must be the typed one, and a note in the owner's own chat
once it is linked (warn_self), without which nothing is read or sent.

What arrives comes as events (on_events): no polling, nothing marked read, never "online".

Money never moves here. A payment someone asks for in WhatsApp goes through the app's own payment cards, which
the person approves.

Sending: createWhatsAppDraft returns the text and its hash; only the person's tap on that card may call
sendWhatsAppDraft. No assistant tool may send a draft (founder rule: the assistant never acts on its own).
"""
import hashlib
import json
import logging
import re
import time
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone

from celery.exceptions import SoftTimeLimitExceeded
from django.core.cache import cache
from django.db import transaction
from django.db.models import Case, DateTimeField, Q, Value, When
from django.utils import timezone
from django.utils.crypto import salted_hmac

from users.encryption import decrypt_data, encrypt_data

from . import bridge, classify, conf
from .models import WhatsAppDraft, WhatsAppInbox, WhatsAppLink, WhatsAppLinkRecord, WhatsAppNotice

logger = logging.getLogger(__name__)

PROVIDER = 'whatsmeow'
SENDING_STUCK = timedelta(minutes=12)  # past the send task's limits
DRAFT_HOURS = 24
MAX_BODY = 2000
MAX_NAME = 120
# 2: the person types the number; Confío writes one note to their own chat when it is linked.
# 3: linked from our own servers (whatsmeow), new messages arrive as they come, never "online".
# 4: each chat's last 48 hours (both sides, hers from her phone too) kept sealed as context.
# 5: each chat's last 30 days kept sealed, and she can ask the assistant about them (founder 2026-11-26: on
# every link, whichever of the two texts it accepted).
# CONSENT_VERSION is the oldest text a link may run under, and what builds are told to show: a build whose text
# is 4 keeps linking and is never told to update. TEXT_VERSION is the text of today's builds.
CONSENT_VERSION = 4
TEXT_VERSION = 5
ACCEPTED_CONSENT = (CONSENT_VERSION, TEXT_VERSION)
NOTICE_TYPE = 'whatsapp_link'
LIMITS = {'link': 10, 'refresh': 30, 'write': 40}
TITLE = 'Confío IA'
GONE = 'Tu WhatsApp se desvinculó de Confío. Si quieres, vuelve a vincularlo en Confío IA.'
# A login code, a password or a bank token: never stored, never shown to a model.
SECURITY = re.compile(
    r'c[oó]digo|\bcode\b|c[oó]d\.|\botp\b|\bpin\b|verifica|contrase|password|senha|\bclave\b|\btoken\b|'
    r'din[aá]mica|acceso|one[- ]time|single[- ]use|no lo compartas|no la compartas|no compartas|never share|'
    r'nunca compartas|autentica|2fa|seguridad|sign ?in|log ?in|iniciar sesi|ingres|confirma', re.I)
DIGITS = re.compile(r'\d{4,8}|[A-Z0-9]{6,8}')

MESSAGES = {
    'unavailable': 'Vincular WhatsApp todavía no está disponible.',
    'not_personal': 'WhatsApp se vincula solo en tu cuenta personal.',
    'number_taken': ('No pude pedir un código para ese número. Si lo vinculaste en otra cuenta de Confío, '
                     'desvincúlalo allí primero.'),
    'number_limit': 'Demasiados intentos con ese número hoy. Inténtalo mañana.',
    'consent': 'Acepta primero lo que Confío hará con tu WhatsApp.',
    'already_linked': 'Tu WhatsApp ya está vinculado.',
    'not_linked': 'Primero vincula tu WhatsApp.',
    'rate_limited': 'Llegaste al límite de hoy. Prueba mañana.',
    'not_found': 'Ese mensaje ya no existe.',
    'changed': 'El mensaje cambió. Revísalo otra vez antes de enviarlo.',
    'busy': 'Ya estoy enviando ese mensaje.',
    'on_its_way': 'Tu mensaje anterior todavía se está enviando. Espera a que termine y revisa el chat en tu teléfono.',
    'unlinking': 'Estoy terminando de desvincular tu WhatsApp. Inténtalo en un minuto.',
    'finishing': 'Estoy terminando de vincular tu WhatsApp. Inténtalo en unos minutos.',
    'body': f'Escribe un mensaje de hasta {MAX_BODY} caracteres.',
    'chat': 'Dime a qué chat de tu WhatsApp o a qué número.',
    'phone': 'Escribe el número con el código de país, por ejemplo +591 71234567.',
}
# Why a pairing or a send did not finish, in the person's words.
REASONS = {
    'phone_invalid': 'WhatsApp no aceptó ese número. Revisa el número y su código de país.',
    'timeout': 'El código venció sin que se vinculara. Pide uno nuevo.',
    'browser': 'No pude conectar con WhatsApp ahora. Inténtalo en unos minutos.',
    'whatsapp': 'WhatsApp no respondió como esperaba. Inténtalo en unos minutos.',
    'chat_not_found': 'No encontré ese chat en tu WhatsApp. Escribe su nombre tal como aparece.',
    'chat_ambiguous': 'Hay más de un chat con ese nombre. Usa el número en su lugar.',
    'number_not_on_whatsapp': 'Ese número no tiene WhatsApp.',
    'unknown': 'No sé si el mensaje salió. Revisa el chat en tu teléfono antes de repetirlo.',
    'gone': GONE,
    'not_own_phone': 'El WhatsApp vinculado no es el número que escribiste. Lo desvinculé.',
    'number_taken': ('No pude vincular ese número. Si lo vinculaste en otra cuenta de Confío, desvincúlalo allí '
                     'primero.'),
    'banned': 'WhatsApp restringió tu cuenta por un tiempo. Lo desvinculé para cuidarla.',
}


class LinkRefused(Exception):
    def __init__(self, code, message=None):
        super().__init__(code)
        self.code = code
        self.message = message or MESSAGES.get(code) or REASONS.get(code) or MESSAGES['unavailable']


# ------------------------------------------------------------------ helpers

def _seal(value) -> str:
    return encrypt_data(json.dumps(value, ensure_ascii=False))


def _unseal(blob, default=None):
    if not blob:
        return default
    try:
        return json.loads(decrypt_data(blob))
    except Exception:  # noqa: BLE001 - unreadable is absent
        logger.warning('WhatsApp link: a sealed field could not be read')
        return default


def _key(*parts) -> str:
    return salted_hmac('whatsapp_link.source', '\x1f'.join(parts)).hexdigest()


def _claim(user, action, per_day):
    key = f'whatsapp-link:{action}:{user.pk}:{timezone.now().date().isoformat()}'
    try:
        cache.add(key, 0, 2 * 86400)
        count = cache.incr(key)
    except Exception:  # noqa: BLE001 - no counter, no call
        count = None
    if not isinstance(count, int) or count > per_day:
        raise LinkRefused('rate_limited')


def phone_digits(value) -> str:
    digits = re.sub(r'\D', '', str(value or ''))
    if not 8 <= len(digits) <= 15 or digits.startswith('0'):
        raise LinkRefused('phone')
    return digits


# A number can't say which country of a shared code it is: the main one (the person's pick in the app decides).
SHARED_CODE_DEFAULT = {'1': 'US', '7': 'RU', '44': 'GB', '47': 'NO', '61': 'AU', '212': 'MA', '262': 'RE',
                       '590': 'GP', '599': 'CW'}


def phone_country(digits, picked='', home='') -> str:
    """The ISO country of an international number: the one the person picked when its calling code fits the
    number, else their account's country when it fits, else the code's main country. '' when no code fits. It
    only chooses the proxy route the person's WhatsApp connects through (whatsapp_bridge/proxy.go).

    The app's chip starts on the code's main country (+1 is the US), so a pick of that is taken as no pick when
    the account says otherwise (a Dominican with a prefilled +1 number)."""
    from users.country_codes import COUNTRY_CODES
    picked, home = str(picked or '').strip().upper(), str(home or '').strip().upper()
    codes = {}
    for _name, code, iso in (row for row in COUNTRY_CODES if len(row) >= 3):
        codes.setdefault(code.replace('+', ''), []).append(iso.upper())
    for length in (4, 3, 2, 1):
        prefix = digits[:length]
        if len(digits) > length and prefix in codes:
            options = codes[prefix]
            main = SHARED_CODE_DEFAULT.get(prefix) if SHARED_CODE_DEFAULT.get(prefix) in options else options[0]
            if picked in options and picked != main:
                return picked
            if home in options:
                return home
            return main
    return ''


def own_phone(user) -> str:
    """The person's Confío number as international digits, or ''."""
    from users.phone_utils import _resolve_calling_code
    local = re.sub(r'\D', '', getattr(user, 'phone_number', '') or '')
    code = _resolve_calling_code(getattr(user, 'phone_country', '') or '')
    if code == '54' and local and not local.startswith('9'):
        local = '9' + local  # WhatsApp writes Argentine mobiles with the 9 our canonical form leaves out
    return f'{code}{local}' if local and code else ''


def phone_key(digits, secret=None) -> str:
    if not digits:
        return ''
    return salted_hmac('whatsapp_link.source', '\x1f'.join(('phone', digits)), secret=secret).hexdigest()


def enabled():
    return bool(conf.get('WHATSAPP_LINK_ENABLED'))


def allowed(user, account, jwt_context):
    if not enabled():
        raise LinkRefused('unavailable')
    if account is None or (jwt_context or {}).get('account_type') != 'personal':
        raise LinkRefused('not_personal')
    from security.utils import check_user_banned
    if not getattr(user, 'is_active', False) or check_user_banned(user)[0]:
        raise LinkRefused('unavailable')


def _mine(link):
    return WhatsAppLink.objects.filter(pk=link.pk, grant=link.grant)


def _notify(user, message, data=None, title=None):
    try:
        from notifications.models import NotificationType
        from notifications.utils import create_notification
        # Fixed words, but for what a look found important (sync, _push): that one says who wrote and what, as
        # WhatsApp's own notification does on the same phone. All of them go with the link (_forget_pushes), and
        # none outlives the messages (sweep).
        create_notification(user=user, notification_type=NotificationType.SYSTEM, title=title or TITLE, message=message,
                            data={'type': NOTICE_TYPE, 'screen': 'WhatsApp', **(data or {})})
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning('WhatsApp notice failed: %s', type(exc).__name__)


def _forget_pushes(user_id=None, before=None, kind=None):
    """The notifications of one person's WhatsApp (unlinked; `kind`: only those), or everyone's older than `before`
    (sweep)."""
    try:
        from notifications.models import Notification
        rows = Notification.objects.filter(data__type=NOTICE_TYPE)
        rows = rows.filter(user_id=user_id) if before is None else rows.filter(created_at__lt=before)
        if kind:
            rows = rows.filter(data__kind=kind)
        with transaction.atomic():
            rows.delete()
    except Exception as exc:  # noqa: BLE001
        logger.warning('WhatsApp notices not erased: %s', type(exc).__name__)


PUSH_CHARS = 140
# Control and direction characters. Not U+200D: it joins an emoji's parts.
_NOT_WORDS = re.compile(r'[\x00-\x1f\x7f\u200b\u200c\u200e\u200f\u2028-\u202e\u2066-\u2069]')
# A lock screen and a code. The plain cases never get this far (private: not stored). Here, a message with a
# security word and any digit shows none of its words; in any other, a number of 4 to 8 digits is covered unless
# it is plainly an amount of money, and so is a short run of letters and digits mixed. This is what the phone's
# own WhatsApp notification shows of the same message, less those: not a filter a sender would bother to dodge
# (the code is theirs to send), so no chase after invisible characters.
_NUMBER = re.compile(r'\d(?:[\d .,\-–—/_]*\d)?')
_AMOUNT = re.compile(r'\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?')
_MIXED = re.compile(r'(?<![^\W_])(?=[^\W_]*\d)(?=[^\W_]*[^\W\d_])[^\W_]{6,12}(?![^\W_])')
# Only marks that are not also words ("ves", "sol", "real", "pen" are).
_MONEY_BEFORE = re.compile(r'(?:[$€]|\b(?:bs|s/|usd|usdt|mxn|brl|clp)\.?)\s?$', re.I)
_MONEY_AFTER = re.compile(r'\s?(?:[$€]|(?:bs|bolivianos?|pesos?|soles|reales|bol[ií]vares|d[oó]lares|usd|usdt|mxn|brl|clp)\b)',
                          re.I)
PUSH_QUIET = 'Te escribió algo importante. Te lo cuento en Confío IA.'
NO_NAME = 'Alguien'
_FILLERS = 'ᅟᅠㅤﾠ'  # letters by category, blank to the eye


def _shown(text, limit):
    text = ' '.join(_NOT_WORDS.sub(' ', str(text or '')).split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def _no_codes(text):
    """The text with whatever may be a code covered. An amount with its currency stays."""
    def cover(match):
        number = match.group(0)
        digits = sum(c.isdigit() for c in number)
        if _AMOUNT.fullmatch(number) and (_MONEY_BEFORE.search(text[:match.start()])
                                          or _MONEY_AFTER.match(text[match.end():])):
            return number
        return '••••' if 4 <= digits <= 8 else number
    return _MIXED.sub('••••', _NUMBER.sub(cover, text))


def _reads_as_code(*texts):
    """A security word and any digit: no word of it is shown. More than the intake drops (private), which wants
    the digits to look like a code: "mi clave es Perro.12", "Steam code: X7K9P"."""
    text = unicodedata.normalize('NFKC', ' '.join(str(t or '') for t in texts))
    return bool(SECURITY.search(text)) and any(c.isdigit() for c in text)


def _push_name(value):
    """The chat's name for a push's title. It is the sender's to choose: one whose letters read as Confío or
    WhatsApp, whatever sits between them, is nobody's name; a code is covered."""
    name = ''.join(c for c in unicodedata.normalize('NFKC', str(value or ''))
                   if unicodedata.category(c) != 'Cf' and c not in _FILLERS)
    name = _shown(name.replace('«', '').replace('»', ''), 40)
    letters = ''.join(c for c in _fold(name) if c.isascii() and c.isalpha())
    if 'confio' in letters or 'whatsapp' in letters:
        return NO_NAME
    name = _no_codes(name)
    return name if re.search(r'\w', name.replace('•', '')) else NO_NAME


def _push(found):
    """What the phone shows for what a look found important: (title, words). One chat: its name and what it wrote
    (founder 2026-11-26: a push that says who and what is the one a person opens; "Tienes 1 mensaje importante"
    was not). Several chats: their names and how many."""
    chats = {}
    for notice, _replies in found:
        data = _unseal(notice.sealed, {})
        data = data if isinstance(data, dict) else {}
        chats[data.get('jid') or data.get('chat') or ''] = data  # the last of each chat
    told = list(chats.values())
    if not told:
        return TITLE, PUSH_QUIET
    names = list(dict.fromkeys(_push_name(data.get('chat')) for data in told))
    if len(told) == 1:
        last = told[0]
        if private({'name': last.get('chat') or '', 'preview': last.get('preview') or ''}) or _reads_as_code(
                last.get('chat'), last.get('preview')):
            return f'{names[0]} · WhatsApp', PUSH_QUIET
        words = _shown(_no_codes(_shown(last.get('preview'), 600)), PUSH_CHARS)
        return f'{names[0]} · WhatsApp', words if re.search(r'\w', words.replace('•', '')) else PUSH_QUIET
    if len(names) == 1:
        who = f'{names[0]} y {len(told) - 1} más'
    else:
        who = f'{names[0]} y {names[1]}' if len(told) == 2 else f'{names[0]}, {names[1]} y {len(told) - 2} más'
    count = len(found)
    return TITLE, (f'{who}: {count if count < 10 else "más de 9"} mensajes importantes en WhatsApp. Te lo cuento en '
                   'Confío IA.')


# ------------------------------------------------------------------ the screen

def status(user) -> dict:
    link = WhatsAppLink.objects.filter(user=user).first()
    result = {'state': 'none', 'code': None, 'code_at': None, 'phone_hint': None, 'reason': None,
              'reason_message': None, 'linked_at': None, 'last_sync_at': None, 'own_phone_hint': None,
              'consent_version': CONSENT_VERSION, 'consent_outdated': False, 'suggested_phone': None, 'notices': []}
    phone = own_phone(user)
    result['own_phone_hint'] = phone[-4:] if phone else None
    # A prefill for the field, never a proof: the WhatsApp they linked last (to link it again), else the account's.
    last = WhatsAppLinkRecord.objects.filter(user=user).order_by('-linked_at').values_list('phone', flat=True).first()
    result['suggested_phone'] = last or (f'+{phone}' if phone else None)
    if link is None or link.reason == 'unlinking':
        return result
    result.update(state=link.state, phone_hint=link.phone_hint or None, linked_at=link.linked_at,
                  last_sync_at=link.last_sync_at, reason=link.reason or None,
                  reason_message=REASONS.get(link.reason) if link.reason else None)
    if link.state == WhatsAppLink.State.PAIRING and link.code_at:
        result.update(code=_unseal(link.sealed_code), code_at=link.code_at)
    if link.state != WhatsAppLink.State.LINKED:
        return result
    result['consent_outdated'] = link.consent_version < CONSENT_VERSION
    notices = link.notices.all()
    if conf.get('WHATSAPP_LINK_KEEP_DAYS'):
        notices = notices.filter(created_at__gte=timezone.now() - timedelta(days=conf.get('WHATSAPP_LINK_KEEP_DAYS')))
    for notice in notices.order_by('-created_at')[:30]:
        data = _unseal(notice.sealed, {})
        result['notices'].append({'id': str(notice.pk), 'kind': notice.kind, 'chat': data.get('chat') or '',
                                  'preview': data.get('preview') or '', 'summary': data.get('summary') or '',
                                  'time': data.get('time') or '', 'created_at': notice.created_at})
    return result


NUMBER_PER_DAY = 3  # linking prompts one WhatsApp number can receive a day, from all of Confío


def _keys(digits) -> list:
    """The number's key under the current secret and the rotated ones: a key rotation never frees a number."""
    from django.conf import settings
    return [phone_key(digits, secret) for secret in (None, *getattr(settings, 'SECRET_KEY_FALLBACKS', []))]


def _number_taken(user, digits, *, linked_only=False, exclude_pk=None) -> bool:
    states = (WhatsAppLink.State.LINKED,) if linked_only else (WhatsAppLink.State.PAIRING, WhatsAppLink.State.LINKED)
    rows = WhatsAppLink.objects.filter(phone_key__in=_keys(digits), state__in=states).exclude(reason='unlinking')
    rows = rows.exclude(pk=exclude_pk) if exclude_pk else rows.exclude(user=user)
    return rows.exists()


def _number_lock(digits):
    """One pairing decision per number at a time (inside a transaction): two accounts never both get it."""
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [int(phone_key(digits)[:15], 16)])


def _claim_number(key):
    counter = f'whatsapp-link:number:{key}:{timezone.now().date().isoformat()}'
    try:
        cache.add(counter, 0, 2 * 86400)
        count = cache.incr(counter)
    except Exception:  # noqa: BLE001 - no counter, no prompt
        count = None
    if not isinstance(count, int) or count > NUMBER_PER_DAY:
        raise LinkRefused('number_limit')


def start_link(user, phone, consent_version, country=''):
    """Asks WhatsApp for a pairing code for the number the person typed (with its country code), and waits
    for it (a few seconds): the screen shows the code as soon as this returns.

    The number is theirs to type (sign-up no longer proves a phone). What keeps a stranger's WhatsApp out:
    WhatsApp asks its owner to type the code in their own phone; one Confío account per WhatsApp number;
    a few prompts a day per number, from all of Confío; and, once linked, a note in the owner's own chat
    that says so (warn_self), which a person tricked into typing a code sees in their own WhatsApp."""
    if consent_version not in ACCEPTED_CONSENT:
        raise LinkRefused('consent')
    if not str(phone or '').strip().startswith('+'):
        raise LinkRefused('phone')
    digits = phone_digits(phone)
    key = phone_key(digits)
    # Counted before any answer about the number: no one can try number after number for free.
    _claim(user, 'link', LIMITS['link'])
    _claim_number(key)
    with transaction.atomic():
        _number_lock(digits)
        if _number_taken(user, digits):
            raise LinkRefused('number_taken')
        link = WhatsAppLink.objects.select_for_update().filter(user=user).first()
        if link is not None and link.reason == 'unlinking':
            raise LinkRefused('unlinking')
        if link is not None and link.state == WhatsAppLink.State.LINKED:
            raise LinkRefused('already_linked')
        fields = dict(state=WhatsAppLink.State.PAIRING, reason='', sealed_phone=_seal(digits), phone_hint=digits[-4:],
                      phone_key=phone_key(digits), provider=PROVIDER,
                      sealed_code='', code_at=None, linked_at=None, history_at=None, next_sync_at=None, failures=0,
                      consent_version=consent_version, grant=uuid.uuid4(), session_expires_at=None)
        if link is None:
            link = WhatsAppLink.objects.create(user=user, **fields)
        else:
            # A new pairing may be another WhatsApp: nothing of the last one carries over.
            link.notices.all().delete()
            link.drafts.all().delete()
            link.inbox.all().delete()
            for name, value in fields.items():
                setattr(link, name, value)
            link.save()
    _ask_code(link, phone_country(digits, country, getattr(user, 'phone_country', '')))
    return link


def _ask_code(link, country):
    grant = str(link.grant)
    try:
        code = bridge.pair(link.pk, grant, _unseal(link.sealed_phone, ''), conf.get('WHATSAPP_LINK_PAIRING_SECONDS'),
                           country=country)
    except bridge.BridgeRefused as exc:
        logger.warning('WhatsApp pairing %s refused: %s', link.pk, exc.code)
        _fail(link, exc.code if exc.code in REASONS else 'whatsapp')
        return
    except (bridge.BridgeUnavailable, TimeoutError, OSError, ValueError, KeyError) as exc:
        logger.warning('WhatsApp pairing %s: bridge %s', link.pk, type(exc).__name__)
        _fail(link, 'browser')
        return
    _mine(link).filter(state=WhatsAppLink.State.PAIRING).update(sealed_code=_seal(code), code_at=timezone.now(),
                                                                session_expires_at=_pairing_ends())


def _pairing_ends():
    return timezone.now() + timedelta(seconds=conf.get('WHATSAPP_LINK_PAIRING_SECONDS'))


def accept_consent(user, consent_version):
    """A linked person accepts today's text: what arrives is kept again."""
    if consent_version not in ACCEPTED_CONSENT:
        raise LinkRefused('consent')
    # Never back to an older text: the row says the newest one the person accepted.
    WhatsAppLink.objects.filter(user=user, state=WhatsAppLink.State.LINKED, consent_version__lt=consent_version).exclude(
        reason='unlinking').update(consent_version=consent_version)


def unlink(user, ended_by=WhatsAppLinkRecord.EndedBy.CONFIO, grant=None, only_pending=False):
    """Erases what came from WhatsApp now; then the bridge logs the device out and deletes its keys."""
    with transaction.atomic():
        link = WhatsAppLink.objects.select_for_update().filter(user=user).first()
        if link is None or link.reason == 'unlinking' or (grant is not None and str(link.grant) != str(grant)):
            return False
        if only_pending and not note_pending(link):
            return False  # the note was written meanwhile: nothing to undo
        link.notices.all().delete()
        link.drafts.all().delete()
        link.inbox.all().delete()
        WhatsAppLink.objects.filter(pk=link.pk).update(
            reason='unlinking', grant=uuid.uuid4(), sealed_code='', code_at=None, sealed_phone='', next_sync_at=None,
            history_at=None, updated_at=timezone.now())
    _forget_pushes(user.pk)
    from . import chat
    chat.erase(user)  # what the assistant said about it in the conversation goes too
    _end_record(user.pk, ended_by)
    from . import tasks
    transaction.on_commit(lambda: tasks.forget.delay(link.pk))
    return True


def refresh(user):
    """Opening Confío IA: what arrived and waits to be looked at is looked at now (messages come by themselves)."""
    link = WhatsAppLink.objects.filter(user=user, state=WhatsAppLink.State.LINKED).exclude(reason='unlinking').first()
    if link is None or link.consent_version < CONSENT_VERSION or note_pending(link) \
            or not link.inbox.filter(from_me=False, looked_at__isnull=True).exists():
        return False
    _claim(user, 'refresh', LIMITS['refresh'])
    _queue_sync(link.pk, countdown=0)
    return True


def dismiss(user, notice_id):
    if str(notice_id).isdigit():
        WhatsAppNotice.objects.filter(pk=notice_id, link__user=user).delete()


# ------------------------------------------------------------------ events from the bridge

EVENT_TRIES = 3  # deliveries of one event that failed here before it is given up (logged as an error): the
# bridge delivers in order, so one bad event must not hold everyone's (a pairing code) for long


def on_events(events) -> bool:
    """What WhatsApp said, in order, as the bridge delivers it (views.bridge_events). Delivered again after a
    lost answer or a failure here: each one is safe to see twice. False while one failed and must come again."""
    ok = True
    for event in events:
        started = time.monotonic()
        kind = str(event.get('kind') or '')
        try:
            _on_event(event)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - the bridge delivers it again
            key = f"whatsapp-link:event-fails:{event.get('id')}"
            try:
                cache.add(key, 0, 86400)
                tries = cache.incr(key)
            except Exception:  # noqa: BLE001 - no counter: given up rather than holding the queue forever
                tries = EVENT_TRIES
            if tries >= EVENT_TRIES:
                logger.error('WhatsApp event %s for link %s given up after %d tries: %s', kind, event.get('link'),
                             tries, type(exc).__name__)
            else:
                logger.warning('WhatsApp event %s for link %s failed (%s), delivered again', kind, event.get('link'),
                               type(exc).__name__)
                ok = False
        logger.info('WhatsApp event %s link=%s ms=%d', kind, event.get('link'), (time.monotonic() - started) * 1000)
    return ok


def _on_event(event):
    kind, data = event.get('kind'), event.get('data') or {}
    link = WhatsAppLink.objects.select_related('user').filter(
        pk=int(event.get('link') or 0), grant=str(event.get('grant') or '')).exclude(reason='unlinking').first() \
        if str(event.get('link') or '').isdigit() else None
    if link is None:
        if kind in ('paired', 'message', 'history'):
            # A device for a pairing that is over (unlinked or asked again meanwhile): it must not stay linked.
            _queue_logout(event.get('link'), event.get('grant'))
        return
    if kind in ('paired', 'message', 'history') and link.state not in (WhatsAppLink.State.PAIRING, WhatsAppLink.State.LINKED):
        _queue_logout(link.pk, link.grant)  # this pairing ended here (failed, gone): its device goes too
        return
    if kind == 'code':
        _mine(link).filter(state=WhatsAppLink.State.PAIRING).update(sealed_code=_seal(str(data.get('code') or '')),
                                                                    code_at=timezone.now())
    elif kind == 'paired':
        if link.state == WhatsAppLink.State.PAIRING:
            _linked(link, re.sub(r'\D', '', str(data.get('phone') or '')))
    elif kind == 'pair_timeout':
        _fail(link, 'timeout', logout=False)
    elif kind == 'pair_error':
        _fail(link, 'whatsapp')
    elif kind == 'logged_out':
        if link.state == WhatsAppLink.State.LINKED:
            _gone(link)
        else:
            _fail(link, 'whatsapp', logout=False)
    elif kind == 'banned':
        logger.error('WhatsApp link %s: WhatsApp restricted the account for a while', link.pk)
        if link.state == WhatsAppLink.State.LINKED:
            _gone(link, reason='banned', ended_by=WhatsAppLinkRecord.EndedBy.PHONE)
            _queue_logout(link.pk, link.grant)
    elif kind == 'outdated':
        logger.error('WhatsApp bridge: WhatsApp says the client is outdated; update whatsmeow and redeploy')
    elif kind == 'message':
        _arrived(link, data)
    elif kind == 'history':
        _past(link, data)


def _queue_logout(link_id, grant):
    """That pairing's device only: a late logout never touches a newer pairing of the same row. Once an hour per
    pairing (a stale device still getting messages would queue one per message)."""
    if str(link_id or '').isdigit() and grant and cache.add(f'whatsapp-link:logout:{link_id}:{grant}', 1, 3600):
        from . import tasks
        transaction.on_commit(lambda: tasks.logout.delay(int(link_id), str(grant)))


def _linked(link, signed):
    """WhatsApp says the device is linked to `signed`. Only the number the person typed may be: a spelling of it
    (the same last 8 digits) is recorded as WhatsApp writes it; any other number is unlinked at once."""
    typed = _unseal(link.sealed_phone, '')
    if not signed or not typed or signed[-8:] != typed[-8:]:
        _fail(link, 'not_own_phone')
        return
    digits = signed
    now = timezone.now()
    with transaction.atomic():
        _number_lock(digits)
        taken = _number_taken(link.user, digits, linked_only=True, exclude_pk=link.pk)
        linked = 0
        if not taken:
            # The number stays sealed until the note to the person's own chat is written (warn_self), then goes.
            linked = _mine(link).filter(state=WhatsAppLink.State.PAIRING).update(
                state=WhatsAppLink.State.LINKED, reason='', sealed_code='', code_at=None, linked_at=now, failures=0,
                sealed_phone=_seal(digits), phone_key=phone_key(digits), phone_hint=digits[-4:],
                session_expires_at=None)
            if linked:
                # With the link itself, so no crash in between loses them and an unlink always finds the record.
                _end_record(link.user_id, WhatsAppLinkRecord.EndedBy.CONFIO, now)  # left open by a lost unlink
                WhatsAppLinkRecord.objects.create(
                    user_id=link.user_id, phone=f'+{digits}', phone_key=phone_key(digits),
                    phone_hint=digits[-4:], consent_version=link.consent_version, linked_at=now)
                from . import tasks
                grant = str(link.grant)
                transaction.on_commit(lambda: tasks.warn_self.apply_async((link.pk, grant), countdown=3))
    if taken:
        _fail(link, 'number_taken')  # another account linked it first: this one never holds it
        return
    if linked:
        _notify(link.user, 'Tu WhatsApp quedó vinculado. Te aviso cuando llegue algo importante.')


def _arrived(link, data):
    """A new message of a one-to-one chat: from someone (waits for the next look, 30 seconds later, so a burst
    is one look) or hers, written on her phone (context only: it tells the look she already answered). Kept
    sealed for the chat's context; never when it looks like a code or a password."""
    if link.state != WhatsAppLink.State.LINKED or link.consent_version < CONSENT_VERSION or note_pending(link):
        return  # nothing is read before the note is written, nor under an older consent
    row = {'name': str(data.get('name') or '')[:MAX_NAME], 'preview': str(data.get('text') or '')[:1000]}
    if not row['preview'] or private(row):
        return
    chat_id = str(data.get('chat') or '')
    if not chat_id:
        return
    from_me = data.get('from_me') is True
    key = _key(str(link.user_id), str(link.grant), str(data.get('id') or ''), chat_id)
    _row, made = WhatsAppInbox.objects.get_or_create(link=link, source_key=key, defaults={
        'chat_key': _chat_key(link, chat_id), 'from_me': from_me, 'looked_at': timezone.now() if from_me else None,
        'sealed': _seal({'chat': chat_id, 'name': row['name'], 'phone': str(data.get('phone') or ''),
                         'text': row['preview'], 'at': int(data.get('at') or 0)})})
    if made and not from_me:
        _queue_sync(link.pk)


HISTORY_PER_EVENT = 500


def _past(link, data):
    """The chats' history WhatsApp handed the new device (its last HISTORY_DAYS, one-to-one text, filtered by the
    bridge as new messages are): kept like any kept message, under the message's own time, so she can ask about it
    right after linking and it is erased on the same day as it would have been. Already looked at: old messages are
    never classified, pushed or told; one written after the link (it came with the history) waits for its look
    like a new message. Kept while the owner's note is still being written, as nothing is read before it is
    (assistant_tool._link) and an undone link erases them (unlink)."""
    # The accepted texts cover it (founder 2026-11-26): the same check as a new message.
    if link.state != WhatsAppLink.State.LINKED or link.consent_version < CONSENT_VERSION:
        return
    items = data.get('messages') if isinstance(data, dict) else None
    if not isinstance(items, list):
        return
    now = timezone.now()
    since = _history_since()
    linked = link.linked_at.timestamp() if link.linked_at else now.timestamp()
    rows, times = {}, {}
    for item in items[:HISTORY_PER_EVENT]:
        if not isinstance(item, dict):
            continue
        row = {'name': str(item.get('name') or '')[:MAX_NAME], 'preview': str(item.get('text') or '')[:1000]}
        chat_id = str(item.get('chat') or '')
        try:
            at = int(item.get('at') or 0)
        except (TypeError, ValueError):
            continue
        if not row['preview'] or not chat_id or at <= 0 or private(row):
            continue
        when = datetime.fromtimestamp(min(at, int(now.timestamp())), tz=dt_timezone.utc)
        if when < since:
            continue
        from_me = item.get('from_me') is True
        key = _key(str(link.user_id), str(link.grant), str(item.get('id') or ''), chat_id)
        new = not from_me and at >= linked  # written after the link: a new message, looked at as one
        rows[key] = WhatsAppInbox(
            link=link, source_key=key, chat_key=_chat_key(link, chat_id), from_me=from_me,
            looked_at=None if new else now,
            sealed=_seal({'chat': chat_id, 'name': row['name'], 'phone': str(item.get('phone') or ''),
                          'text': row['preview'], 'at': at}))
        times[key] = when
    if not rows:
        # History came with nothing to keep (or only a marker that a chunk came): it still came.
        _mine(link).filter(state=WhatsAppLink.State.LINKED).exclude(reason='unlinking').update(history_at=now)
        return
    with transaction.atomic():
        if _mine(link).select_for_update().filter(state=WhatsAppLink.State.LINKED).exclude(
                reason='unlinking').first() is None:
            return  # unlinked meanwhile: write nothing
        known = set(WhatsAppInbox.objects.filter(link=link, source_key__in=list(rows)).values_list(
            'source_key', flat=True))
        made = [row for key, row in rows.items() if key not in known]
        # A live copy that lands between the read and the write is the same row: kept once.
        WhatsAppInbox.objects.bulk_create(made, ignore_conflicts=True)
        # created_at is the message's own time: the 30-day erase (sweep) and the days asked about go by it.
        keys = [row.source_key for row in made]
        if keys:
            WhatsAppInbox.objects.filter(link=link, source_key__in=keys, created_at__gte=now).update(created_at=Case(
                *[When(source_key=key, then=Value(times[key])) for key in keys], output_field=DateTimeField()))
        _mine(link).update(history_at=now)
    if any(row.looked_at is None for row in made):
        _queue_sync(link.pk)


def _chat_key(link, chat_id):
    return _key(str(link.user_id), str(link.grant), 'chat', chat_id)


def _context_since():
    return timezone.now() - timedelta(hours=conf.get('WHATSAPP_LINK_CONTEXT_HOURS'))


def _history_since():
    return timezone.now() - timedelta(days=conf.get('WHATSAPP_LINK_HISTORY_DAYS'))


HISTORY_ROWS = 20000  # the newest kept messages one question reads, at most
HISTORY_PAGE = 1000
HISTORY_LINES = 25
HISTORY_CHARS = 300   # of one message; the tool's whole answer must fit what the model is given (engine._run_tool)


def _folded(text):
    """The text without case or accents, and where in the text each of its characters came from."""
    out, where = [], []
    for index, char in enumerate(str(text or '')):
        for piece in unicodedata.normalize('NFKD', char.casefold()):
            if not unicodedata.combining(piece):
                out.append(piece)
                where.append(index)
    return ''.join(out), where


def _fold(text):
    return _folded(text)[0]


def _excerpt(text, folded, where, terms):
    """What is told of a long message: the part around the first word asked about, with … where it was cut."""
    if len(text) <= HISTORY_CHARS:
        return text
    spots = [where[spot] for spot in (folded.find(term) for term in terms) if spot >= 0]
    start = min(max(0, min(spots) - HISTORY_CHARS // 3) if spots else 0, len(text) - HISTORY_CHARS)
    return ('…' if start else '') + text[start:start + HISTORY_CHARS] + ('…' if start + HISTORY_CHARS < len(text) else '')


def history(link, *, chat=None, words=None, days=None) -> tuple:
    """What she asks about her own kept messages (HISTORY_DAYS, both sides): of one chat or of all, holding the
    words she asks about, oldest first: ([{chat, de, texto, at}], whole). `whole` is False when what is told is not
    all there is: more kept messages than one question reads (HISTORY_ROWS), or more that match than one answer
    carries (HISTORY_LINES). Then neither "there is none" nor "these are all" can be said. Unsealed for this
    answer, stored nowhere else."""
    since = _history_since()
    if days:
        since = max(since, timezone.now() - timedelta(days=max(1, int(days))))
    # Every word of the name, in any order: "Genesis esposa" finds the chat saved as "Esposa Génesis".
    who = [part for part in _fold(chat).split() if part]
    terms = [term for term in _fold(words).split() if len(term) > 1][:6]
    kept = WhatsAppInbox.objects.filter(link=link, created_at__gte=since)
    # By chat id: a chat is the one asked for when any of its lines carries that name, and all of its lines come
    # with it, hers too (hers can carry another name: her number, where the contact is not saved).
    names, labels, named, matches = {}, {}, set(), {}
    read, before, whole = 0, None, True

    def asked(loose=False):
        if loose:  # the saved name whole, inside what she asked ("Genesis esposa" ⊇ "Genesis"), never a part of it
            return [cid for cid in matches if any(name.split() and set(name.split()) <= set(who) for name in names[cid])]
        return [cid for cid in matches if not who or any(all(part in name for part in who) for name in names[cid])]

    def older(rows, cursor):
        # Newest first by the message's own time (created_at: history comes in after live messages, with older
        # times), pk among equals.
        return rows.filter(Q(created_at__lt=cursor[0]) | Q(created_at=cursor[0], pk__lt=cursor[1])) if cursor else rows

    while True:
        page = list(older(kept, before).order_by('-created_at', '-pk')[:HISTORY_PAGE])
        for row in page:
            data = _unseal(row.sealed, {})
            text = data.get('text')
            if not text:
                continue
            cid, name = data.get('chat') or '', data.get('name') or ''
            names.setdefault(cid, set()).add(_fold(name))
            if name and cid not in named and (not row.from_me or cid not in labels):
                labels[cid] = name  # the chat is called what the contact is called now: the newest of their lines
                if not row.from_me:
                    named.add(cid)
            folded, where = _folded(text)
            hits = sum(term in folded for term in terms)
            if terms and not hits:
                continue
            of_chat = matches.setdefault(cid, [])
            if terms or len(of_chat) <= HISTORY_LINES:  # the latest of a chat: no more than an answer carries
                of_chat.append((hits, int(data.get('at') or 0) or int(row.created_at.timestamp()), row.pk, row.from_me,
                                text, folded, where))
        read += len(page)
        if len(page) < HISTORY_PAGE:
            break
        before = (page[-1].created_at, page[-1].pk)
        if not terms and sum(len(matches[cid]) for cid in asked()) >= HISTORY_LINES:
            whole = False  # the latest was asked for, and that much is here; older ones were not read
            break
        if read >= HISTORY_ROWS:
            whole = not older(kept, before).exists()
            break
    # "Genesis esposa" for the chat saved as "Genesis": a word she adds (who the person is to her) is not in the
    # name. Only when no chat carries every word, and never "Genesis hermana" for "Esposa Génesis".
    # Loose only when no saved chat name carries every word, whatever its messages hold.
    named_whole = who and any(any(all(part in name for part in who) for name in chat_names)
                              for chat_names in names.values())
    chats = asked(loose=True) if who and not named_whole else asked()
    found = [(item, cid) for cid in chats for item in matches[cid]]
    # The messages holding most of the words; among equals, the newest. Told oldest first.
    best = sorted(found, key=lambda pair: (-pair[0][0], -pair[0][1], -pair[0][2]))
    if len(best) > HISTORY_LINES:
        whole = False
    lines = [{'chat': labels.get(cid) or '', 'de': 'ella' if from_me else 'contacto',
              'texto': _excerpt(text, folded, where, terms), 'at': at}
             for (_hits, at, _pk, from_me, text, folded, where), cid in sorted(
                 best[:HISTORY_LINES], key=lambda pair: (pair[0][1], pair[0][2]))]
    return lines, whole


CONTEXT_LINES = 15


def conversation(link, chat_id, *, new_ids=()):
    """The chat's last hours as the model reads them, oldest first: [{de, texto, nuevo}] ("ella" is the person)."""
    rows = list(WhatsAppInbox.objects.filter(link=link, chat_key=_chat_key(link, chat_id),
                                             created_at__gte=_context_since()).order_by('pk'))
    lines = []
    for row in rows:
        data = _unseal(row.sealed, {})
        if data.get('text'):
            lines.append({'de': 'ella' if row.from_me else 'contacto', 'texto': data['text'][:500],
                          'nuevo': row.pk in new_ids, 'at': int(data.get('at') or 0)})
    lines.sort(key=lambda line: line['at'])
    return [{k: v for k, v in line.items() if k != 'at'} for line in lines[-CONTEXT_LINES:]]


def _retire_unlooked(rows):
    """A message that waited for its look past CONTEXT_HOURS is never looked at (a look reads the last hours, and a
    notice about it would be stale): it stays only to be asked about."""
    rows.filter(looked_at__isnull=True, created_at__lt=_context_since()).update(looked_at=timezone.now())


def transcript(lines):
    # One line per message: a contact's text can never start a line that reads as hers.
    return '\n'.join(f"{'Ella' if line['de'] == 'ella' else 'Contacto'}: {' '.join(line['texto'].split())}"
                     for line in lines)


def _queue_sync(link_id, countdown=None):
    """One look per link at a time: the first message starts the wait, the rest join it."""
    wait = conf.get('WHATSAPP_LINK_BATCH_SECONDS') if countdown is None else countdown
    if cache.add(f'whatsapp-link:queued:{link_id}', 1, max(wait, 1) + 60):
        from . import tasks
        transaction.on_commit(lambda: tasks.sync.apply_async((link_id,), countdown=wait))


# What the owner of the WhatsApp reads in their own chat right after it is linked. Fixed words.
SELF_NOTE = ('Confío: este WhatsApp se vinculó a una cuenta de Confío (aparece como «Chrome» en Dispositivos '
             'vinculados). Si no fuiste tú, desvincúlalo ahora y no compartas códigos con nadie.')
WARN_TRIES = 30  # a minute apart
NOT_WRITTEN = ('No pude terminar de vincular tu WhatsApp, así que lo desvinculé. Vuelve a vincularlo en Confío IA '
               'cuando quieras.')
NOTE_DEADLINE = timedelta(hours=1)  # a note still not written by then undoes the link, whatever happened


def note_pending(link) -> bool:
    """Linked, and the note to the owner's own chat not written yet: nothing is read or sent until it is."""
    return link.state == WhatsAppLink.State.LINKED and bool(link.sealed_phone)


def _note_failed(link_id, grant):
    """Fails closed: the link is undone, never left usable without the note."""
    row = WhatsAppLink.objects.select_related('user').filter(pk=link_id, grant=grant).first()
    if row is not None and note_pending(row) and unlink(row.user, WhatsAppLinkRecord.EndedBy.NOTE, grant=grant,
                                                        only_pending=True):
        logger.error('WhatsApp link %s: the note to its owner could not be confirmed; unlinked', link_id)
        _notify(row.user, NOT_WRITTEN)


def warn_self(link_id, grant, tries=0):
    """The one message Confío writes by itself: a note in the owner's own chat that the link happened. A person
    tricked into typing a code sees it in their own WhatsApp.

    Fails closed: nothing is read or sent until it is written (note_pending), and if it cannot be written the
    link is undone. The bridge sends one id at most once, so trying again never writes it twice."""
    link = WhatsAppLink.objects.filter(pk=link_id, grant=grant).exclude(reason='unlinking').first()
    if link is None or not note_pending(link):
        return
    try:
        result = bridge.send(link.pk, grant, f'note-{grant}', SELF_NOTE, own_chat=True)
    except (bridge.BridgeUnavailable, bridge.BridgeRefused):
        result = {'status': 'not_sent'}
    except (TimeoutError, OSError, ValueError):
        result = {'status': 'unknown'}  # asked, no answer: tried again under the same id, answered from its row
    if result.get('status') == 'sent':
        _mine(link).update(sealed_phone='')  # the number is not kept past this
        return
    if tries < WARN_TRIES:
        from . import tasks
        tasks.warn_self.apply_async((link_id, grant, tries + 1), countdown=60)
        return
    _note_failed(link_id, grant)


def _end_record(user_id, ended_by, now=None):
    WhatsAppLinkRecord.objects.filter(user_id=user_id, ended_at__isnull=True).update(
        ended_at=now or timezone.now(), ended_by=ended_by)


def _fail(link, reason, logout=True):
    """The pairing ended without a link (a link already made is never failed). The device goes with it."""
    if _mine(link).filter(state=WhatsAppLink.State.PAIRING).update(
            state=WhatsAppLink.State.FAILED, reason=reason, sealed_code='', code_at=None, sealed_phone='',
            session_expires_at=None) and logout:
        _queue_logout(link.pk, link.grant)


def _gone(link, reason='gone', ended_by=WhatsAppLinkRecord.EndedBy.PHONE):
    """Unlinked from the phone (or WhatsApp ended the device): what came from it goes."""
    if not _mine(link).filter(state=WhatsAppLink.State.LINKED).update(
            state=WhatsAppLink.State.GONE, reason=reason, next_sync_at=None, sealed_phone='', history_at=None):
        return
    link.notices.all().delete()
    link.inbox.all().delete()
    link.drafts.exclude(status=WhatsAppDraft.Status.SENDING).delete()
    _end_record(link.user_id, ended_by)
    from . import chat
    chat.erase(link.user)
    _forget_pushes(link.user_id)  # what the pushes said of its messages goes too; then the one that says it ended
    _notify(link.user, REASONS.get(reason) or GONE)


# ------------------------------------------------------------------ unlinking

def forget(link_id, tries=0):
    """Logs the device out of WhatsApp (it leaves the person's list) and deletes its keys, then the row."""
    if not WhatsAppLink.objects.filter(pk=link_id, reason='unlinking').exists():
        return
    try:
        bridge.logout(link_id)
    except (bridge.BridgeUnavailable, bridge.BridgeRefused, TimeoutError, OSError, ValueError) as exc:
        logger.warning('WhatsApp link %s: logout not done yet (%s)', link_id, type(exc).__name__)
        if tries < 20:
            from . import tasks
            tasks.forget.apply_async((link_id, tries + 1), countdown=min(30 * (tries + 1), 600))
        else:
            logger.error('WhatsApp link %s: unlinked here, but the bridge never logged it out', link_id)
        return
    WhatsAppLink.objects.filter(pk=link_id, reason='unlinking').delete()


def logout(link_id, grant=''):
    """A device that must not stay (a failed pairing, a stranger's number): off the phone, keys deleted."""
    try:
        bridge.logout(link_id, grant)
    except (bridge.BridgeUnavailable, bridge.BridgeRefused, TimeoutError, OSError, ValueError) as exc:
        logger.warning('WhatsApp link %s: logout failed (%s)', link_id, type(exc).__name__)
        raise


# ------------------------------------------------------------------ looking at what arrived

def private(row) -> bool:
    """A login code, a password or a bank token: never stored, never shown to a model."""
    text = f"{row.get('name', '')} {row.get('preview', '')}"
    if not SECURITY.search(text):
        return False
    return bool(DIGITS.search(re.sub(r'[\s\-.]', '', text)))


def sync(link_id):
    """Looks at what arrived since the last look, each chat in its whole recent conversation, and keeps only the
    important. Messages stay sealed: the last CONTEXT_HOURS are each look's context, HISTORY_DAYS can be asked
    about (history)."""
    cache.delete(f'whatsapp-link:queued:{link_id}')
    if not enabled():
        return
    link = WhatsAppLink.objects.select_related('user').filter(
        pk=link_id, state=WhatsAppLink.State.LINKED).exclude(reason='unlinking').first()
    if link is None or link.consent_version < CONSENT_VERSION or note_pending(link):
        return
    # One look per link at a time; a failed look leaves them unlooked for the next.
    lease = f'whatsapp-link:looking:{link_id}'
    if not cache.add(lease, 1, 120):
        _queue_sync(link_id)
        return
    try:
        _retire_unlooked(WhatsAppInbox.objects.filter(link=link))
        taken = list(WhatsAppInbox.objects.filter(link=link, from_me=False, looked_at__isnull=True,
                                                  created_at__gte=_context_since()).order_by('pk')[:100])
        if not taken:
            return
        started = time.monotonic()
        try:
            found = _store(link, taken)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - by type: a message can quote a chat
            logger.warning('WhatsApp classify %s failed: %s', link.pk, type(exc).__name__)
            return
        # Looked at: kept as the chat's context and to be asked about, until it is HISTORY_DAYS old (sweep).
        WhatsAppInbox.objects.filter(pk__in=[row.pk for row in taken]).update(looked_at=timezone.now())
    finally:
        cache.delete(lease)
    logger.info('WhatsApp classify link=%s messages=%d important=%d ms=%d', link.pk, len(taken), len(found),
                (time.monotonic() - started) * 1000)
    _mine(link).update(last_sync_at=timezone.now())
    if found and _mine(link).filter(state=WhatsAppLink.State.LINKED).exclude(reason='unlinking').exists():
        from . import chat
        # Confío IA says it in the conversation, with replies to pick. One that only grew the open post of its
        # chat (chat._merge) is not pushed again: she was told minutes ago and has not answered yet.
        found = [(notice, replies) for notice, replies in found if not chat.tell(link, notice, replies)]
        if found:
            title, words = _push(found)
            _notify(link.user, words, {'kind': 'messages'}, title=title)  # it opens the conversation
        if not _mine(link).filter(state=WhatsAppLink.State.LINKED).exclude(reason='unlinking').exists():
            _forget_pushes(link.user_id, kind='messages')  # unlinked while it was being told: it goes too
    if WhatsAppInbox.objects.filter(link=link, from_me=False, looked_at__isnull=True).exists():
        _queue_sync(link.pk)


def _store(link, taken) -> list:
    """One look per chat with new messages, in its whole recent conversation (both sides): is what is new
    something she should hear about now, and what could she answer? Returns the new notices with their replies."""
    new = {}
    for row in taken:
        data = _unseal(row.sealed, {})
        if data.get('chat') and data.get('text'):
            new.setdefault(data['chat'], []).append((row.pk, data))
    if not new:
        return []
    looked = []
    for chat_id, rows in new.items():
        rows.sort(key=lambda item: item[1].get('at') or 0)
        last = rows[-1][1]
        lines = conversation(link, chat_id, new_ids={pk for pk, _data in rows})
        preview = '\n'.join(data['text'] for _pk, data in rows[-3:])[-600:]
        if not any(line['nuevo'] for line in lines):
            # Rows from before chat keys (or the window cut them): the new lines themselves are the conversation.
            lines = [{'de': 'contacto', 'texto': data['text'][:500], 'nuevo': True} for _pk, data in rows][-CONTEXT_LINES:]
        looked.append({'chat': chat_id, 'name': last.get('name') or '', 'phone': last.get('phone') or '',
                       'preview': preview, 'at': last.get('at') or 0, 'conversation': lines,
                       'rows': ','.join(str(pk) for pk, _data in rows)})
    verdicts = classify.important([{'chat': row['name'], 'conversation': row['conversation']} for row in looked])
    found = []
    with transaction.atomic():
        if _mine(link).select_for_update().filter(state=WhatsAppLink.State.LINKED).first() is None:
            return []  # unlinked meanwhile: write nothing
        for row, verdict in zip(looked, verdicts):
            if not verdict:
                continue
            # The messages of this look, not their words: the same words in a later message are told again.
            key = _key(str(link.user_id), str(link.grant), row['chat'], 'rows', row['rows'])
            when = timezone.localtime(datetime.fromtimestamp(row['at'], tz=dt_timezone.utc)) if row['at'] else None
            _notice, made = WhatsAppNotice.objects.get_or_create(link=link, source_key=key, defaults={
                'kind': verdict['kind'], 'notified_at': timezone.now(),
                'sealed': _seal({'chat': row['name'], 'jid': row['chat'], 'phone': row['phone'],
                                 'preview': row['preview'], 'summary': verdict['summary'],
                                 # The newest message's own time: a reply of hers after it settles a follow-up.
                                 'at': int(row['at'] or 0),
                                 'time': when.strftime('%H:%M') if when else ''})})
            if made:
                found.append((_notice, verdict.get('replies') or []))
    return found


# ------------------------------------------------------------------ writing

def display_hash(fields) -> str:
    shown = [fields.get('chat') or '', fields.get('phone') or '', fields.get('body') or '']
    return hashlib.sha256(json.dumps(shown, ensure_ascii=False).encode()).hexdigest()


def present(draft, fields=None) -> dict:
    fields = fields if fields is not None else _unseal(draft.sealed, {})
    phone = fields.get('phone')
    return {'id': str(draft.pk), 'chat': fields.get('chat') or None, 'phone': f'+{phone}' if phone else None,
            'body': fields.get('body') or '', 'status': draft.status,
            'reason': REASONS.get(draft.reason) if draft.reason else None, 'display_hash': display_hash(fields)}


def _linked_of(user):
    link = WhatsAppLink.objects.filter(user=user, state=WhatsAppLink.State.LINKED).exclude(reason='unlinking').first()
    if link is None:
        raise LinkRefused('not_linked')
    if note_pending(link):
        raise LinkRefused('finishing')
    if link.consent_version < CONSENT_VERSION:
        raise LinkRefused('consent')
    return link


def _body(value) -> str:
    body = str(value or '').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not body or len(body) > MAX_BODY:
        raise LinkRefused('body')
    return body


def create_draft(user, *, chat=None, phone=None, body=None, instructions=None, notice_id=None):
    """A draft for a chat a message came from (a notice) or one number. Written by the person, or by the model
    from their words. A chat named by hand (no notice) is not one WhatsApp can be asked for: the number is."""
    link = _linked_of(user)
    jid = replying_to = ''
    if notice_id:
        notice = link.notices.filter(pk=notice_id).first() if str(notice_id).isdigit() else None
        if notice is None:
            raise LinkRefused('not_found')
        sealed = _unseal(notice.sealed, {})
        chat, jid, replying_to = sealed.get('chat'), sealed.get('jid') or '', sealed.get('preview') or ''
        if not jid:
            raise LinkRefused('not_found')
    elif chat and not phone:
        raise LinkRefused('chat')  # a bare name is ambiguous: a number (or a reply to a message) is needed
    chat = str(chat or '').strip()[:MAX_NAME]
    if phone and not str(phone).strip().startswith('+'):
        # 4141234567 is a Venezuelan number to the person and a Swiss one to WhatsApp: the + is required.
        raise LinkRefused('phone')
    digits = phone_digits(phone) if phone else ''
    if not jid and not digits:
        raise LinkRefused('chat')
    if jid:
        digits = ''
    if instructions:
        _claim(user, 'write', LIMITS['write'])
        from .assistant_tool import own_only
        # The model's wording of what she asked: a number or a link only if it is in her own words.
        context = transcript(conversation(link, jid)) if jid else ''
        body = own_only(classify.write(str(instructions)[:1000], chat or 'un número nuevo', context or replying_to),
                        [str(instructions)])
    fields = {'chat': chat if jid else '', 'jid': jid, 'phone': digits, 'body': _body(body)}
    with transaction.atomic():
        # One message at a time. While one is on its way no new one is written: if the person could not see it
        # (a stalled request, an app closed mid-send), writing it again would send it twice.
        if WhatsAppDraft.objects.select_for_update().filter(link=link, status=WhatsAppDraft.Status.SENDING).exists():
            raise LinkRefused('on_its_way')
        # And a new one replaces the unsent others, so a late "Enviar" for an older version (a request stalled in
        # the network) finds nothing to send instead of sending it too. Locked like send_draft.
        stale = WhatsAppDraft.objects.select_for_update().filter(link=link, status=WhatsAppDraft.Status.DRAFT)
        WhatsAppDraft.objects.filter(pk__in=list(stale.values_list('pk', flat=True))).delete()
        draft = WhatsAppDraft.objects.create(link=link, sealed=_seal(fields),
                                             expires_at=timezone.now() + timedelta(hours=DRAFT_HOURS))
    return present(draft, fields)


def _draft(user, draft_id, lock=False):
    rows = WhatsAppDraft.objects.select_for_update() if lock else WhatsAppDraft.objects
    draft = rows.filter(pk=draft_id, link__user=user, expires_at__gt=timezone.now()).first()
    if draft is None:
        raise LinkRefused('not_found')
    return draft


def get_draft(user, draft_id):
    return present(_draft(user, draft_id))


def update_draft(user, draft_id, body):
    with transaction.atomic():
        draft = _draft(user, draft_id, lock=True)
        if draft.status != WhatsAppDraft.Status.DRAFT:
            raise LinkRefused('busy')
        fields = _unseal(draft.sealed, {})
        fields['body'] = _body(body)
        draft.sealed, draft.reason = _seal(fields), ''
        draft.save(update_fields=['sealed', 'reason'])
    return present(draft, fields)


def send_draft(user, draft_id, shown_hash):
    """The person tapped Enviar on exactly this text. Sent once, by a worker, at a person's pace."""
    with transaction.atomic():
        draft = _draft(user, draft_id, lock=True)
        if draft.status != WhatsAppDraft.Status.DRAFT:
            raise LinkRefused('busy')
        if draft.link.state != WhatsAppLink.State.LINKED or draft.link.reason == 'unlinking':
            raise LinkRefused('not_linked')
        if note_pending(draft.link):
            raise LinkRefused('finishing')
        if draft.link.consent_version < CONSENT_VERSION:
            raise LinkRefused('consent')
        fields = _unseal(draft.sealed, {})
        if shown_hash != display_hash(fields):
            raise LinkRefused('changed')
        _claim(user, 'send', conf.get('WHATSAPP_LINK_SENDS_PER_DAY'))
        if fields.get('phone'):
            _claim(user, 'new-number', conf.get('WHATSAPP_LINK_NEW_NUMBERS_PER_DAY'))
        draft.status, draft.reason, draft.sending_at = WhatsAppDraft.Status.SENDING, '', timezone.now()
        # Room to finish: the sweep never deletes a draft while it is being sent.
        draft.expires_at = max(draft.expires_at, timezone.now() + timedelta(hours=1))
        draft.save(update_fields=['status', 'reason', 'sending_at', 'expires_at'])
    from . import tasks
    transaction.on_commit(lambda: tasks.send.delay(str(draft.pk)))
    return present(draft, fields)


def send(draft_id, tries=0):
    draft = WhatsAppDraft.objects.select_related('link').filter(pk=draft_id, status=WhatsAppDraft.Status.SENDING).first()
    if draft is None:
        return
    link = draft.link
    fields = _unseal(draft.sealed, {})
    if not enabled() or not fields.get('body') or not (fields.get('jid') or fields.get('phone')):
        _sent(draft, WhatsAppDraft.Status.DRAFT, 'whatsapp')  # nothing left: it can be tried again
        return
    if link.state != WhatsAppLink.State.LINKED or link.reason == 'unlinking':
        _sent(draft, WhatsAppDraft.Status.DRAFT, 'gone')
        return
    try:
        result = bridge.send(link.pk, str(link.grant), str(draft.pk), fields['body'],
                             to=fields.get('jid') or fields.get('phone'))
    except (bridge.BridgeUnavailable, bridge.BridgeRefused):
        # Not asked: nothing left. Tried again a few times; then it is a draft again.
        if tries < 5:
            from . import tasks
            WhatsAppDraft.objects.filter(pk=draft.pk, status=WhatsAppDraft.Status.SENDING).update(
                sending_at=timezone.now())
            tasks.send.apply_async((draft_id, tries + 1), countdown=20)
        else:
            _sent(draft, WhatsAppDraft.Status.DRAFT, 'browser')
        return
    except (TimeoutError, OSError, ValueError):
        _sent(draft, WhatsAppDraft.Status.UNKNOWN, 'unknown')  # asked, no answer: it may have left
        return
    state = result.get('status')
    if state == 'sent':
        _sent(draft, WhatsAppDraft.Status.SENT, '')
    elif state == 'not_sent':
        error = str(result.get('error') or '')
        _sent(draft, WhatsAppDraft.Status.DRAFT, error if error in REASONS else 'whatsapp')
    else:
        _sent(draft, WhatsAppDraft.Status.UNKNOWN, 'unknown')


def _sent(draft, status_, reason):
    fields = {}
    if status_ in (WhatsAppDraft.Status.SENT, WhatsAppDraft.Status.UNKNOWN):
        # The card keeps showing what went and where (sealed) for the hours each look reads as context, then goes.
        fields = {'expires_at': timezone.now() + timedelta(hours=conf.get('WHATSAPP_LINK_CONTEXT_HOURS'))}
    if WhatsAppDraft.objects.filter(pk=draft.pk, status=WhatsAppDraft.Status.SENDING).update(
            status=status_, reason=reason, **fields):
        if status_ == WhatsAppDraft.Status.SENT:
            _context_of_sent(draft)
        from . import chat
        chat.outcome(draft.pk)  # Confío IA says how it went


def _context_of_sent(draft):
    """A reply sent from Confío is part of the chat's conversation (WhatsApp never echoes it back to this device):
    the next look knows she answered."""
    try:
        sent = _unseal(draft.sealed, {})
        link = WhatsAppLink.objects.filter(pk=draft.link_id, state=WhatsAppLink.State.LINKED).first()
        if link is None or not sent.get('jid') or not sent.get('body'):
            return
        WhatsAppInbox.objects.get_or_create(link=link, source_key=_key(str(link.user_id), str(link.grant), 'sent', str(draft.pk)),
                                            defaults={'chat_key': _chat_key(link, sent['jid']), 'from_me': True,
                                                      'looked_at': timezone.now(),
                                                      'sealed': _seal({'chat': sent['jid'], 'name': sent.get('chat') or '',
                                                                       'text': sent['body'][:1000],
                                                                       'at': int(time.time())})})
    except Exception as exc:  # noqa: BLE001 - the send is done either way
        logger.warning('WhatsApp sent reply not kept as context: %s', type(exc).__name__)


# ------------------------------------------------------------------ sweep

def _leavers():
    """Links of people deleted, deactivated or banned: one query, all of them."""
    from security.models import UserBan
    now = timezone.now()
    banned = UserBan.objects.filter(deleted_at__isnull=True).exclude(
        ban_type='temporary', expires_at__lt=now).values('user_id')
    return WhatsAppLink.objects.exclude(reason='unlinking').filter(
        Q(user__is_active=False) | Q(user__deleted_at__isnull=False) | Q(user_id__in=banned)).select_related('user')


def sweep():
    """Erases what must not stay and restarts what a restart lost."""
    from . import tasks
    now = timezone.now()
    # A send that never reported back: unknown, so it is never sent twice (and the assistant says so).
    for stuck in WhatsAppDraft.objects.filter(status=WhatsAppDraft.Status.SENDING,
                                              sending_at__lt=now - SENDING_STUCK)[:50]:
        _sent(stuck, WhatsAppDraft.Status.UNKNOWN, 'unknown')
    if conf.get('WHATSAPP_LINK_KEEP_DAYS'):
        WhatsAppNotice.objects.filter(created_at__lt=now - timedelta(days=conf.get('WHATSAPP_LINK_KEEP_DAYS'))).delete()
    WhatsAppDraft.objects.filter(expires_at__lte=now).exclude(status=WhatsAppDraft.Status.SENDING).delete()
    # What a push said of a message is kept no longer than the messages. An answer that told her what they said
    # stays: it is the conversation's context, and later answers need it (founder 2026-11-26); it goes when she
    # unlinks (chat.erase).
    _forget_pushes(before=_history_since())
    # Messages are kept HISTORY_DAYS: older ones go (looked at or not). And none stays on a link that is no longer
    # linked (a message that landed just as the phone unlinked it).
    WhatsAppInbox.objects.filter(Q(created_at__lt=_history_since()) | ~Q(link__state=WhatsAppLink.State.LINKED)
                                 | Q(link__reason='unlinking')).delete()
    for link in _leavers()[:20]:
        try:
            unlink(link.user, WhatsAppLinkRecord.EndedBy.ACCOUNT)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - one row must not stop the others
            logger.warning('WhatsApp link %s: unlink of a leaver failed: %s', link.pk, type(exc).__name__)
    for link_id in WhatsAppLink.objects.filter(reason='unlinking', updated_at__lt=now - timedelta(minutes=5)).values_list(
            'pk', flat=True)[:20]:
        tasks.forget.delay(link_id)
    # A pairing whose end never came (the bridge restarted): over.
    for link in WhatsAppLink.objects.filter(
            Q(session_expires_at__lt=now - timedelta(minutes=2)) | Q(session_expires_at__isnull=True,
                                                                     updated_at__lt=now - timedelta(minutes=15)),
            state=WhatsAppLink.State.PAIRING).exclude(reason='unlinking')[:20]:
        _fail(link, 'timeout')
    # A note to the owner past its deadline undoes the link; one whose chain was lost starts again.
    for link_id, grant, linked_at in WhatsAppLink.objects.filter(state=WhatsAppLink.State.LINKED).exclude(
            sealed_phone='').exclude(reason='unlinking').values_list('pk', 'grant', 'linked_at')[:20]:
        if linked_at and linked_at < now - NOTE_DEADLINE:
            _note_failed(link_id, grant)
        elif cache.add(f'whatsapp-link:note-restart:{grant}', 1, 600):
            tasks.warn_self.apply_async((link_id, str(grant)), countdown=1)
    # Messages waiting whose look was lost; one that waited past the context window is never looked at.
    _retire_unlooked(WhatsAppInbox.objects.all())
    for link_id in WhatsAppInbox.objects.filter(from_me=False, looked_at__isnull=True,
                                                created_at__lt=now - timedelta(minutes=10),
                                                link__state=WhatsAppLink.State.LINKED,
                                                link__consent_version__gte=CONSENT_VERSION).values_list(
            'link_id', flat=True).distinct()[:50]:
        _queue_sync(link_id, countdown=0)
    # A linked WhatsApp on an older text: the assistant asks, once per version (nothing is read until it is accepted).
    from . import chat
    for link in WhatsAppLink.objects.filter(state=WhatsAppLink.State.LINKED, consent_version__lt=CONSENT_VERSION).exclude(
            reason='unlinking').exclude(sealed_phone__gt='').select_related('user')[:20]:
        try:
            if chat.ask_consent(link, CONSENT_VERSION):
                _notify(link.user, 'Cambié cómo leo tu WhatsApp. Revísalo en Confío IA para que siga avisándote.',
                        {'kind': 'messages'})
        except Exception as exc:  # noqa: BLE001 - asked again at the next sweep
            logger.warning('WhatsApp consent ask for link %s failed: %s', link.pk, type(exc).__name__)
    # Browser profiles from before whatsmeow (Browserbase): deleted.
    for link_id, provider, context_id in WhatsAppLink.objects.exclude(context_id='').exclude(
            provider=PROVIDER).values_list('pk', 'provider', 'context_id')[:20]:
        tasks.drop_profile.delay(provider, context_id, '')
        WhatsAppLink.objects.filter(pk=link_id, context_id=context_id).update(context_id='', session_id='')


def profile_orphaned(provider_name, context_id, session_id=''):
    """A Browserbase profile from before whatsmeow: deleted. Raises BrowserUnavailable so the task retries."""
    from agent_tasks import browsers
    provider = browsers.provider(provider_name or None)
    if session_id:
        try:
            provider.close(session_id)
        except browsers.BrowserUnavailable:
            pass
    provider.delete_profile(context_id)
