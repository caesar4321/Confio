from . import client, crypto
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
    try:
        return client.Mailbox(client.access_token(crypto.unseal(connection.sealed_token)))
    except GrantEnded:
        expire(connection)
        raise MailRefused('reconnect', 'Tu conexión con Gmail venció. Vuelve a conectarla.') from None
