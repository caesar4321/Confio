"""Gmail in the Confío IA conversation, as WhatsApp is (whatsapp_link/chat.py): the assistant tells the person
about mail that needs them, offers to reply, and puts the mail it writes on a card sent with a tap.

Everything posted here is written by code. A sender's name and subject are third parties' words: they reach the
conversation only inside «», cleaned of links, addresses and numbers, and are marked as data when the thread is
replayed to the model (engine GMAIL_PREFIX). A mail leaves only from the card (compose.send, with the hash of
exactly what the card showed).

Chips are actions of types the app knows from this build on; older builds skip them:
- {'type': 'mail_reply', 'target': <need id>, 'label': 'Responder…'}: she says what to answer, the card follows.
- {'type': 'mail_draft', 'target': <draft id>, 'label': 'Enviar por Gmail'}: the card itself.
"""
import logging
import re
from datetime import timedelta
from email.utils import getaddresses

from django.core import signing
from django.db import models, transaction
from django.utils import timezone

from . import compose, config, crypto, text
from .errors import MailRefused
from .models import GmailConnection, MailDraft, MailNeed

logger = logging.getLogger(__name__)

# Only fresh mail is told: the first read goes back 30 days, and an old letter is not a conversation.
FRESH_DAYS = 2
PER_DAY = 6

KIND_WORDS = {
    'payment': 'Parece un pago pendiente.',
    'ticket': 'Parece un pasaje o una entrada.',
    'trip': 'Parece sobre un viaje.',
    'deadline': 'Parece un vencimiento.',
    'reply': 'Parece que espera tu respuesta.',
    'appointment': 'Parece una cita o una reunión.',
    'delivery': 'Parece sobre una entrega.',
    'money': 'Parece dinero que recibes o te deben.',
}


def sender_name(mail) -> str:
    """The name a sender chose, cleaned like any third party's words. Never their address."""
    try:
        name = getaddresses([str(mail.headers.get('from', ''))[:400]])[0][0]
    except Exception:  # noqa: BLE001
        name = ''
    name = text.strict_line(name, 40)
    name = re.sub(r'conf[ií]o', '', name, flags=re.I)  # never posing as us; a real "Google Cloud" keeps its name
    name = ' '.join(name.replace('«', '').replace('»', '').split())
    if not name:
        found = text.addresses(mail.headers.get('from'))
        domain = found[0].rsplit('@', 1)[-1].split('.')[0] if len(found) == 1 else ''
        name = text.strict_line(domain.capitalize(), 30)
    return name or 'Alguien'


def _unquoted(value) -> str:
    """A third party's words go between «»: they must not be able to close them early."""
    return ' '.join(str(value or '').replace('«', '"').replace('»', '"').split())


# A notice as soon as something important arrives, not once a day: at most one an hour, in the person's daytime.
PUSH_GAP = timedelta(hours=1)
DAYTIME = range(7, 22)
PUSH_WORDS = {
    'payment': 'un pago pendiente', 'ticket': 'un pasaje o una entrada', 'trip': 'algo de un viaje',
    'deadline': 'un vencimiento', 'reply': 'alguien que espera tu respuesta', 'appointment': 'una cita',
    'delivery': 'una entrega', 'money': 'dinero que recibes',
}


def _push(connection, need):
    """Fixed words only: a lock screen never shows who wrote or what. The need counts as noticed."""
    from django.core.cache import cache
    from .oauth import NOTICE_TYPE
    try:
        local = timezone.now() + timedelta(hours=config.utc_offset(connection.user))
        if local.hour not in DAYTIME:
            return  # the morning notice counts it
        if not cache.add(f'gmail-push:{connection.user_id}', 1, int(PUSH_GAP.total_seconds())):
            return  # one went out this hour: what it says is in the conversation
        from notifications.models import NotificationType
        from notifications.utils import create_notification
        words = PUSH_WORDS.get(need.kind, 'algo importante')
        create_notification(user=connection.user, notification_type=NotificationType.SYSTEM, title='Confío IA',
                            message=f'Tu Gmail trae {words}. Te lo cuento en Confío IA.', data={'type': NOTICE_TYPE})
        MailNeed.objects.filter(pk=need.pk).update(notified_at=timezone.now())
    except Exception as exc:  # noqa: BLE001
        logger.warning('Gmail push failed: %s', type(exc).__name__)


def _post(user, body, tag, actions=(), connection=None, extra=None, existing_ok=False):
    """A Confío IA message in the person's own thread (personal account), once per tag.

    With `connection`, only while it still exists under the same grant, checked under its row lock: a disconnect
    (which takes that lock and erases these posts) either sees this post or makes it never be written."""
    from assistant.service import lock_user
    from inbox.models import SupportMessage
    from inbox.schema import get_or_create_support_conversation
    from users.models import Account
    personal = Account.objects.filter(user=user, account_type='personal', account_index=0,
                                      deleted_at__isnull=True).first()
    if personal is None:
        return None
    with transaction.atomic():
        if connection is not None and not GmailConnection.objects.select_for_update().filter(
                pk=connection.pk, grant=connection.grant).exists():
            return None
        lock_user(user)
        conversation = get_or_create_support_conversation(user, personal, None)
        existing = conversation.messages.filter(metadata__notice=tag).first()
        if existing is not None:
            # Already there: for a follow-up, it was posted (by a run cut short after posting); for a notice, it was
            # told before and is not told (or pushed) again.
            return existing if existing_ok or connection is None else None
        message = SupportMessage.objects.create(
            conversation=conversation, sender_type='AGENT', message_type='TEXT', body=body,
            metadata={'ai': True, 'notice': tag, 'gmail': True, 'actions': list(actions), **(extra or {})})
        conversation.last_message_at = message.created_at
        conversation.save(update_fields=['last_message_at', 'updated_at'])
    return message


def _about(from_key, subject) -> str:
    import hashlib
    return hashlib.sha256(f'{from_key or ""}|{subject.casefold()}'.encode()).hexdigest()[:32]


AUTOMATIC_KINDS = ('payment', 'ticket', 'trip', 'deadline', 'delivery', 'money')


def _same_told(user, from_key, subject, kind=None) -> bool:
    """An automatic notice sent again (the same sender and subject): told once. Never a person's new mail in a
    thread (reply, appointment), and never without a known sender."""
    from inbox.models import SupportMessage
    if not from_key or (kind is not None and kind not in AUTOMATIC_KINDS):
        return False
    return SupportMessage.objects.filter(
        conversation__user=user, metadata__gmail=True, metadata__mail_about=_about(from_key, subject),
        created_at__gte=timezone.now() - timedelta(days=FRESH_DAYS)).exists()


def _told_today(user) -> int:
    from inbox.models import SupportMessage
    since = timezone.now() - timedelta(days=1)
    return SupportMessage.objects.filter(conversation__user=user, metadata__gmail=True,
                                         metadata__notice__startswith='gmail-need:', created_at__gte=since).count()


def tell(connection, need, mail):
    """One mail that needs the person, told in the conversation. Never fails the sync."""
    try:
        if not config.chat_consented(connection):
            return  # accepted before mail was told in the conversation: the daily notice only
        if mail.sent_at < timezone.now() - timedelta(days=FRESH_DAYS) or _told_today(connection.user) >= PER_DAY:
            return
        data = crypto.unseal(need.sealed)
        subject = _unquoted(text.strict_line(mail.subject or '', 120, numbers=True)) or 'sin asunto'
        shown = _unquoted(data.get('sender')) or sender_name(mail)
        lines = [f'«{shown}» te escribió a tu Gmail: «{subject}»']
        if data.get('summary'):
            lines.append(f'Según el correo: {_unquoted(data["summary"])}')
        lines.append(KIND_WORDS.get(need.kind, 'Parece importante.'))
        # Drawn as a card by builds that know it (MailNoticeCard); the body stays the text for older ones and the model.
        actions = [{'type': 'mail_notice', 'target': str(need.pk), 'label': need.kind}]
        # Offered only where a person may answer: who waits for a reply, an appointment, or replies the model wrote
        # reading the thread. Never under an automatic notice.
        if connection.can_send and (need.kind in ('reply', 'appointment') or data.get('replies')):
            lines[-1] += ' ¿Le respondo?'
            # Replies the model offered, read in the whole thread: one tap writes that one on a card.
            for reply in (data.get('replies') or [])[:3]:
                actions.append({'type': 'mail_suggested', 'target': str(need.pk), 'label': _unquoted(reply)})
            actions.append({'type': 'mail_reply', 'target': str(need.pk), 'label': 'Otro…' if data.get('replies') else 'Responder…'})
        if _same_told(connection.user, data.get('from_key'), subject, need.kind):
            MailNeed.objects.filter(pk=need.pk).update(notified_at=timezone.now())  # a copy: settled, not re-tried
            return
        if _post(connection.user, '\n'.join(lines), f'gmail-need:{need.pk}', actions, connection=connection,
                 extra={'mail_about': _about(data.get('from_key'), subject)}):
            # Told: what a follow-up names is what was shown here (sender and subject, already cleaned), so a
            # follow-up never reads the mail's text again (gmail.followups).
            MailNeed.objects.filter(pk=need.pk, told_at__isnull=True).update(
                told_at=timezone.now(), sealed=crypto.seal({**data, 'shown_subject': subject,
                                                            'shown_sender': shown, 'thread': mail.thread_id or ''}))
            _push(connection, need)
    except Exception as exc:  # noqa: BLE001 - the need is kept either way; logged by type only
        logger.warning('Gmail need %s not told in the chat: %s', need.pk, type(exc).__name__)


FOLLOW_WORDS = {
    'reply': '«{name}» sigue esperando tu respuesta a «{subject}»',
    'appointment': 'La cita o reunión de «{name}»: «{subject}»',
    'payment': '«{subject}» de «{name}» vence hoy',
    'deadline': '«{subject}» de «{name}» vence hoy',
}


def _follow_line(need):
    """From what was shown when it was told (chat.tell keeps it): the mail is never read again for its words."""
    data = crypto.unseal(need.sealed)
    subject = data.get('shown_subject') or 'sin asunto'
    name = data.get('shown_sender') or _unquoted(data.get('sender')) or 'Alguien'
    return FOLLOW_WORDS.get(need.kind, 'Sigue pendiente «{subject}» de «{name}»').format(name=name, subject=subject)


def follow_up(connection, items):
    """ONE follow-up message for what of hers is still open and due now (gmail.followups): [(need, number)], the
    first with its answer button, each named. Plain text with
    buttons, never the notice card (that card draws the original mail). Tagged like every Gmail post: it goes with
    the connection."""
    first = items[0][0]
    if len(items) == 1:
        need = first
        lines = [('Recordatorio: ' if need.kind in ('payment', 'deadline') else '') + _follow_line(need) + '.']
        summary = crypto.unseal(need.sealed).get('summary')
        if summary:
            lines.append(f'Según el correo: {_unquoted(summary)}')
    else:
        lines = ['Siguen pendientes en tu Gmail:'] + [f'• {_follow_line(need)}.' for need, _number in items]
    actions = []
    if connection.can_send and first.kind in ('reply', 'appointment'):
        if len(items) == 1:
            lines[0] += ' ¿Le respondo?'
        else:
            name = crypto.unseal(first.sealed).get('shown_sender') or 'el primero'
            lines.append(f'¿Le respondo a «{name}»?')
        actions.append({'type': 'mail_reply', 'target': str(first.pk), 'label': 'Responder…'})
    tag = 'gmail-followup:' + ','.join(f'{need.pk}.{number}' for need, number in items)
    return _post(connection.user, '\n'.join(lines), tag[:200], actions, connection=connection, existing_ok=True)


def push_follow_up(connection, count):
    """A follow-up's push: fixed words only (never who wrote or what), read as a reminder, never as a new mail.
    In her daytime and at most one Gmail push an hour, as _push; a need's notified_at (the morning count) is left
    alone."""
    from django.core.cache import cache
    from .oauth import NOTICE_TYPE
    try:
        local = timezone.now() + timedelta(hours=config.utc_offset(connection.user))
        if local.hour not in DAYTIME or not cache.add(f'gmail-push:{connection.user_id}', 1,
                                                       int(PUSH_GAP.total_seconds())):
            return False
        from notifications.models import NotificationType
        from notifications.utils import create_notification
        words = 'Un correo sigue pendiente' if count == 1 else f'{count} correos siguen pendientes'
        create_notification(user=connection.user, notification_type=NotificationType.SYSTEM, title='Pendiente · Gmail',
                            message=f'{words}. Te lo recuerdo en Confío IA.', data={'type': NOTICE_TYPE})
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning('Gmail follow-up push failed: %s', type(exc).__name__)
        return False


CATCH_UP = 3


def catch_up(connection):
    """Recent needs never told (found before the person accepted the conversation, or before this build): told
    now, a few per sync, each read again from Gmail for its subject. Never fails the sync."""
    from inbox.models import SupportMessage
    from . import session
    try:
        since = timezone.now() - timedelta(days=FRESH_DAYS)
        told = {str(tag).split(':', 1)[1] for tag in SupportMessage.objects.filter(
            conversation__user=connection.user, metadata__gmail=True,
            metadata__notice__startswith='gmail-need:').values_list('metadata__notice', flat=True)}
        # A copy that was not told is marked noticed (tell): it never takes a catch-up slot again.
        waiting = [need for need in connection.needs.filter(dismissed=False, created_at__gte=since,
                                                             notified_at__isnull=True).order_by('created_at')
                   if str(need.pk) not in told][:CATCH_UP]
        if not waiting:
            return
        box = session.mailbox(connection)
        for need in waiting:
            mail = text.parse(box.message(crypto.unseal(need.sealed)['id']))
            tell(connection, need, mail)
    except Exception as exc:  # noqa: BLE001 - logged by type only; the next sync tries again
        logger.warning('Gmail catch-up failed: %s', type(exc).__name__)


def _need_by_sender(connection, name):
    """The newest need from the sender the assistant named (as it told it). Only an exact or a unique longer name."""
    wanted = ' '.join(str(name or '').split()).casefold()
    if not wanted:
        return None
    named = []
    for need in connection.needs.order_by('-created_at')[:30]:
        try:
            data = crypto.unseal(need.sealed)
            named.append((need, (data.get('sender') or '').casefold(), data.get('from_key') or data.get('id')))
        except Exception:  # noqa: BLE001
            continue
    exact = [need for need, sender, _key in named if sender == wanted]
    if exact:
        # A name is the sender's choice: two addresses under one name ("Banco") are never guessed between.
        return exact[0] if len({key for need, sender, key in named if sender == wanted}) == 1 else None
    close = {key: need for need, sender, key in named if sender and wanted in sender}
    return next(iter(close.values())) if len(close) == 1 else None


def _handle(connection, need) -> str:
    return signing.dumps({'g': str(connection.grant), 'm': crypto.unseal(need.sealed)['id']}, salt=compose._HANDLE_SALT)


def prepare(user, instructions, *, need_id=None, about=None, to=None):
    """A mail on a card in the conversation: a reply to a need (from its chip, or the sender the assistant named),
    or a new mail to an address the person wrote. Returns the draft as compose.present."""
    from . import service
    connection = service.connection_of(user)
    if connection is None or connection.status != GmailConnection.Status.ACTIVE:
        raise MailRefused('not_connected', 'Conecta tu Gmail primero.')
    if not config.chat_consented(connection):
        raise MailRefused('consent', 'Actualiza la app y acepta lo nuevo de Gmail para escribir correos aquí.')
    if not connection.can_send:
        raise MailRefused('no_send', 'No diste permiso para enviar correos. Reconecta Gmail y márcalo.')
    need = None
    if need_id is not None:
        need = connection.needs.filter(pk=need_id).first() if str(need_id).isdigit() else None
        if need is None:
            raise MailRefused('not_found', 'Ese aviso ya no existe.')
    elif about and not to:
        need = _need_by_sender(connection, about)
        if need is None:
            raise MailRefused('source', 'No encuentro ese correo. Dime a qué dirección escribo.')
    draft = compose.create(connection, instructions, to=None if need else to,
                           source=_handle(connection, need) if need else None)
    if not draft.get('id'):
        raise MailRefused('reconnect', 'Conecta tu Gmail para preparar el correo.')
    asked = _unquoted(text.one_line(instructions, 200))
    intro = (f'Esta es tu respuesta para {draft["to"]} (me pediste: «{asked}»). Revísala y toca Enviar:'
             if draft['is_reply']
             else f'Este es el correo para {draft["to"]} (me pediste: «{asked}»). Revísalo y toca Enviar:')
    target = {'mail_to': draft['to'], 'need': str(need.pk) if need else '', 'reply': bool(draft['is_reply'])}
    try:
        card = _post(user, intro, f'gmail-draft:{draft["id"]}',
                     [{'type': 'mail_draft', 'target': draft['id'], 'label': 'Enviar por Gmail'}],
                     connection=connection, extra=target)
        if card is not None:
            _replace_earlier(user, connection, draft['id'], target)
    except Exception:  # noqa: BLE001
        card = None
    if card is None:
        # No card to send it from: no draft either (nothing may wait unseen).
        MailDraft.objects.filter(pk=draft['id'], status=MailDraft.Status.DRAFT).delete()
        raise MailRefused('unavailable', 'No pude preparar el correo ahora.')
    return draft


# A change she asks for ("más corto") follows the card it changes only this long after it.
CHANGE_WINDOW = timedelta(minutes=30)


def _last_card(user):
    from inbox.models import SupportMessage
    return SupportMessage.objects.filter(
        conversation__user=user, metadata__gmail=True, metadata__notice__startswith='gmail-draft:',
        created_at__gte=timezone.now() - CHANGE_WINDOW).order_by('-pk').first()


def last_recipient(user) -> str:
    """The address of the newest NEW mail's card (one she wrote herself), so a change may keep it. Never a
    reply's: that address came from the mail's sender."""
    card = _last_card(user)
    return (card.metadata.get('mail_to') or '') if card and not card.metadata.get('reply') else ''


def last_need(user):
    """The mail the newest reply card answers, so a change may keep answering it."""
    card = _last_card(user)
    return (card.metadata.get('need') or None) if card and card.metadata.get('reply') else None


def _replace_earlier(user, connection, draft_id, target):
    """A new version of the same mail (same mail answered, or same address) deletes the earlier drafts, so only
    the newest card can be sent. Other mails' cards stay."""
    from inbox.models import SupportMessage
    same = {'metadata__need': target['need']} if target['need'] else {'metadata__mail_to': target['mail_to'],
                                                                      'metadata__reply': False}
    earlier = [action.get('target') for card in SupportMessage.objects.filter(
        conversation__user=user, metadata__gmail=True, metadata__notice__startswith='gmail-draft:', **same)
        for action in card.metadata.get('actions') or [] if action.get('type') == 'mail_draft']
    MailDraft.objects.filter(connection=connection, status=MailDraft.Status.DRAFT,
                             pk__in=[pk for pk in earlier if pk and pk != draft_id]).delete()


def sent(user, draft_id):
    """After a send that went through: the assistant says so, once."""
    try:
        from . import service
        _post(user, 'Listo, lo envié desde tu Gmail.', f'gmail-sent:{draft_id}', connection=service.connection_of(user))
    except Exception as exc:  # noqa: BLE001 - the card shows it either way
        logger.warning('Gmail send outcome not posted: %s', type(exc).__name__)


READ_ERASED = 'Borré esta respuesta porque hablaba de tu Gmail o tu calendario y lo desconectaste.'


def erase(user_id):
    """Everything Gmail the assistant said in the person's conversation, its answers about her mail and calendar
    too: gone with the connection."""
    from inbox.models import SupportMessage
    try:
        with transaction.atomic():
            SupportMessage.objects.filter(conversation__user_id=user_id, metadata__gmail=True).delete()
            # An answer that told her what her mail or calendar said (assistant.service tags it): its words go, as
            # WhatsApp's (whatsapp_link.chat.erase). The line stays, so the thread and the turn that points at it
            # keep their shape.
            # A card that came in the same reply (a payment she asked for in her own words) keeps its own marks.
            told = SupportMessage.objects.filter(conversation__user_id=user_id).filter(
                models.Q(metadata__gmail_read=True) | models.Q(metadata__gmail_follow=True))
            for message in told.only('pk', 'metadata'):
                kept = {key: value for key, value in (message.metadata or {}).items()
                        if key not in ('gmail_read', 'gmail_follow', 'actions')}
                SupportMessage.objects.filter(pk=message.pk).update(
                    body=READ_ERASED, metadata={**kept, 'ai': True, 'actions': [], 'gmail_erased': True})
    except Exception as exc:  # noqa: BLE001 - logged by type only
        logger.error('Gmail chat posts not erased: %s', type(exc).__name__)
