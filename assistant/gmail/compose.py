"""Drafts and the confirmed send."""
import base64
import hashlib
import json
import logging
import re
from datetime import timedelta
from email import message_from_bytes, policy
from email.header import Header
from email.message import EmailMessage

from django.core import signing
from django.db import transaction
from django.utils import timezone

from . import config, crypto, reader, session, text
from .errors import GmailError, MailRefused
from .models import GmailConnection, MailDraft

logger = logging.getLogger(__name__)
DRAFT_HOURS = 24
HANDLE_SECONDS = 3600
MAX_BODY = 8000
MAX_SUBJECT = 200
_HANDLE_SALT = 'assistant.gmail.source'
_MESSAGE_ID = re.compile(r'<[!-~]{1,250}?>')  # printable ASCII, no spaces or line breaks


def handle_for(connection, mail) -> str:
    return signing.dumps({'g': str(connection.grant), 'm': mail.id}, salt=_HANDLE_SALT)


def _source(connection, handle):
    try:
        data = signing.loads(handle, salt=_HANDLE_SALT, max_age=HANDLE_SECONDS)
    except signing.BadSignature:
        data = {}
    if data.get('g') != str(connection.grant):
        raise MailRefused('source', 'Vuelve a buscar ese correo para responderlo.')
    mail = text.parse(session.mailbox(connection).message(data['m']))
    if mail.is_security:
        raise MailRefused('security', 'No trabajo con correos de códigos o contraseñas.')
    return mail


def _recipient(value):
    found = text.addresses(value)
    if len(found) != 1:
        raise MailRefused('recipient', 'Escribe una sola dirección de correo válida.')
    return found[0]


def _reply_target(mail):
    """(to, warning). Addresses come from headers only, never from the body or the model."""
    if mail.sent:  # Gmail's label: From can be forged
        return _recipient(mail.headers.get('to')), False
    sender = text.addresses(mail.headers.get('from'))
    reply_to = mail.headers.get('reply-to')
    found = text.addresses(reply_to or mail.headers.get('from'))
    if len(found) != 1:
        raise MailRefused('recipient', 'No puedo responder a esa dirección desde aquí. Respóndelo desde Gmail.')
    to = found[0]
    return to, bool(reply_to) and (not sender or sender[0].lower() != to.lower())


def _ids(value):
    # '=?' would be decoded by the email library into a header nobody checked.
    return [found for found in _MESSAGE_ID.findall(str(value or '')[-4000:]) if '=?' not in found]


def display_hash(fields) -> str:
    shown = [fields.get(key) or '' for key in ('sender', 'to', 'subject', 'body', 'thread_id')]
    return hashlib.sha256(json.dumps(shown).encode()).hexdigest()


def present(fields, draft=None, can_send=False) -> dict:
    return {
        'id': str(draft.pk) if draft else None,
        'sender': fields['sender'] or None,
        'to': fields['to'],
        'subject': fields['subject'],
        'body': fields['body'],
        'is_reply': bool(fields.get('thread_id')),
        'reply_to_differs': bool(fields.get('reply_to_differs')),
        'can_send': bool(draft and can_send),
        'display_hash': display_hash(fields),
    }


def create(connection, instructions, to=None, source=None) -> dict:
    active = connection is not None and connection.status == GmailConnection.Status.ACTIVE
    own = crypto.unseal(connection.sealed_email) if active else ''
    fields = {'sender': own, 'thread_id': '', 'reply_to_differs': False, 'in_reply_to': '', 'references': ''}
    original = None
    if source:
        if not active:
            raise MailRefused('reconnect', 'Conecta tu Gmail para responder ese correo.')
        original = _source(connection, source)
        fields['to'], fields['reply_to_differs'] = _reply_target(original)
    else:
        fields['to'] = _recipient(to)
    thread = None
    if original is not None and config.thread_consented(connection) and original.thread_id:
        try:
            thread = text.conversation(session.mailbox(connection).thread(original.thread_id), original.id)
        except GmailError as exc:
            logger.warning('Gmail thread not read for a reply: status %s', exc.status)
    subject, body = reader.write(instructions, original, thread)
    if original is not None:
        subject = original.subject
        if not subject.lower().startswith('re:'):
            subject = f'Re: {subject}'
        fields['thread_id'] = original.thread_id
        message_id = _ids(original.headers.get('message-id'))[:1]
        earlier = _ids(original.headers.get('references'))[-10:]
        fields['in_reply_to'] = ''.join(message_id)
        fields['references'] = ' '.join(earlier + message_id)
    if not body:
        raise MailRefused('error', 'No pude escribir el correo. Inténtalo de nuevo.')
    fields.update(subject=subject[:MAX_SUBJECT], body=body)
    if not active:
        # Nothing to send with: the app hands it to the phone's composer. Not stored.
        return present(fields)
    with transaction.atomic():
        current = GmailConnection.objects.select_for_update().filter(pk=connection.pk, grant=connection.grant).first()
        if current is None:
            raise MailRefused('reconnect', 'Tu conexión con Gmail cambió. Inténtalo de nuevo.')
        draft = MailDraft.objects.create(connection=current, sealed=crypto.seal(fields),
                                         expires_at=timezone.now() + timedelta(hours=DRAFT_HOURS))
    return present(fields, draft, connection.can_send)


def _locked(connection, draft_id):
    draft = MailDraft.objects.select_for_update().filter(
        pk=draft_id, connection=connection, expires_at__gt=timezone.now()).first()
    if draft is None:
        raise MailRefused('not_found', 'Ese borrador ya no existe.')
    if draft.status != MailDraft.Status.DRAFT:
        raise MailRefused('sent_unknown', 'Ese correo ya se intentó enviar. Revisa tu carpeta Enviados.')
    return draft


def show(connection, draft_id) -> dict:
    """A draft as its card shows it."""
    draft = MailDraft.objects.filter(pk=draft_id, connection=connection, expires_at__gt=timezone.now()).first()
    if draft is None:
        raise MailRefused('not_found', 'Ese borrador ya no existe.')
    if draft.status != MailDraft.Status.DRAFT:
        raise MailRefused('sent_unknown', 'Ese correo ya se intentó enviar. Revisa tu carpeta Enviados.')
    return present(crypto.unseal(draft.sealed), draft, connection.can_send)


def update(connection, draft_id, to, subject, body) -> dict:
    with transaction.atomic():
        draft = _locked(connection, draft_id)
        fields = crypto.unseal(draft.sealed)
        if not fields['thread_id']:
            fields['to'] = _recipient(to)
            fields['subject'] = text.one_line(subject, MAX_SUBJECT).replace('=?', '= ?')
        # A reply keeps its thread's recipient and subject.
        fields['body'] = text.visible(str(body or '')[:MAX_BODY + 1]).strip()
        if not fields['body'] or len(body) > MAX_BODY:
            raise MailRefused('invalid', 'El mensaje está vacío o es demasiado largo.')
        draft.sealed = crypto.seal(fields)
        draft.save(update_fields=['sealed'])
    return present(fields, draft, connection.can_send)


class _SendPolicy(policy.EmailPolicy):
    """Long ids stay on one line; an accented subject gets encoded words of at most 75 characters.

    The standard folder does neither: it encodes the ids and, unfolded, makes one huge word of the subject.
    """

    def fold_binary(self, name, value):
        if name.lower() == 'subject' and not str(value).isascii():
            encoded = Header(str(value), 'utf-8', header_name='Subject', maxlinelen=70).encode(linesep='\r\n')
            return f'{name}: {encoded}\r\n'.encode('ascii')
        return super().fold_binary(name, value)


_SEND_POLICY = _SendPolicy(linesep='\r\n', max_line_length=998)


def raw_message(fields) -> str:
    """Builds the mail, then reads it back: what leaves must be what was confirmed."""
    message = EmailMessage(policy=policy.SMTP)
    message['From'] = fields['sender']
    message['To'] = fields['to']
    message['Subject'] = fields['subject']
    if fields.get('in_reply_to'):
        message['In-Reply-To'] = fields['in_reply_to']
        message['References'] = fields['references']
    message.set_content(fields['body'])
    # Long headers only (the body is already encoded): folded ids come out as invalid encoded words.
    raw = message.as_bytes(policy=_SEND_POLICY)
    _verify(raw, fields)
    return base64.urlsafe_b64encode(raw).decode()


def _verify(raw, fields):
    sent = message_from_bytes(raw, policy=policy.default)
    plain = lambda value: str(value or '').replace('\r\n', '\n').rstrip()
    same = (
        len(sent.get_all('to') or []) == 1 and str(sent['to']) == fields['to']
        and len(sent.get_all('from') or []) == 1 and str(sent['from']) == fields['sender']
        and not any(sent.get_all(name) for name in ('cc', 'bcc', 'resent-to', 'reply-to'))
        and str(sent['subject'] or '') == fields['subject']
        and not sent.is_multipart() and plain(sent.get_content()) == plain(fields['body'])
        and str(sent['in-reply-to'] or '') == (fields.get('in_reply_to') or '')
    )
    if not same:
        raise MailRefused('mismatch', 'No pude preparar ese correo tal como lo viste. No se envió.')


def send(connection, draft_id, shown_hash):
    """Sends exactly what was shown, at most once."""
    if not connection.can_send:
        raise MailRefused('no_send', 'No diste permiso para enviar. Ábrelo en tu app de correo o reconecta Gmail.')
    with transaction.atomic():
        draft = _locked(connection, draft_id)
        fields = crypto.unseal(draft.sealed)
        if shown_hash != display_hash(fields):
            raise MailRefused('changed', 'El borrador cambió. Revísalo otra vez antes de enviarlo.')
        draft.status = MailDraft.Status.SENDING
        draft.save(update_fields=['status'])
    row = MailDraft.objects.filter(pk=draft.pk)
    try:
        box, raw = session.mailbox(connection), raw_message(fields)
    except Exception:
        row.update(status=MailDraft.Status.DRAFT)  # nothing left the server
        raise
    try:
        box.send(raw, fields.get('thread_id'))
    except GmailError as exc:
        logger.warning('Gmail send failed: status %s', exc.status)
        if exc.definitive:
            row.update(status=MailDraft.Status.DRAFT)
            raise MailRefused('send_refused', 'Gmail no aceptó el correo. No se envió.') from None
        row.update(status=MailDraft.Status.UNKNOWN)
        raise MailRefused('sent_unknown', 'No sé si el correo salió. Revisa tu carpeta Enviados antes de repetirlo.') from None
    row.delete()
