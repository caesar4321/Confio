"""WhatsApp in the Confío IA conversation: the assistant tells the person what arrived, offers replies, and puts
the one they choose on a card they send with a tap. It then says how it went.

Everything here is written by code, never by the chat model: the person's WhatsApp messages are third parties'
words, so they reach the conversation only inside a fixed sentence, and a reply leaves only from the card
(service.send_draft, with the hash of exactly what the card showed).

Chips are actions of types the app knows from this build on; older builds skip them (they only draw
navigate/card actions):
- {'type': 'whatsapp_reply', 'target': <notice id>, 'label': <the reply>}: tapping it prepares that reply.
- {'type': 'whatsapp_draft', 'target': <draft id>, 'label': 'Enviar por WhatsApp'}: the card itself.
"""
import logging
import re

from django.db import transaction
from django.utils import timezone

from . import service
from .models import WhatsAppDraft, WhatsAppNotice

logger = logging.getLogger(__name__)

KIND_WORDS = {
    'payment': 'Parece un cobro o un pago.',
    'order': 'Parece sobre un pedido.',
    'delivery': 'Parece sobre una entrega.',
    'appointment': 'Parece sobre una cita.',
    'reply': 'Parece que espera tu respuesta.',
    'urgent': 'Parece urgente.',
}


def _post(user, body, tag, actions=()):
    """A Confío IA message in the person's own thread (their personal account), once per tag."""
    from assistant.service import lock_user
    from inbox.models import SupportMessage
    from inbox.schema import get_or_create_support_conversation
    from users.models import Account
    personal = Account.objects.filter(user=user, account_type='personal', account_index=0,
                                      deleted_at__isnull=True).first()
    if personal is None:
        return None
    with transaction.atomic():
        lock_user(user)
        conversation = get_or_create_support_conversation(user, personal, None)
        existing = conversation.messages.filter(metadata__notice=tag).first()
        if existing is not None:
            return existing
        message = SupportMessage.objects.create(
            conversation=conversation, sender_type='AGENT', message_type='TEXT', body=body,
            metadata={'ai': True, 'notice': tag, 'whatsapp': True, 'actions': list(actions)})
        conversation.last_message_at = message.created_at
        conversation.save(update_fields=['last_message_at', 'updated_at'])
    return message


def _quote(text, limit=220):
    """A third party's words for the «» quote: one line, and never a « or » that would close it early."""
    text = ' '.join(str(text or '').replace('«', '"').replace('»', '"').split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def _name(value):
    """The chat's name (a sender can choose it): quoted like their words, never posing as Confío or WhatsApp."""
    name = ' '.join(str(value or '').replace('«', '').replace('»', '').split())
    name = re.sub(r'conf[ií]o|whats\s*app', '', name, flags=re.I)
    name = ' '.join(name.split())[:40]
    return name or 'Alguien'


def tell(link, notice, replies):
    """The assistant tells the person about one important message, with replies to choose from."""
    data = service._unseal(notice.sealed, {})
    # A chat that keeps writing is one thread: "siguió escribiendo", answered with what it says now.
    earlier = any(service._unseal(other.sealed, {}).get('jid') == data.get('jid') for other in WhatsAppNotice.objects.filter(
        link=link, created_at__gte=service._context_since()).exclude(pk=notice.pk).order_by('-created_at')[:20])
    verb = 'siguió escribiendo' if earlier else 'te escribió'
    lines = [f'«{_name(data.get("chat"))}» {verb} por WhatsApp:', f'«{_quote(data.get("preview"))}»']
    lines.append(KIND_WORDS.get(notice.kind, 'Parece importante.') + ' ¿Qué le respondo?')
    # The notice drawn as a card on builds that know it (sender, the message as a chat bubble, what it seems);
    # the body above stays for older builds and for the assistant's own reading of the conversation.
    actions = [{'type': 'whatsapp_notice', 'target': str(notice.pk), 'label': 'siguió' if earlier else ''}]
    actions += [{'type': 'whatsapp_reply', 'target': str(notice.pk), 'label': reply} for reply in replies[:3]]
    # Always a way to say it in her own words: the assistant writes the full reply, on a card she confirms.
    actions.append({'type': 'whatsapp_other', 'target': str(notice.pk), 'label': 'Otro…'})
    try:
        if _post(link.user, '\n'.join(lines), f'whatsapp-notice:{notice.pk}', actions) is not None:
            WhatsAppNotice.objects.filter(pk=notice.pk, told_at__isnull=True).update(told_at=timezone.now())
    except Exception as exc:  # noqa: BLE001 - the notice is kept either way (the WhatsApp screen shows it)
        logger.warning('WhatsApp notice %s not posted to the chat: %s', notice.pk, type(exc).__name__)


FOLLOW_WORDS = {
    'reply': '«{name}» sigue esperando tu respuesta',
    'appointment': 'La cita que te escribió «{name}»',
    'payment': 'El cobro o pago que te escribió «{name}»',
    'urgent': 'Lo que te escribió «{name}»',
}


def follow_up(link, items, now, zone):
    """ONE follow-up message for everything of hers still open and due now (whatsapp_link.followups): [(notice,
    number)], each named. Plain text with an answer button for the first, never the notice
    card (that card draws the original message and hides this text). Tagged like every WhatsApp post: it goes with
    the link."""
    from assistant.gmail.followups import when_words

    def line(notice):
        data = service._unseal(notice.sealed, {})
        lead = FOLLOW_WORDS.get(notice.kind, 'Lo que te escribió «{name}»').format(name=_name(data.get('chat')))
        return lead, f'«{_quote(data.get("preview"), 160)}»', when_words(notice.created_at, now, zone)

    first = items[0][0]
    if len(items) == 1:
        lead, quote, when = line(first)
        lines = [f'{lead} (te escribió {when}):', quote, '¿Qué le respondo?']
    else:
        lines = ['Siguen pendientes en tu WhatsApp:']
        for notice, _number in items:
            lead, quote, when = line(notice)
            lines.append(f'• {lead} ({when}): {quote}')
        lines.append(f'¿Qué le respondo a «{_name(service._unseal(first.sealed, {}).get("chat"))}»?')
    actions = [{'type': 'whatsapp_other', 'target': str(first.pk), 'label': 'Otro…'}]
    tag = 'whatsapp-followup:' + ','.join(f'{notice.pk}.{number}' for notice, number in items)
    return _post(link.user, '\n'.join(lines), tag[:200], actions)


def prepare(user, text=None, *, notice_id=None, chat=None, phone=None, instructions=None):
    """A reply on a card in the conversation: from a chip (notice_id + its text), from "Otro" (notice_id + what she
    wants to say: the assistant writes the full reply), or from the chat model's tool (the chat's name as the
    assistant wrote it, or a number). Returns the draft as service.present."""
    if notice_id is None and chat and not phone:
        notice = _notice_by_chat(user, chat)
        if notice is None:
            raise service.LinkRefused('chat')
        notice_id = notice.pk
    draft = service.create_draft(user, notice_id=notice_id, phone=phone, body=text, instructions=instructions)
    to = _name(draft.get('chat')) if draft.get('chat') else (draft.get('phone') or 'ese chat')
    try:
        card = _post(user, f'Esta es tu respuesta para «{to}». Revísala y toca Enviar:', f'whatsapp-draft:{draft["id"]}',
                     [{'type': 'whatsapp_draft', 'target': draft['id'], 'label': 'Enviar por WhatsApp'}])
    except Exception:
        card = None
    if card is None:
        # No card to send it from: no draft either (nothing may wait unseen).
        WhatsAppDraft.objects.filter(pk=draft['id'], status=WhatsAppDraft.Status.DRAFT).delete()
        raise service.LinkRefused('unavailable')
    return draft


def _notice_by_chat(user, chat):
    """The newest important message from the chat the assistant named (its name as WhatsApp shows it)."""
    wanted = ' '.join(str(chat or '').split()).casefold()
    if not wanted:
        return None
    notices = WhatsAppNotice.objects.filter(link__user=user).order_by('-created_at')[:30]
    named = [(notice, (service._unseal(notice.sealed, {}).get('chat') or '').casefold()) for notice in notices]
    for notice, name in named:
        if name == wanted:
            return notice
    # Only a longer name holding what was said ("Farmacia" for "Farmacia Central"), and only when one chat does:
    # never a short name inside a longer request ("Ana" for "Ana María").
    close = {name: notice for notice, name in named if name and wanted in name}
    return next(iter(close.values())) if len(close) == 1 else None


def outcome(draft_id):
    """After a send: the assistant says how it went, once."""
    draft = WhatsAppDraft.objects.select_related('link__user').filter(pk=draft_id).first()
    if draft is None or draft.status == WhatsAppDraft.Status.SENDING:
        return
    if draft.status == WhatsAppDraft.Status.SENT:
        body = 'Listo, lo envié desde tu WhatsApp.'
    elif draft.status == WhatsAppDraft.Status.DRAFT:
        if not draft.reason:
            return
        body = (service.REASONS.get(draft.reason) or service.REASONS['whatsapp']) + ' No se envió.'
    else:
        body = service.REASONS.get(draft.reason) or service.REASONS['unknown']
    try:
        # Tagged by the send's moment: a draft refused, then sent, says both.
        _post(draft.link.user, body, f'whatsapp-sent:{draft.pk}:{draft.sending_at and draft.sending_at.timestamp()}')
    except Exception as exc:  # noqa: BLE001 - the card shows how it went either way
        logger.warning('WhatsApp send outcome not posted: %s', type(exc).__name__)


def erase(user):
    """Everything WhatsApp the assistant said in the person's conversation: gone with the link (unlinked from
    Confío or the phone, or the account leaving), as the consent says."""
    from inbox.models import SupportMessage
    try:
        SupportMessage.objects.filter(conversation__user=user, metadata__whatsapp=True).delete()
        # An answer that told her what her kept messages said (assistant.service tags it): its words go. The line
        # stays, so the thread and the turn that points at it keep their shape.
        for mark in ('whatsapp_read', 'whatsapp_follow'):  # the answer that read them, and the one right after it
            SupportMessage.objects.filter(conversation__user=user, **{f'metadata__{mark}': True}).update(
                body=READ_ERASED, metadata={'ai': True, 'actions': [], 'whatsapp_erased': True})
    except Exception as exc:  # noqa: BLE001 - retried by the next unlink path; logged by type only
        logger.error('WhatsApp chat posts not erased: %s', type(exc).__name__)


READ_ERASED = 'Borré esta respuesta porque hablaba de tus mensajes de WhatsApp y lo desvinculaste.'

CONSENT_CHANGED = ('Cambié cómo leo tu WhatsApp: ahora entiendo la conversación completa de cada chat (guardo los '
                   'últimos 30 días, también lo que tú respondes), para avisarte mejor y que me preguntes por ellos. '
                   'Hasta que lo revises no leo nada. Revísalo en «WhatsApp, correo y calendario» → WhatsApp → '
                   'Revisar.')


def ask_consent(link, version):
    """Once per version: the assistant tells a linked person the text changed and nothing is read until they
    review it (the Revisar chip opens the WhatsApp screen on builds that know it). True when it was posted now."""
    from inbox.models import SupportMessage
    tag = f'whatsapp-consent:{link.pk}:{version}'
    if SupportMessage.objects.filter(conversation__user=link.user, metadata__notice=tag).exists():
        return False
    posted = _post(link.user, CONSENT_CHANGED, tag, [{'type': 'whatsapp_consent', 'target': str(version),
                                                       'label': 'Revisar'}])
    return posted is not None
