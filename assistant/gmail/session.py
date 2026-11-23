from . import client, config, crypto
from .errors import GrantEnded, MailRefused
from .models import GmailConnection


def expire(connection):
    """Marks the grant ended, unless the person reconnected meanwhile."""
    return GmailConnection.objects.filter(
        pk=connection.pk, grant=connection.grant, status=GmailConnection.Status.ACTIVE,
    ).update(status=GmailConnection.Status.EXPIRED, sealed_token='') == 1


def mailbox(connection) -> client.Mailbox:
    if connection is None:
        raise MailRefused('not_connected', 'Conecta tu Gmail primero.')
    if connection.status != GmailConnection.Status.ACTIVE or not connection.sealed_token:
        raise MailRefused('reconnect', 'Tu conexión con Gmail venció. Vuelve a conectarla.')
    return client.Mailbox(_token(connection))


def calendar(connection) -> client.Calendar:
    if connection is None:
        raise MailRefused('not_connected', 'Conecta tu Gmail primero.')
    if connection.status != GmailConnection.Status.ACTIVE or not connection.sealed_token:
        raise MailRefused('reconnect', 'Tu conexión con Gmail venció. Vuelve a conectarla.')
    if not connection.can_calendar:
        raise MailRefused('no_calendar', 'No diste permiso para ver tu calendario.')
    return client.Calendar(_token(connection))


OUTDATED = 'Vuelve a conectar tu Gmail para aceptar lo que lee ahora.'


def _token(connection) -> str:
    # Every read goes through here: none happens under an agreement that covered less.
    if not config.consented(connection):
        raise MailRefused('reconnect', OUTDATED)
    try:
        return client.access_token(crypto.unseal(connection.sealed_token))
    except GrantEnded:
        refused = MailRefused('reconnect', 'Tu conexión con Gmail venció. Vuelve a conectarla.')
        refused.ended_now = expire(connection)  # false: someone else already saw it end, and said so
        raise refused from None
