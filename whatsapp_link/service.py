"""The person's WhatsApp link: pairing, reading the chat list, unlinking, sending.

One browser profile per person, at the vendor, in its own region. Only
this module opens it, and only for that person's link. One worker at a time
holds it (lease_until). Only the person's own Confío number can be linked:
a pairing code for someone else's number is how WhatsApp accounts get stolen.

Money never moves here. A payment someone asks for in WhatsApp goes through
the app's own payment cards, which the person approves.

Sending: createWhatsAppDraft returns the text and its hash; only the
person's tap on that card may call sendWhatsAppDraft. No assistant tool may
send a draft (founder rule: the assistant never acts on its own).
"""
import contextlib
import hashlib
import json
import logging
import re
import uuid
from datetime import timedelta

from celery.exceptions import SoftTimeLimitExceeded
from django.core.cache import cache
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.crypto import salted_hmac

from agent_tasks import browsers
from agent_tasks.cdp import CdpError, Page
from users.encryption import decrypt_data, encrypt_data

from . import classify, conf, web
from .models import WhatsAppDraft, WhatsAppLink, WhatsAppLinkRecord, WhatsAppNotice

logger = logging.getLogger(__name__)

LEASE = timedelta(minutes=5)
WATCH_SECONDS = 45  # one watch holds the browser this long, then hands over to the next
REASK_BEFORE = 30  # past this in a watch, a lapsed code is asked again by the next watch
SETTLE_AFTER_LINK = 30  # WhatsApp copies the chat list to a new device: let it start before closing
SENDING_STUCK = timedelta(minutes=12)  # past the lease wait (about 200 s) and the task's limits
MAX_BACKOFF = timedelta(hours=12)
SEND_BUSY_TRIES = 40  # 20 s apart: longer than a pairing (10 min) holds its browser
PAIR_RETRIES = 80  # 4 to 10 s apart: longer than a lease (5 min) a killed task may leave behind
DRAFT_HOURS = 24
MAX_BODY = 2000
# 2: the person types the number; Confío writes one note to their own chat when it is linked.
CONSENT_VERSION = 2
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
    'browser': 'No pude abrir WhatsApp ahora. Inténtalo en unos minutos.',
    'whatsapp': 'WhatsApp no respondió como esperaba. Inténtalo en unos minutos.',
    'chat_not_found': 'No encontré ese chat en tu WhatsApp. Escribe su nombre tal como aparece.',
    'chat_ambiguous': 'Hay más de un chat con ese nombre. Usa el número en su lugar.',
    'number_not_on_whatsapp': 'Ese número no tiene WhatsApp.',
    'composer_not_empty': 'No pude preparar ese chat para escribir. Inténtalo de nuevo.',
    'typed_mismatch': 'No pude escribir el mensaje tal como lo aprobaste. No se envió.',
    'unknown': 'No sé si el mensaje salió. Revisa el chat en tu teléfono antes de repetirlo.',
    'gone': GONE,
    'not_own_phone': 'El WhatsApp de este navegador no es el número que escribiste. Lo desvinculé.',
    'number_taken': ('No pude vincular ese número. Si lo vinculaste en otra cuenta de Confío, desvincúlalo allí '
                     'primero.'),
    'phone_mismatch': 'WhatsApp mostró otro número. Revisa el número que escribiste e inténtalo de nuevo.',
    'pending': ('Tu mensaje quedó en espera en WhatsApp y puede salir más tarde. Revisa el chat en tu teléfono '
                'antes de repetirlo.'),
    'partial_sent': 'Salió solo una parte del mensaje. Revisa el chat en tu teléfono antes de repetirlo.',
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


@contextlib.contextmanager
def _taken(link_id, grant=None, seconds=LEASE):
    """The link, leased to this worker for the block (None when another holds it or it changed).
    The lease always ends with the block, whatever happens in it."""
    now = timezone.now()
    rows = WhatsAppLink.objects.filter(pk=link_id).exclude(lease_until__gt=now)
    if grant:
        rows = rows.filter(grant=grant)
    if not rows.update(lease_until=now + seconds):
        yield None
        return
    try:
        yield WhatsAppLink.objects.select_related('user').filter(pk=link_id).first()
    finally:
        WhatsAppLink.objects.filter(pk=link_id).update(lease_until=None)


def _mine(link):
    return WhatsAppLink.objects.filter(pk=link.pk, grant=link.grant)


def _vendor(link=None):
    return browsers.provider((link.provider if link is not None else '') or None)


SLOTS = 2  # WhatsApp tasks at once on the shared browser worker (3 processes): a purchase always has one
SLOT_SECONDS = 300  # past every browser task's hard time limit: a killed worker's slot frees itself


@contextlib.contextmanager
def _slot():
    """One of WhatsApp's two places on the browser worker, held for the whole task, or False."""
    token = uuid.uuid4().hex
    for number in range(SLOTS):
        key = f'whatsapp-link:slot:{number}'
        try:
            taken = cache.add(key, token, SLOT_SECONDS)
        except Exception:  # noqa: BLE001 - no counter, no slot
            taken = False
        if taken:
            try:
                yield True
            finally:
                try:
                    if cache.get(key) == token:
                        cache.delete(key)
                except Exception:  # noqa: BLE001 - it expires on its own
                    pass
            return
    yield False


OPEN_LOCK = 47113503  # pg advisory lock: one WhatsApp browser opens at a time, so the room check holds


def _room(link, kind) -> bool:
    """Whether WhatsApp may open one more browser now. The plan's browsers are shared with purchases.

    background (reads): WhatsApp's share, and one browser always left free.
    pair: WhatsApp's share.
    send: any free browser, one past WhatsApp's share: an approved message never waits behind a pairing."""
    from agent_tasks.models import AgentTask
    now = timezone.now()
    # Browsers only: worker places are bounded by _slot.
    ours = WhatsAppLink.objects.exclude(pk=link.pk).exclude(session_id='').filter(session_expires_at__gt=now).count()
    # Every purchase under way counts, also one whose browser is about to open: it was admitted first.
    shopping = AgentTask.objects.filter(state__in=AgentTask.ACTIVE).count()
    free = conf.get('WHATSAPP_LINK_PLAN_CONCURRENCY') - ours - shopping - (1 if kind == 'background' else 0)
    share = conf.get('WHATSAPP_LINK_MAX_SESSIONS') + (1 if kind == 'send' else 0)
    return ours < share and free > 0


def _open(link, seconds, *, kind='pair'):
    """A browser on the person's own profile. Creates the profile on first use.
    Only when the plan has room (`_room`); busy otherwise.

    The profile and session ids are bookkeeping, written by row whatever the
    grant: a vendor profile nobody recorded could never be deleted."""
    from django.db import connection
    provider = _vendor()
    if not link.context_id:
        context = provider.create_profile()
        if not WhatsAppLink.objects.filter(pk=link.pk).update(context_id=context, provider=provider.name):
            from . import tasks
            tasks.drop_profile.delay(provider.name, context)  # retried there until it is gone
            raise browsers.BrowserUnavailable('link gone')
        link.context_id, link.provider = context, provider.name
    _close(link)
    session = None
    try:
        # Checked, opened and recorded under one lock: two workers never both see the last free browser.
        with transaction.atomic():
            with connection.cursor() as cursor:
                # Never waited for: another open in progress is a busy browser plan, retried like one.
                cursor.execute('SELECT pg_try_advisory_xact_lock(%s)', [OPEN_LOCK])
                got = cursor.fetchone()[0]
            if not got or not _room(link, kind):
                raise browsers.BrowserUnavailable('no browser free for WhatsApp now', 'busy')
            session = provider.open(profile_id=link.context_id, country='', seconds=seconds, solve_captchas=False,
                                    viewport=conf.get('WHATSAPP_LINK_VIEWPORT'),
                                    region=conf.get('WHATSAPP_LINK_REGION'))
            recorded = WhatsAppLink.objects.filter(pk=link.pk).update(
                session_id=session.id, sealed_connect_url=_seal(session.connect_url),
                session_expires_at=session.expires_at)
            if not recorded:
                raise browsers.BrowserUnavailable('link gone')
    except BaseException:
        # Opened and not recorded (an error, a time limit, a failed commit): nobody would count or close it.
        if session is not None:
            try:
                provider.close(session.id)
            except browsers.BrowserUnavailable:
                pass
        raise
    link.session_id, link.session_expires_at = session.id, session.expires_at
    return session.connect_url


def _close(link):
    """Closing is what saves the profile at the vendor: every opened browser is closed."""
    if not link.session_id:
        return
    try:
        _vendor(link).close(link.session_id)
    except browsers.BrowserUnavailable:
        logger.warning('WhatsApp link %s: closing the browser failed', link.pk)
    WhatsAppLink.objects.filter(pk=link.pk, session_id=link.session_id).update(
        session_id='', sealed_connect_url='', session_expires_at=None)
    link.session_id = ''


def _drop_profile(link):
    """Deletes the vendor profile (the WhatsApp session in it) and forgets its id."""
    _close(link)
    if not link.context_id:
        return True
    try:
        _vendor(link).delete_profile(link.context_id)
    except browsers.BrowserUnavailable:
        logger.warning('WhatsApp link %s: profile not deleted yet', link.pk)
        return False
    WhatsAppLink.objects.filter(pk=link.pk, context_id=link.context_id).update(context_id='')
    link.context_id = ''
    return True


@contextlib.contextmanager
def _guarded(connect_url):
    """A connection that only lets WhatsApp Web's own pages load, closed the proper way."""
    with Page(connect_url) as page:
        page.guard_documents(web.allowed)
        try:
            # The screens are read in English: WhatsApp Web follows the browser's language.
            page.call('Emulation.setLocaleOverride', {'locale': 'en-US'})
        except CdpError:
            pass  # already set on this tab
        yield page


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


def start_link(user, phone, consent_version):
    """Asks WhatsApp for a pairing code for the number the person typed (with its country code).

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
                      phone_key=phone_key(digits),
                      sealed_code='', code_at=None, linked_at=None, next_sync_at=None, failures=0,
                      consent_version=consent_version, grant=uuid.uuid4(), session_expires_at=None)
        if link is None:
            link = WhatsAppLink.objects.create(user=user, provider='', **fields)
        else:
            # A new pairing may be another WhatsApp: nothing of the last one carries over.
            link.notices.all().delete()
            link.drafts.all().delete()
            for name, value in fields.items():
                setattr(link, name, value)
            link.save()
    from . import tasks
    grant = str(link.grant)
    transaction.on_commit(lambda: tasks.pair.delay(link.pk, grant))
    return link


def accept_consent(user, consent_version):
    """A linked person accepts today's text: reads start again."""
    if consent_version != CONSENT_VERSION:
        raise LinkRefused('consent')
    WhatsAppLink.objects.filter(user=user, state=WhatsAppLink.State.LINKED).exclude(reason='unlinking').update(
        consent_version=consent_version, next_sync_at=timezone.now())


def unlink(user, ended_by=WhatsAppLinkRecord.EndedBy.CONFIO, grant=None, only_pending=False):
    """Erases what came from WhatsApp now; a worker logs the browser out and deletes its profile."""
    with transaction.atomic():
        link = WhatsAppLink.objects.select_for_update().filter(user=user).first()
        if link is None or link.reason == 'unlinking' or (grant is not None and str(link.grant) != str(grant)):
            return False
        if only_pending and not note_pending(link):
            return False  # the note was written meanwhile: nothing to undo
        link.notices.all().delete()
        link.drafts.all().delete()
        WhatsAppLink.objects.filter(pk=link.pk).update(
            reason='unlinking', grant=uuid.uuid4(), sealed_code='', code_at=None, sealed_phone='', next_sync_at=None,
            updated_at=timezone.now())
    _forget_pushes(user.pk)
    _end_record(user.pk, ended_by)
    from . import tasks
    transaction.on_commit(lambda: tasks.forget.delay(link.pk))
    return True


def refresh(user):
    """Opening Confío IA asks for a fresh read, at most every REFRESH minutes, never past a backoff."""
    link = WhatsAppLink.objects.filter(user=user, state=WhatsAppLink.State.LINKED).exclude(reason='unlinking').first()
    if link is None or link.failures or link.consent_version < CONSENT_VERSION or _gone_seen(link) is not None \
            or note_pending(link):
        return False
    soon = timezone.now() - timedelta(minutes=conf.get('WHATSAPP_LINK_REFRESH_MINUTES'))
    if link.last_sync_at and link.last_sync_at > soon:
        return False
    _claim(user, 'refresh', LIMITS['refresh'])
    WhatsAppLink.objects.filter(pk=link.pk, failures=0).update(next_sync_at=timezone.now())
    _queue_sync(link.pk)
    return True


def dismiss(user, notice_id):
    if str(notice_id).isdigit():
        WhatsAppNotice.objects.filter(pk=notice_id, link__user=user).delete()


# ------------------------------------------------------------------ pairing (browser worker)

def pair(link_id, grant, tries=0):
    with _slot() as placed:
        if placed:
            return _pair(link_id, grant, tries)
    # Both of WhatsApp's places on the browser worker are taken: this waits, nothing is spent.
    waiting = WhatsAppLink.objects.filter(pk=link_id, grant=grant, state=WhatsAppLink.State.PAIRING,
                                          code_at__isnull=True).exclude(reason='unlinking')
    if tries < PAIR_RETRIES and enabled() and waiting.exists():
        from . import tasks
        tasks.pair.apply_async((link_id, grant, tries + 1), countdown=10)
        return
    with _taken(link_id, grant) as link:
        if link is not None and link.state == WhatsAppLink.State.PAIRING and link.code_at is None:
            # Nobody is asking WhatsApp for a code right now: ended, its browser and profile with it.
            _fail(link, 'browser' if enabled() else 'whatsapp')


def _pair(link_id, grant, tries):
    from . import tasks
    again, busy = None, False
    with _taken(link_id, grant) as link:
        if link is None:
            # Another pairing or watch still holds the browser: come back until it lets go.
            waiting = WhatsAppLink.objects.filter(pk=link_id, grant=grant, state=WhatsAppLink.State.PAIRING).exclude(
                reason='unlinking')
            if tries < PAIR_RETRIES and enabled() and waiting.exists():
                tasks.pair.apply_async((link_id, grant, tries + 1), countdown=4)
            elif not enabled():
                waiting.filter(code_at__isnull=True).update(state=WhatsAppLink.State.FAILED, reason='whatsapp',
                                                            sealed_phone='')
            return
        if link.state != WhatsAppLink.State.PAIRING or link.reason == 'unlinking' or link.code_at is not None:
            return  # a code for this pairing is out: the person may be typing it, its browser stays
        if not enabled():
            _fail(link, 'whatsapp')
            return
        cache.set(f'whatsapp-link:pair-started:{grant}', 1, 900)
        try:
            with _guarded(_open(link, conf.get('WHATSAPP_LINK_PAIRING_SECONDS'))) as page:
                if not _mine(link).filter(state=WhatsAppLink.State.PAIRING).exists():
                    _close(link)  # unlinked or asked again while the browser opened: no prompt on the phone
                    return
                page.goto(web.HOME)
                try:
                    code = web.ask_for_code(page, _unseal(link.sealed_phone, ''))
                except web.WebError as exc:
                    if exc.code != 'already_linked':
                        raise
                    # A profile signed in before this pairing: it must be the person's own number.
                    page.pump(5.0)
                    _linked(link, number=web.signed_in_number(page))
                    return
            if _mine(link).filter(state=WhatsAppLink.State.PAIRING).update(sealed_code=_seal(code),
                                                                           code_at=timezone.now()):
                again = str(link.grant)
            else:
                _close(link)
        except web.WebError as exc:
            # The step's name only (no number, no code): what to look at when WhatsApp Web changes.
            logger.warning('WhatsApp pairing %s stopped at %s', link.pk, exc.code)
            _fail(link, exc.code if exc.code in REASONS else 'whatsapp')
        except (browsers.BrowserUnavailable, CdpError) as exc:
            if getattr(exc, 'code', '') == 'busy' and tries < PAIR_RETRIES:
                busy = True  # every browser is in use: the pairing waits its turn, nothing is spent
            else:
                _fail(link, 'browser')
        except BaseException:
            _fail(link, 'whatsapp')  # a time limit or anything unforeseen: never a pairing left open
            raise
    if busy:
        tasks.pair.apply_async((link_id, grant, tries + 1), countdown=10)
    if again:
        tasks.watch.apply_async((link_id, again), countdown=2)


def watch(link_id, grant):
    with _slot() as placed:
        if placed:
            return _watch(link_id, grant)
    # No place now: the pairing's browser stays open and is looked at again in a moment, for as long as it
    # lives. No de-duplication here: an extra chain is cheap and merges once a place frees (the leased path).
    if enabled() and WhatsAppLink.objects.filter(
            pk=link_id, grant=grant, state=WhatsAppLink.State.PAIRING, session_expires_at__gt=timezone.now()).exclude(
            session_id='').exists():
        from . import tasks
        tasks.watch.apply_async((link_id, grant), countdown=3)


def _watch(link_id, grant):
    """Until the person types the code: keeps the code fresh and sees the link happen."""
    from . import tasks
    again = soon = False
    with _taken(link_id, grant) as link:
        if link is None:
            # Held by a pair or another watch for a moment: look again so the pairing is never unwatched.
            soon = WhatsAppLink.objects.filter(pk=link_id, grant=grant, state=WhatsAppLink.State.PAIRING).exclude(
                session_id='').exists() and cache.add(f'whatsapp-link:watch-requeued:{grant}', 1, 20)
        elif link.state != WhatsAppLink.State.PAIRING or not link.session_id:
            return
        elif not enabled():
            _fail(link, 'whatsapp')
            return
        else:
            again = _watch_once(link)
    if soon:
        tasks.watch.apply_async((link_id, grant), countdown=3)
    if again:
        tasks.watch.apply_async((link_id, grant), countdown=1)


def _watch_once(link):
    """One watch's budget on the pairing browser. True when the next watch should go on."""
    started = timezone.now()
    try:
        if not link.session_expires_at or link.session_expires_at <= started + timedelta(seconds=20):
            _fail(link, 'timeout')
            return
        shown = _unseal(link.sealed_code)
        with _guarded(_unseal(link.sealed_connect_url, '')) as page:
            while timezone.now() < started + timedelta(seconds=WATCH_SECONDS):
                if not _mine(link).filter(state=WhatsAppLink.State.PAIRING).exists():
                    _close(link)
                    return  # unlinked or asked again meanwhile
                seen = web.screen(page)
                if seen in ('chats', 'loading'):
                    _linked(link, page)
                    return
                if seen == 'code':
                    code = web.read_code(page)
                    if not code and web.refresh_code(page):
                        code = web.read_code(page)
                    if code and code != shown:
                        _mine(link).filter(state=WhatsAppLink.State.PAIRING).update(
                            sealed_code=_seal(code), code_at=timezone.now())
                        shown = code
                elif seen in ('login', 'phone'):
                    if timezone.now() > started + timedelta(seconds=REASK_BEFORE):
                        break  # asking takes long: the next watch does it with a whole budget
                    # The code lapsed and WhatsApp went back to its first screen: ask again.
                    try:
                        code = web.ask_for_code(page, _unseal(link.sealed_phone, ''))
                    except web.WebError as exc:
                        # The person may have typed the code just as it was asked again.
                        if exc.code == 'already_linked' or web.screen(page) in ('chats', 'loading'):
                            _linked(link, page)
                            return
                        raise
                    _mine(link).filter(state=WhatsAppLink.State.PAIRING).update(
                        sealed_code=_seal(code), code_at=timezone.now())
                    shown = code
                page.pump(3.0)
        return True
    except web.WebError as exc:
        logger.warning('WhatsApp pairing %s stopped at %s', link.pk, exc.code)
        _fail(link, exc.code if exc.code in REASONS else 'whatsapp')
    except (browsers.BrowserUnavailable, CdpError):
        _fail(link, 'browser')
    except BaseException:
        _fail(link, 'whatsapp')
        raise
    return False


def _linked(link, page=None, number=None):
    """`number`: read from a profile that was signed in before this pairing. It must be the person's own;
    unread ('') is no proof, and the pairing ends (the person can ask again)."""
    typed = _unseal(link.sealed_phone, '')
    if number is not None and number != typed:
        _fail(link, 'not_own_phone' if number else 'whatsapp')
        return
    # The number WhatsApp itself says is signed in decides (a spelling of the same number, with or without a
    # 0 or a 9, would otherwise get past one account per number). Unread: the typed one, which WhatsApp paired.
    signed = number or (_signed_in(page) if page is not None else '')
    # Only a spelling of the typed number (the same last 8 digits): a profile used before can still hold the
    # last account's number for a moment, and that one is never recorded, held or written to.
    digits = signed if signed and typed and signed[-8:] == typed[-8:] else typed
    now = timezone.now()
    with transaction.atomic():
        _number_lock(digits)
        if _number_taken(link.user, digits, linked_only=True, exclude_pk=link.pk):
            taken = True
        else:
            taken = False
            # The number stays sealed until the note to the person's own chat is written (warn_self), then goes.
            linked = _mine(link).filter(state=WhatsAppLink.State.PAIRING).update(
                state=WhatsAppLink.State.LINKED, reason='', sealed_code='', code_at=None, linked_at=now, failures=0,
                sealed_phone=_seal(digits), phone_key=phone_key(digits), phone_hint=digits[-4:],
                next_sync_at=now + timedelta(minutes=conf.get('WHATSAPP_LINK_SYNC_MINUTES')))
            if linked:
                # With the link itself, so no crash in between loses them and an unlink always finds the record.
                _end_record(link.user_id, WhatsAppLinkRecord.EndedBy.CONFIO, now)  # left open by a lost unlink
                WhatsAppLinkRecord.objects.create(
                    user_id=link.user_id, phone=f'+{digits}', phone_key=phone_key(digits),
                    phone_hint=digits[-4:], consent_version=link.consent_version, linked_at=now)
                from . import tasks
                grant = str(link.grant)
                transaction.on_commit(lambda: tasks.warn_self.apply_async((link.pk, grant), countdown=5))
    if taken:
        _fail(link, 'number_taken')  # another account linked it first: this one never holds it
        return
    if not linked:
        _close(link)
        return  # unlinked or asked again meanwhile: nothing to say
    link.refresh_from_db()
    if page is not None:
        try:
            page.pump(SETTLE_AFTER_LINK)
        except CdpError:
            pass
    _close(link)
    _notify(link.user, 'Tu WhatsApp quedó vinculado. Te aviso cuando llegue algo importante.')


# What the owner of the WhatsApp reads in their own chat right after it is linked. Fixed words.
SELF_NOTE = ('Confío: este WhatsApp se vinculó a una cuenta de Confío (aparece como «Chrome» en Dispositivos '
             'vinculados). Si no fuiste tú, desvincúlalo ahora y no compartas códigos con nadie.')
WARN_TRIES = 60  # a minute apart: an hour of a busy plan never drops the note


def note_pending(link) -> bool:
    """Linked, and the note to the owner's own chat not written yet: nothing is read or sent until it is,
    so keeping every browser busy (to keep the note away) gets nothing."""
    return link.state == WhatsAppLink.State.LINKED and bool(link.sealed_phone)


OPENED_TRIES = 5  # tries that opened a (paid) browser before giving up
NOT_WRITTEN = ('No pude terminar de vincular tu WhatsApp, así que lo desvinculé. Vuelve a vincularlo en Confío IA '
               'cuando quieras.')


def _typing_key(grant):
    return f'whatsapp-link:note-entered:{grant}'


def _chain_key(grant):
    return f'whatsapp-link:note-chain:{grant}'


NOTE_DEADLINE = timedelta(hours=2)  # a note still not written by then undoes the link, whatever the chains did


def _note_failed(link_id, grant):
    """Fails closed: the link is undone, never left usable without the note."""
    row = WhatsAppLink.objects.select_related('user').filter(pk=link_id, grant=grant).first()
    if row is not None and note_pending(row) and unlink(row.user, WhatsAppLinkRecord.EndedBy.NOTE, grant=grant,
                                                        only_pending=True):
        logger.error('WhatsApp link %s: the note to its owner could not be confirmed; unlinked', link_id)
        _notify(row.user, NOT_WRITTEN)


def warn_self(link_id, grant, tries=0, opened=0):
    """The one message Confío writes by itself: a note in the owner's own chat that the link happened. A
    person tricked into typing a code sees it in their own WhatsApp.

    Fails closed: nothing is read or sent until it is written (note_pending), and if it cannot be written the
    link is undone. Tried again while nothing could have left; never once Enter may have been pressed (a
    durable marker says so even if the worker died), so it never arrives twice."""
    from . import tasks
    try:
        cache.set(_chain_key(grant), 1, 300)  # a live chain: the sweep leaves it alone
    except Exception:  # noqa: BLE001
        pass

    def later(browser=False):
        if tries < WARN_TRIES and opened + int(browser) < OPENED_TRIES:
            try:
                cache.set(_chain_key(grant), 1, 600)  # still alive while it waits: no second chain from the sweep
            except Exception:  # noqa: BLE001
                pass
            tasks.warn_self.apply_async((link_id, grant, tries + 1, opened + int(browser)), countdown=60)
            return
        _note_failed(link_id, grant)

    def written(link):
        _mine(link).update(sealed_phone='')  # the number is not kept past this

    with _slot() as placed:
        if not placed:
            later()
            return
        with _taken(link_id, grant) as link:
            if link is None:
                if WhatsAppLink.objects.filter(pk=link_id, grant=grant).exists():
                    later()
                return
            digits = _unseal(link.sealed_phone, '')
            if link.state != WhatsAppLink.State.LINKED or link.reason == 'unlinking' or not digits:
                return
            if cache.get(_typing_key(grant)):
                # Enter may have been pressed by a worker that died, unconfirmed: never typed again, and never
                # usable unconfirmed either. Undone; linking again writes a new note.
                _note_failed(link_id, grant)
                return

            def about_to_enter():
                # Durable before Enter: whatever happens next, it is never typed again.
                cache.set(_typing_key(grant), 1, 30 * 86400)
                return True

            progress, browser = {}, False
            try:
                url = _open(link, 180, kind='send')
            except browsers.BrowserUnavailable:
                later()  # no browser free: nothing was opened or typed
                return
            browser = True
            try:
                with _guarded(url) as page:
                    web.open_chat_by_number(page, digits)
                    sent = web.send_text(page, SELF_NOTE, about_to_enter, progress)
                if sent is True or sent == 'pending':
                    written(link)  # WhatsApp shows it sent, or on its way
                else:
                    _note_failed(link_id, grant)  # Enter pressed, nothing confirmed: undone, never typed again
            except web.WebError as exc:
                logger.warning('WhatsApp link %s: note to self stopped at %s', link.pk, exc.code)
                # One line, so nothing leaves before Enter: a "partial" without it (a dropped connection
                # read as growth) is a refusal, never a written note.
                if progress.get('enter') or cache.get(_typing_key(grant)):
                    _note_failed(link_id, grant)  # after Enter, unconfirmed: undone, never typed again
                else:
                    later(browser)
            except (browsers.BrowserUnavailable, CdpError) as exc:
                logger.warning('WhatsApp link %s: note to self not written (%s)', link.pk, type(exc).__name__)
                if progress.get('enter') or cache.get(_typing_key(grant)):
                    _note_failed(link_id, grant)
                else:
                    later(browser)
            except BaseException:
                # A time limit or anything else: undone once Enter may have been pressed, else tried again.
                if progress.get('enter') or cache.get(_typing_key(grant)):
                    _note_failed(link_id, grant)
                else:
                    later(browser)
                raise
            finally:
                _close(link)


def _end_record(user_id, ended_by, now=None):
    WhatsAppLinkRecord.objects.filter(user_id=user_id, ended_at__isnull=True).update(
        ended_at=now or timezone.now(), ended_by=ended_by)


def _signed_in(page) -> str:
    try:
        return web.signed_in_number(page)
    except CdpError:
        return ''


def _fail(link, reason):
    """The pairing ended without a link. The profile goes too: a code typed just now could have linked it.
    A link that is already made is never failed (a time limit can land just after it)."""
    if _mine(link).filter(state=WhatsAppLink.State.PAIRING).update(
            state=WhatsAppLink.State.FAILED, reason=reason, sealed_code='', code_at=None, sealed_phone=''):
        _drop_profile(link)
    else:
        _close(link)


# ------------------------------------------------------------------ unlinking

def forget(link_id, tries=0):
    with _slot() as placed:
        if placed:
            return _forget(link_id, tries)
    from . import tasks
    if tries < 4:
        # A place usually frees within a minute: try for the logout a few times first.
        if WhatsAppLink.objects.filter(pk=link_id, reason='unlinking').exists():
            tasks.forget.apply_async((link_id, tries + 1), countdown=15)
        return
    # Still no place: no logout, and the vendor delete goes to the task that retries it (analytics
    # worker). The phone drops the device later on its own.
    with _taken(link_id, seconds=timedelta(minutes=1)) as row:
        if row is None:
            if WhatsAppLink.objects.filter(pk=link_id, reason='unlinking').exists():
                tasks.forget.apply_async((link_id, tries + 1), countdown=15)
            return
        if row.reason != 'unlinking':
            return
        if row.context_id:
            tasks.drop_profile.delay(row.provider, row.context_id, row.session_id)
            WhatsAppLink.objects.filter(pk=row.pk, reason='unlinking').update(context_id='', session_id='')
        WhatsAppLink.objects.filter(pk=row.pk, reason='unlinking').delete()


def _forget(link_id, tries):
    """Log the browser out of WhatsApp (the device leaves the person's list), then delete the profile and the row."""
    with _taken(link_id, seconds=timedelta(minutes=3)) as link:
        if link is None:
            if tries < 25 and WhatsAppLink.objects.filter(pk=link_id, reason='unlinking').exists():
                from . import tasks
                tasks.forget.apply_async((link_id, tries + 1), countdown=15)  # a read or pairing lets go soon
            return
        if link.reason != 'unlinking':
            return
        if link.context_id and link.state == WhatsAppLink.State.LINKED:
            # Tried once: a retry only deletes, it never opens another paid browser.
            WhatsAppLink.objects.filter(pk=link.pk).update(state=WhatsAppLink.State.GONE)
            try:
                # Within the shared slots like everything else; with none free, the logout is skipped (below).
                with _guarded(_open(link, 120, kind='send')) as page:
                    page.goto(web.HOME)
                    if web.wait_for(page, ('chats', 'login'), 45) == 'chats':
                        web.log_out(page)
            except (web.WebError, CdpError, browsers.BrowserUnavailable) as exc:
                # Deleting the profile still ends it here; the phone drops the device later on its own.
                logger.info('WhatsApp link %s: logout skipped (%s)', link.pk, type(exc).__name__)
            finally:
                _close(link)
        if _drop_profile(link):
            WhatsAppLink.objects.filter(pk=link.pk, reason='unlinking').delete()
        else:
            key = f'whatsapp-link:forget-fails:{link.pk}'
            cache.add(key, 0, 7 * 86400)
            if cache.incr(key) >= 20:
                # The person must be able to link again: the profile goes to the task that retries it for a day.
                logger.error('WhatsApp link %s: unlinked but its vendor profile still not deleted', link.pk)
                from . import tasks
                tasks.drop_profile.delay(link.provider, link.context_id, '')
                WhatsAppLink.objects.filter(pk=link.pk, reason='unlinking').update(context_id='')
                WhatsAppLink.objects.filter(pk=link.pk, reason='unlinking').delete()


# ------------------------------------------------------------------ reading (browser worker)

def due_ids():
    now = timezone.now()
    return list(WhatsAppLink.objects.filter(state=WhatsAppLink.State.LINKED, next_sync_at__lte=now,
                                            consent_version__gte=CONSENT_VERSION)
                .exclude(reason='unlinking').exclude(lease_until__gt=now)
                .order_by('next_sync_at').values_list('pk', flat=True)[:conf.get('WHATSAPP_LINK_SYNCS_PER_SWEEP')])


def _queue_sync(link_id):
    """Once per link until it runs or expires: the sweep must not stack reads behind purchases."""
    if cache.add(f'whatsapp-link:queued:{link_id}', 1, 240):
        from . import tasks
        tasks.sync.apply_async((link_id,), expires=240)


def sync(link_id):
    read = False
    try:
        read = _sync(link_id)
    finally:
        if read and enabled():
            # One read at a time fits the plan: when one ends, the next due one starts, not the next sweep.
            for due in due_ids()[:1]:
                if due != link_id:
                    _queue_sync(due)


def _sync(link_id):
    cache.delete(f'whatsapp-link:queued:{link_id}')
    if not enabled():
        return
    with _slot() as placed:
        if placed:
            return _sync_placed(link_id)
    # No place now: later, with a little spread so waiting reads do not all come back together.
    import random
    WhatsAppLink.objects.filter(pk=link_id, state=WhatsAppLink.State.LINKED, next_sync_at__lte=timezone.now()).update(
        next_sync_at=timezone.now() + timedelta(minutes=10, seconds=random.randint(0, 300)))
    return False


def _sync_placed(link_id):
    now = timezone.now()
    interval = timedelta(minutes=conf.get('WHATSAPP_LINK_SYNC_MINUTES'))
    with _taken(link_id) as link:
        if link is None:
            return  # a send or another read holds it: it stays due for the next sweep
        if link.state != WhatsAppLink.State.LINKED or link.reason == 'unlinking' or not link.next_sync_at \
                or link.next_sync_at > now:
            return
        if link.consent_version < CONSENT_VERSION:
            _mine(link).update(next_sync_at=None)  # until they accept today's text (accept_consent)
            return
        if note_pending(link):
            _mine(link).update(next_sync_at=now + timedelta(minutes=5))  # nothing is read before the note is written
            return
        _mine(link).update(next_sync_at=now + interval)
        try:
            rows = _read(link)
        except web.WebError as exc:
            if exc.code != 'gone':
                _backoff(link, now, interval)
            else:
                first = _gone_seen(link)
                if first is None:
                    # Once is not proof (a profile can open stale right after the last browser closed): look again.
                    cache.set(_gone_key(link), now.timestamp(), 6 * 3600)
                    _mine(link).update(next_sync_at=now + GONE_CONFIRM)
                elif now.timestamp() - first >= GONE_CONFIRM.total_seconds():
                    _gone(link)  # a second read, minutes apart, saw it logged out too
                else:
                    _mine(link).update(next_sync_at=now + GONE_CONFIRM)
            return
        except (browsers.BrowserUnavailable, CdpError) as exc:
            if getattr(exc, 'code', '') == 'busy':
                import random
                # Others are reading: soon, no blame, spread so the waiting ones do not return together.
                _mine(link).update(next_sync_at=now + timedelta(minutes=10, seconds=random.randint(0, 300)))
                return False
            logger.warning('WhatsApp sync %s failed: %s', link.pk, type(exc).__name__)
            _backoff(link, now, interval)
            return
        finally:
            _close(link)
        try:
            found = _store(link, rows)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - by type: a message can quote a chat
            logger.warning('WhatsApp classify %s failed: %s', link.pk, type(exc).__name__)
            _backoff(link, now, interval)
            return
        _mine(link).update(last_sync_at=now, failures=0)
    if found and _mine(link).filter(state=WhatsAppLink.State.LINKED).exclude(reason='unlinking').exists():
        noun = 'mensaje importante' if found == 1 else 'mensajes importantes'
        _notify(link.user, f'Tienes {found if found < 10 else "más de 9"} {noun} en WhatsApp. Míralos en Confío IA.')
    return True


GONE_CONFIRM = timedelta(minutes=10)


def _gone_key(link):
    return f'whatsapp-link:gone-seen:{link.pk}:{link.grant}'


def _gone_seen(link):
    """When a read first saw this link logged out, as a timestamp, or None."""
    value = cache.get(_gone_key(link))
    return float(value) if isinstance(value, (int, float)) else None


def _read(link):
    with _guarded(_open(link, conf.get('WHATSAPP_LINK_SYNC_SECONDS'), kind='background')) as page:
        for attempt in range(2):
            page.goto(web.HOME)
            seen = web.wait_for(page, ('chats', 'login', 'phone', 'code'), 60)
            if seen == 'chats':
                cache.delete(_gone_key(link))  # signed in: an earlier logged-out sighting was not real
                page.pump(4.0)  # what arrived while it was closed lands in the list
                return web.unread_chats(page)
            if seen not in ('login', 'phone', 'code'):
                raise web.WebError(f'screen_{seen}')
        # Seen twice, a load apart: the device was logged out.
        raise web.WebError('gone')


def _backoff(link, now, interval):
    wait = min(interval * 2 ** min(link.failures, 4), MAX_BACKOFF)
    _mine(link).update(failures=min(link.failures + 1, 100), next_sync_at=now + wait)


def _gone(link):
    """Unlinked from the phone (or WhatsApp logged the device out): the profile is worth nothing now."""
    if not _mine(link).filter(state=WhatsAppLink.State.LINKED).update(
            state=WhatsAppLink.State.GONE, reason='gone', next_sync_at=None, sealed_phone=''):
        return
    link.notices.all().delete()
    link.drafts.exclude(status=WhatsAppDraft.Status.SENDING).delete()
    _end_record(link.user_id, WhatsAppLinkRecord.EndedBy.PHONE)
    _drop_profile(link)
    _notify(link.user, GONE)


def private(row) -> bool:
    """A login code, a password or a bank token: never stored, never shown to a model."""
    text = f"{row.get('name', '')} {row.get('preview', '')}"
    if not SECURITY.search(text):
        return False
    return bool(DIGITS.search(re.sub(r'[\s\-.]', '', text)))


def _store(link, rows) -> int:
    """Classifies what is new and keeps only the important. Returns how many are new."""
    fresh = []
    for row in rows:
        if row['group'] or private(row) or not row['preview']:
            continue
        key = _key(str(link.user_id), str(link.grant), row['name'], row['preview'])
        if WhatsAppNotice.objects.filter(link=link, source_key=key).exists() or cache.get(f'whatsapp-link:seen:{key}'):
            continue
        fresh.append((key, row))
    if not fresh:
        return 0
    verdicts = classify.important([{'chat': row['name'], 'preview': row['preview']} for _key_, row in fresh])
    found = 0
    with transaction.atomic():
        if _mine(link).select_for_update().filter(state=WhatsAppLink.State.LINKED).first() is None:
            return 0  # unlinked meanwhile: write nothing
        for (key, row), verdict in zip(fresh, verdicts):
            cache.set(f'whatsapp-link:seen:{key}', 1, 3 * 86400)
            if not verdict:
                continue
            _notice, made = WhatsAppNotice.objects.get_or_create(link=link, source_key=key, defaults={
                'kind': verdict['kind'], 'notified_at': timezone.now(),
                'sealed': _seal({'chat': row['name'], 'preview': row['preview'], 'summary': verdict['summary'],
                                 'time': row['time']})})
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
    """A draft for one chat (its exact name) or one number. Written by the person, or by the model from their words."""
    link = _linked_of(user)
    if notice_id:
        notice = link.notices.filter(pk=notice_id).first() if str(notice_id).isdigit() else None
        if notice is None:
            raise LinkRefused('not_found')
        chat = _unseal(notice.sealed, {}).get('chat')
    chat = str(chat or '').strip()[:web.MAX_NAME]
    if phone and not str(phone).strip().startswith('+'):
        # 4141234567 is a Venezuelan number to the person and a Swiss one to WhatsApp: the + is required.
        raise LinkRefused('phone')
    digits = phone_digits(phone) if phone else ''
    if bool(chat) == bool(digits):
        raise LinkRefused('chat')
    if instructions:
        _claim(user, 'write', LIMITS['write'])
        body = classify.write(str(instructions)[:1000], chat or 'un número nuevo')
    fields = {'chat': chat, 'phone': digits, 'body': _body(body)}
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
    with _slot() as placed:
        if placed:
            return _send(draft_id, tries)
    # No place now: the approved message waits its turn; nothing was typed.
    draft = WhatsAppDraft.objects.filter(pk=draft_id, status=WhatsAppDraft.Status.SENDING).first()
    if draft is None:
        return
    WhatsAppDraft.objects.filter(pk=draft.pk, status=WhatsAppDraft.Status.SENDING).update(sending_at=timezone.now())
    if tries < SEND_BUSY_TRIES:
        from . import tasks
        tasks.send.apply_async((draft_id, tries + 1), countdown=20)
    else:
        _sent(draft, WhatsAppDraft.Status.DRAFT, 'browser')


def _send(draft_id, tries):
    from . import tasks
    draft = WhatsAppDraft.objects.filter(pk=draft_id, status=WhatsAppDraft.Status.SENDING).first()
    if draft is None:
        return
    with _taken(draft.link_id) as link:
        if link is None:
            if tries < SEND_BUSY_TRIES:
                tasks.send.apply_async((draft_id, tries + 1), countdown=20)  # a read holds the browser: wait for it
            else:
                _sent(draft, WhatsAppDraft.Status.DRAFT, 'browser')
            return
        # The clock for "silent too long" starts now that a worker holds the browser.
        WhatsAppDraft.objects.filter(pk=draft.pk, status=WhatsAppDraft.Status.SENDING).update(sending_at=timezone.now())
        fields = _unseal(draft.sealed, {})
        typed = busy = False
        progress = {}

        def still_wanted():
            # Unlinked or deleted since the tap: Enter is not pressed.
            current = _mine(link).filter(state=WhatsAppLink.State.LINKED).exclude(reason='unlinking').first()
            return (WhatsAppDraft.objects.filter(pk=draft.pk, status=WhatsAppDraft.Status.SENDING).exists()
                    and current is not None)

        try:
            if not enabled() or not fields.get('body') or not (fields.get('chat') or fields.get('phone')):
                _sent(draft, WhatsAppDraft.Status.DRAFT, 'whatsapp')  # nothing typed: it can be tried again
                return
            if link.state != WhatsAppLink.State.LINKED or link.reason == 'unlinking':
                _sent(draft, WhatsAppDraft.Status.DRAFT, 'gone')
                return
            with _guarded(_open(link, 260, kind='send')) as page:  # a long text is typed at a person's pace
                if fields.get('phone'):
                    web.open_chat_by_number(page, fields['phone'])
                else:
                    page.goto(web.HOME)
                    seen = web.wait_for(page, ('chats', 'login', 'phone', 'code'), 60)
                    if seen != 'chats':
                        raise web.WebError('whatsapp')
                    web.open_chat_by_name(page, fields['chat'])
                typed = True
                delivered = web.send_text(page, fields['body'], still_wanted, progress)
            if delivered == 'pending':
                _sent(draft, WhatsAppDraft.Status.UNKNOWN, 'pending')
            else:
                _sent(draft, WhatsAppDraft.Status.SENT if delivered else WhatsAppDraft.Status.UNKNOWN,
                      '' if delivered else 'unknown')
        except web.WebError as exc:
            # Refused before Enter: nothing left. After it: unknown, never sent again.
            unsure = typed and exc.code not in web.BEFORE_ENTER
            reason = (exc.code if exc.code == 'partial_sent' else 'unknown') if unsure else exc.code
            _sent(draft, WhatsAppDraft.Status.UNKNOWN if unsure else WhatsAppDraft.Status.DRAFT,
                  reason if reason in REASONS else 'whatsapp')
        except DatabaseError:
            # Before Enter nothing left; after it, unknown. Never left in "sending".
            entered = progress.get('enter')
            _sent(draft, WhatsAppDraft.Status.UNKNOWN if entered else WhatsAppDraft.Status.DRAFT,
                  'unknown' if entered else 'browser')
        except (browsers.BrowserUnavailable, CdpError) as exc:
            if getattr(exc, 'code', '') == 'busy' and not typed and tries < SEND_BUSY_TRIES:
                busy = True  # every browser is in use: the approved send waits its turn
                return
            # Before Enter nothing left (a line that did go out is partial_sent, a WebError).
            entered = progress.get('enter')
            _sent(draft, WhatsAppDraft.Status.UNKNOWN if entered else WhatsAppDraft.Status.DRAFT,
                  'unknown' if entered else 'browser')
        except SoftTimeLimitExceeded:
            # Before Enter nothing left (the box was cleared on the way out): it can be sent again.
            entered = progress.get('enter')
            _sent(draft, WhatsAppDraft.Status.UNKNOWN if entered else WhatsAppDraft.Status.DRAFT,
                  'unknown' if entered else 'whatsapp')
            raise
        finally:
            _close(link)
            if busy:
                tasks.send.apply_async((draft_id, tries + 1), countdown=20)


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
    """Erases what must not stay, then queues reads and the vendor cleanup. Only the database here:
    every Browserbase call runs on the browser queue (sweep_vendor)."""
    from . import tasks
    now = timezone.now()
    # A send that never reported back: unknown, so it is never sent twice.
    WhatsAppDraft.objects.filter(status=WhatsAppDraft.Status.SENDING, sending_at__lt=now - SENDING_STUCK).update(
        status=WhatsAppDraft.Status.UNKNOWN, reason='unknown', sealed=_seal({}), expires_at=now + timedelta(hours=1))
    if conf.get('WHATSAPP_LINK_KEEP_DAYS'):
        WhatsAppNotice.objects.filter(created_at__lt=now - timedelta(days=conf.get('WHATSAPP_LINK_KEEP_DAYS'))).delete()
    WhatsAppDraft.objects.filter(expires_at__lte=now).exclude(status=WhatsAppDraft.Status.SENDING).delete()
    for link in _leavers()[:20]:
        try:
            unlink(link.user, WhatsAppLinkRecord.EndedBy.ACCOUNT)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - one row must not stop the others
            logger.warning('WhatsApp link %s: unlink of a leaver failed: %s', link.pk, type(exc).__name__)
    for link_id in WhatsAppLink.objects.filter(reason='unlinking', updated_at__lt=now - timedelta(minutes=5)).exclude(
            lease_until__gt=now).values_list('pk', flat=True)[:20]:
        tasks.forget.delay(link_id)
    # A note to the owner whose chain was lost (a worker restart): started again, or done if Enter may have gone.
    # Past the deadline, whatever happened, the link is undone: never usable without the note.
    for link_id, grant, linked_at in WhatsAppLink.objects.filter(state=WhatsAppLink.State.LINKED).exclude(
            sealed_phone='').exclude(reason='unlinking').exclude(lease_until__gt=now).values_list(
            'pk', 'grant', 'linked_at')[:20]:
        if linked_at and linked_at < now - NOTE_DEADLINE:
            _note_failed(link_id, grant)
        elif not cache.get(_chain_key(grant)):
            tasks.warn_self.apply_async((link_id, str(grant)), countdown=1)
    if enabled():
        for link_id in due_ids():
            _queue_sync(link_id)
    if cache.add('whatsapp-link:sweep-vendor', 1, 240):
        tasks.sweep_vendor.apply_async(expires=240)


VENDOR_SECONDS = 50  # on the shared analytics worker: short


def sweep_vendor():
    """Browserbase work of the sweep, on the browser queue, within a time budget. Each row under its lease."""
    from . import tasks
    started, now = timezone.now(), timezone.now()
    budget = lambda: timezone.now() < started + timedelta(seconds=VENDOR_SECONDS)  # noqa: E731
    late = now - timedelta(seconds=conf.get('WHATSAPP_LINK_PAIRING_SECONDS') + 300)
    # Over when its browser is (the code dies with it), or long after a start that never opened one.
    over = Q(session_expires_at__lt=now) | Q(session_expires_at__isnull=True, updated_at__lt=late)
    for link_id in WhatsAppLink.objects.filter(over, state=WhatsAppLink.State.PAIRING).exclude(
            reason='unlinking').values_list('pk', flat=True)[:10]:
        if not budget():
            break
        with _taken(link_id) as link:
            if link is not None and link.state == WhatsAppLink.State.PAIRING and link.reason != 'unlinking':
                _fail(link, 'timeout')
    # A pairing whose watch was lost (a worker restart): its browser is open, nobody looks at it.
    for link_id, grant in WhatsAppLink.objects.filter(
            state=WhatsAppLink.State.PAIRING, session_expires_at__gt=now, code_at__isnull=False).exclude(
            session_id='').exclude(lease_until__gt=now).exclude(reason='unlinking').values_list('pk', 'grant')[:10]:
        if enabled() and cache.add(f'whatsapp-link:watch-requeued:{grant}', 1, 120):
            tasks.watch.apply_async((link_id, str(grant)), countdown=1)
    # A pairing whose first task was lost: no browser and no code a minute after the tap.
    for link_id, grant in WhatsAppLink.objects.filter(
            state=WhatsAppLink.State.PAIRING, session_expires_at__isnull=True, code_at__isnull=True,
            updated_at__lt=now - timedelta(minutes=1)).exclude(lease_until__gt=now).exclude(
            reason='unlinking').values_list('pk', 'grant')[:10]:
        if enabled() and not cache.get(f'whatsapp-link:pair-started:{grant}') \
                and cache.add(f'whatsapp-link:pair-requeued:{grant}', 1, 600):
            tasks.pair.apply_async((link_id, str(grant)), countdown=1)
    # A profile whose delete failed after a failed pairing or a phone-side unlink: a session may live in it.
    for link_id in WhatsAppLink.objects.filter(state__in=(WhatsAppLink.State.FAILED, WhatsAppLink.State.GONE)).exclude(
            context_id='').exclude(reason='unlinking').order_by('?').values_list('pk', flat=True)[:50]:
        if not budget():
            return
        context = WhatsAppLink.objects.filter(pk=link_id).values_list('context_id', flat=True).first() or ''
        tried = f'whatsapp-link:profile-tries:{context}'
        if (cache.get(tried) or 0) >= 20:
            continue  # reported once below; never blocks the rows behind it
        cache.set(tried, (cache.get(tried) or 0) + 1, 7 * 86400)
        if cache.get(tried) == 20:
            logger.error('WhatsApp link %s: vendor profile could not be deleted after 20 tries', link_id)
        with _taken(link_id) as link:
            # Re-read under the lease: a new pairing may be using this profile now.
            if link is None or link.state not in (WhatsAppLink.State.FAILED, WhatsAppLink.State.GONE) \
                    or link.reason == 'unlinking' or not link.context_id:
                continue
            try:
                _drop_profile(link)
            except SoftTimeLimitExceeded:
                raise
            except Exception as exc:  # noqa: BLE001 - one row must not stop the others
                logger.warning('WhatsApp link %s: profile retry failed: %s', link.pk, type(exc).__name__)


def profile_orphaned(provider_name, context_id, session_id=''):
    """A link row deleted another way (the person's account erased): its browser closes and its profile goes.
    Raises BrowserUnavailable so the task retries."""
    provider = browsers.provider(provider_name or None)
    if session_id:
        try:
            provider.close(session_id)
        except browsers.BrowserUnavailable:
            pass  # its own timeout ends it; the delete below is what matters
    provider.delete_profile(context_id)
