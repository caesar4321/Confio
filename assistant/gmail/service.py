"""What the API calls."""
import logging

from django.db.models import Q
from django.utils import timezone

from . import compose, config, crypto, limits, reader, session, text
from .errors import GmailError, MailRefused
from .models import GmailConnection

logger = logging.getLogger(__name__)
MAX_WORDS = 1000
ANSWER_FROM = 5
AGENDA_DAYS = 2
MAX_EVENT_TITLE = 80


def words(value) -> str:
    clean = text.visible(value).strip()
    if not clean or len(clean) > MAX_WORDS:
        raise MailRefused('invalid', f'Escribe hasta {MAX_WORDS} caracteres.')
    return clean


def connection_of(user):
    return GmailConnection.objects.filter(user=user).first()


def overview(user, account, jwt_context) -> dict:
    connection = connection_of(user) if config.is_personal(account, jwt_context) else None
    available = config.allowed(user, account, jwt_context)
    result = {'available': available, 'connected': connection is not None, 'needs_reconnect': False,
              'can_send': False, 'can_calendar': False, 'consent_outdated': False, 'email': None, 'needs': []}
    if connection is None:
        return result
    result['needs_reconnect'] = connection.status != GmailConnection.Status.ACTIVE
    if not available:
        return result  # only enough to disconnect
    if not config.consented(connection):
        # Connected under an older text: nothing is read until they accept today's.
        result.update(needs_reconnect=True, consent_outdated=True)
        return result
    try:
        result['email'] = crypto.unseal(connection.sealed_email)
        shown = connection.needs.filter(Q(due_date__isnull=True) | Q(due_date__gte=config.local_today()),
                                        dismissed=False).order_by('due_date', '-created_at')[:30]
        for need in shown:
            extra = crypto.unseal(need.sealed)
            result['needs'].append({'id': str(need.pk), 'kind': need.kind, 'due_date': need.due_date,
                                    'amount': extra.get('amount'), 'currency': extra.get('currency'),
                                    'summary': extra.get('summary') or None})
    except Exception as exc:  # noqa: BLE001 - unreadable (a wrong key): disconnect must stay reachable
        logger.warning('Gmail connection unreadable: %s', type(exc).__name__)
        result.update(needs_reconnect=True, email=None, needs=[])
        return result
    result['can_send'] = connection.can_send
    result['can_calendar'] = connection.can_calendar
    return result


def agenda(user) -> list:
    """Today and tomorrow, read from Google for this one answer: never stored, never sent to a model."""
    connection = connection_of(user)
    if connection is None:
        raise MailRefused('not_connected', 'Conecta tu Gmail primero.')
    if not config.consented(connection):
        raise MailRefused('reconnect', session.OUTDATED)
    limits.claim(user, 'agenda')
    events = session.calendar(connection).events(timezone.now(), AGENDA_DAYS, config.utc_offset(user))
    return [{'title': text.strict_line(event['title'], MAX_EVENT_TITLE, numbers=True) or 'Sin título',
             'day': event['day'], 'starts_at': event['starts_at'], 'all_day': event['all_day']}
            for event in events]


def ask(user, question) -> dict:
    question = words(question)
    connection = connection_of(user)
    if connection is None:
        raise MailRefused('not_connected', 'Conecta tu Gmail primero.')
    limits.claim(user, 'ask')
    offset = config.utc_offset(user)
    today = config.local_today(offset=offset)
    query = reader.plan_search(question, today)
    box = session.mailbox(connection)
    mails = []
    for message_id in box.search(f'{query} -in:spam -in:trash'.strip(), ANSWER_FROM * 2):
        try:
            raw = box.message(message_id)
        except GmailError as exc:
            if exc.status in (404, 413):
                continue
            raise
        try:
            mail = text.parse(raw)
            mail.utc_offset = offset
            if not mail.is_security:
                mail.for_model(reader.MAX_MAIL_CHARS)
                mails.append(mail)
        except Exception as exc:  # noqa: BLE001 - one unreadable mail is skipped
            logger.warning('Unreadable mail skipped: %s', type(exc).__name__)
        if len(mails) == ANSWER_FROM:
            break
    if not mails:
        return {'answer': 'No encontré correos sobre eso.', 'sources': []}
    answer = reader.answer(question, mails, today)
    if not answer:
        raise MailRefused('error', 'No pude leer tus correos ahora. Inténtalo de nuevo.')
    return {'answer': answer, 'sources': [
        {'handle': compose.handle_for(connection, mail), 'sender': mail.sender, 'subject': mail.subject,
         'sent_at': mail.sent_at} for mail in mails]}


def need_source(user, need_id) -> dict:
    """Who sent the mail behind a need, read again from Gmail: never stored."""
    connection = connection_of(user)
    need = connection.needs.filter(pk=need_id).first() if connection and str(need_id).isdigit() else None
    if need is None:
        raise MailRefused('not_found', 'Ese aviso ya no existe.')
    limits.claim(user, 'source')
    mail = text.parse(session.mailbox(connection).message(crypto.unseal(need.sealed)['id']))
    return {'handle': compose.handle_for(connection, mail), 'sender': mail.sender, 'subject': mail.subject,
            'sent_at': mail.sent_at}


def dismiss(user, need_id):
    connection = connection_of(user)
    if connection and str(need_id).isdigit():
        connection.needs.filter(pk=need_id).update(dismissed=True)
