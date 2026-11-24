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
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone

from celery.exceptions import SoftTimeLimitExceeded
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
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
CONSENT_VERSION = 3
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


def _notify(user, message, data=None):
    try:
        from notifications.models import NotificationType
        from notifications.utils import create_notification
        # Fixed words and counts only: a lock screen never shows a WhatsApp message.
        create_notification(user=user, notification_type=NotificationType.SYSTEM, title=TITLE, message=message,
                            data={'type': NOTICE_TYPE, 'screen': 'WhatsApp', **(data or {})})
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning('WhatsApp notice failed: %s', type(exc).__name__)


def _forget_pushes(user_id):
    try:
        from notifications.models import Notification
        with transaction.atomic():
            Notification.objects.filter(user_id=user_id, data__type=NOTICE_TYPE).delete()
    except Exception as exc:  # noqa: BLE001
        logger.warning('WhatsApp notices not erased: %s', type(exc).__name__)


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
    if consent_version != CONSENT_VERSION:
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
                      sealed_code='', code_at=None, linked_at=None, next_sync_at=None, failures=0,
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
    if consent_version != CONSENT_VERSION:
        raise LinkRefused('consent')
    WhatsAppLink.objects.filter(user=user, state=WhatsAppLink.State.LINKED).exclude(reason='unlinking').update(
        consent_version=consent_version)


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
            updated_at=timezone.now())
    _forget_pushes(user.pk)
    _end_record(user.pk, ended_by)
    from . import tasks
    transaction.on_commit(lambda: tasks.forget.delay(link.pk))
    return True


def refresh(user):
    """Opening Confío IA: what arrived and waits to be looked at is looked at now (messages come by themselves)."""
    link = WhatsAppLink.objects.filter(user=user, state=WhatsAppLink.State.LINKED).exclude(reason='unlinking').first()
    if link is None or link.consent_version < CONSENT_VERSION or note_pending(link) or not link.inbox.exists():
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
        if kind in ('paired', 'message'):
            # A device for a pairing that is over (unlinked or asked again meanwhile): it must not stay linked.
            _queue_logout(event.get('link'), event.get('grant'))
        return
    if kind in ('paired', 'message') and link.state not in (WhatsAppLink.State.PAIRING, WhatsAppLink.State.LINKED):
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
    """A new message someone wrote the person. Kept sealed until the next look (sync), a minute or two later,
    so a burst of messages is one look; never kept when it looks like a code or a password."""
    if link.state != WhatsAppLink.State.LINKED or link.consent_version < CONSENT_VERSION or note_pending(link):
        return  # nothing is read before the note is written, nor under an older consent
    row = {'name': str(data.get('name') or '')[:MAX_NAME], 'preview': str(data.get('text') or '')[:1000]}
    if not row['preview'] or private(row):
        return
    key = _key(str(link.user_id), str(link.grant), str(data.get('id') or ''), str(data.get('chat') or ''))
    if cache.get(f'whatsapp-link:seen:{key}'):
        return  # delivered again after it was looked at: never a second notice
    WhatsAppInbox.objects.get_or_create(link=link, source_key=key, defaults={'sealed': _seal({
        'chat': str(data.get('chat') or ''), 'name': row['name'], 'phone': str(data.get('phone') or ''),
        'text': row['preview'], 'at': int(data.get('at') or 0)})})
    cache.set(f'whatsapp-link:seen:{key}', 1, 86400)  # only once it is kept: a failure is delivered again
    _queue_sync(link.pk)


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
            state=WhatsAppLink.State.GONE, reason=reason, next_sync_at=None, sealed_phone=''):
        return
    link.notices.all().delete()
    link.inbox.all().delete()
    link.drafts.exclude(status=WhatsAppDraft.Status.SENDING).delete()
    _end_record(link.user_id, ended_by)
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
    """Classifies what arrived since the last look and keeps only the important. Messages are deleted once
    looked at, kept or not."""
    cache.delete(f'whatsapp-link:queued:{link_id}')
    if not enabled():
        return
    link = WhatsAppLink.objects.select_related('user').filter(
        pk=link_id, state=WhatsAppLink.State.LINKED).exclude(reason='unlinking').first()
    if link is None or link.consent_version < CONSENT_VERSION or note_pending(link):
        return
    # One look per link at a time; the messages are deleted only once looked at (a failed look keeps them for
    # the next, and the sweep drops any older than a day).
    lease = f'whatsapp-link:looking:{link_id}'
    if not cache.add(lease, 1, 120):
        _queue_sync(link_id)
        return
    try:
        taken = list(WhatsAppInbox.objects.filter(link=link).order_by('pk')[:100])
        if not taken:
            return
        started = time.monotonic()
        try:
            found = _store(link, [_unseal(row.sealed, {}) for row in taken])
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - by type: a message can quote a chat
            logger.warning('WhatsApp classify %s failed: %s', link.pk, type(exc).__name__)
            return
        WhatsAppInbox.objects.filter(pk__in=[row.pk for row in taken]).delete()
    finally:
        cache.delete(lease)
    logger.info('WhatsApp classify link=%s messages=%d important=%d ms=%d', link.pk, len(taken), found,
                (time.monotonic() - started) * 1000)
    _mine(link).update(last_sync_at=timezone.now())
    if found and _mine(link).filter(state=WhatsAppLink.State.LINKED).exclude(reason='unlinking').exists():
        noun = 'mensaje importante' if found == 1 else 'mensajes importantes'
        _notify(link.user, f'Tienes {found if found < 10 else "más de 9"} {noun} en WhatsApp. Míralos en Confío IA.')
    if WhatsAppInbox.objects.filter(link=link).exists():
        _queue_sync(link.pk)


def _store(link, messages) -> int:
    """One look per chat: its newest lines, oldest first. Returns how many notices are new."""
    chats = {}
    for message in messages:
        if not message.get('chat') or not message.get('text'):
            continue
        chats.setdefault(message['chat'], []).append(message)
    if not chats:
        return 0
    looked = []
    for chat, lines in chats.items():
        lines.sort(key=lambda line: line.get('at') or 0)
        preview = '\n'.join(line['text'] for line in lines[-3:])[-600:]
        looked.append({'chat': chat, 'name': lines[-1].get('name') or '', 'phone': lines[-1].get('phone') or '',
                       'preview': preview, 'at': lines[-1].get('at') or 0})
    verdicts = classify.important([{'chat': row['name'], 'preview': row['preview']} for row in looked])
    found = 0
    with transaction.atomic():
        if _mine(link).select_for_update().filter(state=WhatsAppLink.State.LINKED).first() is None:
            return 0  # unlinked meanwhile: write nothing
        for row, verdict in zip(looked, verdicts):
            if not verdict:
                continue
            key = _key(str(link.user_id), str(link.grant), row['chat'], row['preview'])
            when = timezone.localtime(datetime.fromtimestamp(row['at'], tz=dt_timezone.utc)) if row['at'] else None
            _notice, made = WhatsAppNotice.objects.get_or_create(link=link, source_key=key, defaults={
                'kind': verdict['kind'], 'notified_at': timezone.now(),
                'sealed': _seal({'chat': row['name'], 'jid': row['chat'], 'phone': row['phone'],
                                 'preview': row['preview'], 'summary': verdict['summary'],
                                 'time': when.strftime('%H:%M') if when else ''})})
            found += int(made)
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
    jid = ''
    if notice_id:
        notice = link.notices.filter(pk=notice_id).first() if str(notice_id).isdigit() else None
        if notice is None:
            raise LinkRefused('not_found')
        sealed = _unseal(notice.sealed, {})
        chat, jid = sealed.get('chat'), sealed.get('jid') or ''
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
        body = classify.write(str(instructions)[:1000], chat or 'un número nuevo')
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
        fields = {'sealed': _seal({}), 'expires_at': timezone.now() + timedelta(hours=1)}  # the text goes now
    WhatsAppDraft.objects.filter(pk=draft.pk, status=WhatsAppDraft.Status.SENDING).update(
        status=status_, reason=reason, **fields)


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
    # A send that never reported back: unknown, so it is never sent twice.
    WhatsAppDraft.objects.filter(status=WhatsAppDraft.Status.SENDING, sending_at__lt=now - SENDING_STUCK).update(
        status=WhatsAppDraft.Status.UNKNOWN, reason='unknown', sealed=_seal({}), expires_at=now + timedelta(hours=1))
    if conf.get('WHATSAPP_LINK_KEEP_DAYS'):
        WhatsAppNotice.objects.filter(created_at__lt=now - timedelta(days=conf.get('WHATSAPP_LINK_KEEP_DAYS'))).delete()
    WhatsAppDraft.objects.filter(expires_at__lte=now).exclude(status=WhatsAppDraft.Status.SENDING).delete()
    # Messages nobody looked at within a day (a look that kept failing): not kept.
    WhatsAppInbox.objects.filter(created_at__lt=now - timedelta(days=1)).delete()
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
    # Messages waiting whose look was lost.
    for link_id in WhatsAppInbox.objects.filter(created_at__lt=now - timedelta(minutes=10)).values_list(
            'link_id', flat=True).distinct()[:50]:
        _queue_sync(link_id, countdown=0)
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
