"""Connect and disconnect.

The browser only carries the code back to the app. The exchange needs the
signed-in person who started the attempt plus the verifier only their app holds,
so a forwarded link cannot attach someone else's mailbox to an attacker's account.
"""
import base64
import hashlib
import logging
import secrets
import uuid
from datetime import timedelta
from urllib.parse import urlencode

from django.db import transaction
from django.utils import timezone

from . import client, config, crypto, text
from .errors import GmailError, MailRefused
from .models import GmailConnection, GmailOAuthState

logger = logging.getLogger(__name__)
AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
ATTEMPT_MINUTES = 15
FAILED = 'No pude conectar Gmail. Inténtalo de nuevo.'


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')


def start(user, consent_version):
    if consent_version != config.CONSENT_VERSION:
        raise MailRefused('consent', 'Actualiza la app para conectar Gmail.')
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = _challenge(verifier)
    GmailOAuthState.objects.filter(user=user).delete()
    GmailOAuthState.objects.create(
        state_hash=_hash(state), user=user, challenge=challenge, consent_version=consent_version,
        expires_at=timezone.now() + timedelta(minutes=ATTEMPT_MINUTES))
    query = urlencode({
        'client_id': config.value('GMAIL_OAUTH_CLIENT_ID'),
        'redirect_uri': config.value('GMAIL_OAUTH_REDIRECT_URI'),
        'response_type': 'code',
        'scope': f'{config.READ_SCOPE} {config.SEND_SCOPE}',
        'access_type': 'offline',
        'prompt': 'consent select_account',
        'state': state,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
    })
    return f'{AUTH_URL}?{query}', verifier


def complete(user, code, state, verifier):
    attempt = GmailOAuthState.objects.filter(
        state_hash=_hash(state or ''), user=user, expires_at__gt=timezone.now()).first()
    if attempt is None or not secrets.compare_digest(_challenge(verifier or ''), attempt.challenge):
        raise MailRefused('expired', 'La conexión venció. Vuelve a tocar Conectar Gmail.')
    if not GmailOAuthState.objects.filter(pk=attempt.pk).delete()[0]:
        raise MailRefused('expired', 'La conexión ya se usó. Vuelve a tocar Conectar Gmail.')
    try:
        tokens = client.exchange_code(code, verifier)
    except GmailError as exc:
        logger.warning('Gmail connect failed: status %s', exc.status)
        raise MailRefused('error', FAILED) from None
    refresh, address = tokens.get('refresh_token'), ''
    try:
        if config.READ_SCOPE not in set(str(tokens.get('scope') or '').split()):
            raise MailRefused('no_read', 'Para usarlo, marca el permiso de ver tus correos en la pantalla de Google.')
        if not refresh or not tokens.get('access_token'):
            raise MailRefused('error', FAILED)
        address = client.Mailbox(tokens['access_token']).address()
        if not text.addresses(address):
            raise MailRefused('error', FAILED)
        row, stale = _save(user, attempt, tokens, address)
    except Exception as exc:
        # A revoke ends the whole user+project grant, so only when no saved connection shares it.
        if (refresh and not GmailConnection.objects.filter(user=user).exclude(sealed_token='').exists()
                and not (address and _grant_shared(crypto.opaque(address.lower())))):
            client.revoke(refresh)
        if isinstance(exc, GmailError):
            logger.warning('Gmail connect failed: status %s', exc.status)
            raise MailRefused('error', FAILED) from None
        raise
    if stale and not _grant_shared(stale[1]):
        client.revoke(stale[0])
    return row


def _grant_shared(email_key) -> bool:
    """Another Confío account holds the same Gmail: a revoke would end that person's grant too."""
    return GmailConnection.objects.filter(email_key=email_key).exclude(sealed_token='').exists()


def _save(user, attempt, tokens, address):
    now, email_key, stale = timezone.now(), crypto.opaque(address.lower()), None
    with transaction.atomic():
        # Serialises two connects of the same person; the row lock waits out a sync, draft or disconnect.
        type(user).objects.select_for_update().filter(pk=user.pk).first()
        if not config.user_allowed(user):
            # Access ended while they were on Google's screen. The caller revokes what Google just gave.
            raise MailRefused('unavailable', 'Conectar Gmail ya no está disponible para esta cuenta.')
        row = GmailConnection.objects.select_for_update().filter(user=user).first()
        if row is not None and row.email_key != email_key:
            # Another mailbox: a new row, so nothing from the previous one stays (needs, drafts, what was read).
            if row.sealed_token:
                try:
                    stale = (crypto.unseal(row.sealed_token), row.email_key)
                except Exception as exc:  # noqa: BLE001 - unreadable: nothing to revoke with
                    logger.warning('Previous Gmail grant unreadable: %s', type(exc).__name__)
            row.delete()
            row = None
        if row is None:
            row = GmailConnection(user=user)
        row.grant = uuid.uuid4()
        row.status = GmailConnection.Status.ACTIVE
        row.sealed_token, row.sealed_email = crypto.seal(tokens['refresh_token']), crypto.seal(address)
        row.email_key = email_key
        row.can_send = config.SEND_SCOPE in set(str(tokens.get('scope') or '').split())
        row.consent_version = attempt.consent_version
        row.connected_at = row.next_sync_at = now
        row.failures = 0
        row.save()
    return row, stale


def disconnect(connection) -> bool:
    """Deletes everything here. True when Google confirmed the revoke (or had no grant left)."""
    with transaction.atomic():
        row = GmailConnection.objects.select_for_update().filter(pk=connection.pk).first()
        # The token as it is now: a reconnect may have replaced the one we were given.
        blob = row.sealed_token if row else ''
        if row:
            row.delete()
        GmailOAuthState.objects.filter(user_id=connection.user_id).delete()
    if not blob:
        return True
    if _grant_shared(row.email_key):
        return True  # ours is erased, and the grant now belongs only to the other account
    try:
        return client.revoke(crypto.unseal(blob))
    except Exception as exc:  # noqa: BLE001 - local deletion already happened
        logger.warning('Gmail revoke failed: %s', type(exc).__name__)
        return False
