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

from celery.exceptions import SoftTimeLimitExceeded
from django.db import transaction
from django.utils import timezone

from assistant.connections_models import AssistantConnectionRequest

from . import client, config, crypto, text
from .errors import GmailError, MailRefused
from .models import GmailConnection, GmailGrant, GmailOAuthState

logger = logging.getLogger(__name__)
AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
ATTEMPT_MINUTES = 15
# An expired attempt is kept this long, so a late return from Google is still counted.
LATE_HOURS = 6
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
    with transaction.atomic():
        GmailOAuthState.objects.filter(user=user).delete()
        if config.self_serve() and not config.holds_place(user):
            # Google counts whoever consents: an open attempt by someone without a place holds one.
            # A member is never held back: a reconnect must work, and Google itself stops a 101st account.
            _seats_lock()
            from assistant import connections
            if connections.seats_left() <= 0:
                raise MailRefused('full', FULL)
        GmailOAuthState.objects.create(
            state_hash=_hash(state), user=user, challenge=challenge, consent_version=consent_version,
            expires_at=timezone.now() + timedelta(minutes=ATTEMPT_MINUTES))
    query = urlencode({
        'client_id': config.value('GMAIL_OAUTH_CLIENT_ID'),
        'redirect_uri': config.value('GMAIL_OAUTH_REDIRECT_URI'),
        'response_type': 'code',
        'scope': f'{config.READ_SCOPE} {config.SEND_SCOPE} {config.CALENDAR_SCOPE}',
        'access_type': 'offline',
        'prompt': 'consent select_account',
        'state': state,
        'code_challenge': challenge,
        'code_challenge_method': 'S256',
    })
    return f'{AUTH_URL}?{query}', verifier


def complete(user, code, state, verifier):
    attempt = GmailOAuthState.objects.filter(state_hash=_hash(state or ''), user=user).first()
    if attempt is None or not attempt.challenge or not secrets.compare_digest(
            _challenge(verifier or ''), attempt.challenge):
        raise MailRefused('expired', 'La conexión venció. Vuelve a tocar Conectar Gmail.')
    # Used once. The row stays, still holding its place, until this attempt is counted below.
    if not GmailOAuthState.objects.filter(pk=attempt.pk, challenge=attempt.challenge).update(challenge=''):
        raise MailRefused('expired', 'La conexión ya se usó. Vuelve a tocar Conectar Gmail.')
    known = ''
    try:
        if attempt.expires_at <= timezone.now():
            raise MailRefused('expired', 'La conexión venció. Vuelve a tocar Conectar Gmail.')
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
            known = address
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
    finally:
        # They came back from Google's screen: Google counted them, whatever happened here. Then the hold ends.
        _granted(known)
        GmailOAuthState.objects.filter(pk=attempt.pk).delete()
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
        # no_key: a notice or log row pointing at this person (written under their request's lock) must not wait on it.
        type(user).objects.select_for_update(no_key=True).filter(pk=user.pk).first()
        member = str(user.pk) in config.tester_ids()
        if not config.eligible(user) or not (member or (config.self_serve() and not config.had_place(user))):
            # Access ended while they were on Google's screen. The caller revokes what Google just gave.
            raise MailRefused('unavailable', 'Conectar Gmail ya no está disponible para esta cuenta.')
        if not member:
            _take_place(user)
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
            _forget_notices(user.pk)
        if row is None:
            row = GmailConnection(user=user)
        row.grant = uuid.uuid4()
        row.status = GmailConnection.Status.ACTIVE
        row.sealed_token, row.sealed_email = crypto.seal(tokens['refresh_token']), crypto.seal(address)
        row.email_key = email_key
        granted = set(str(tokens.get('scope') or '').split())
        row.can_send = config.SEND_SCOPE in granted
        row.can_calendar = config.CALENDAR_SCOPE in granted
        row.calendar_checked_on = None
        row.consent_version = attempt.consent_version
        row.connected_at = row.next_sync_at = now
        row.failures = 0
        row.save()
        # The typed address was only for getting them in. Not left for the sweep: they may disconnect before it.
        AssistantConnectionRequest.objects.filter(
            user=user, feature=AssistantConnectionRequest.Feature.GMAIL).exclude(google_email='').update(google_email='')
    return row, stale


FULL = 'Ya no quedan cupos para conectar Gmail.'


def _seats_lock():
    from assistant import connections
    from django.db import connection as database
    with database.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [connections.SEATS_LOCK])


def _granted(address):
    """Mirrors Google's lifetime count: one row per Google account that consented (a random key when unknown)."""
    key = crypto.opaque(address.lower()) if address else f'unknown:{uuid.uuid4().hex}'
    try:
        with transaction.atomic():
            GmailGrant.objects.get_or_create(key=key)
    except Exception as exc:  # noqa: BLE001 - the connect must not fail on the count; GMAIL_PILOT_FULL is the backstop
        logger.warning('Gmail grant not counted: %s', type(exc).__name__)


def _take_place(user):
    """Self-serve: the place held when Google's screen opened becomes theirs. Not re-checked: Google already counted them."""
    if not config.self_serve() or config.had_place(user):
        raise MailRefused('unavailable', 'Conectar Gmail ya no está disponible para esta cuenta.')
    now = timezone.now()
    AssistantConnectionRequest.objects.update_or_create(
        user=user, feature=AssistantConnectionRequest.Feature.GMAIL,
        defaults={'answer': AssistantConnectionRequest.Answer.YES, 'invited_at': now, 'ready_at': now,
                  'removed_at': None, 'google_email': ''})


NOTICE_TYPE = 'assistant_mail'


def _forget_notices(user_id):
    """The notices in the person's list say how many mails and events there were: they go with the rest."""
    try:
        from notifications.models import Notification
        with transaction.atomic():  # its own savepoint: a failure here must not undo erasing the token
            Notification.objects.filter(user_id=user_id, data__type=NOTICE_TYPE).delete()
    except Exception as exc:  # noqa: BLE001
        logger.warning('Gmail notices not erased: %s', type(exc).__name__)


def disconnect(connection) -> bool:
    """Deletes everything here but the GmailGrant count. True when Google confirmed the revoke (or had no grant left)."""
    with transaction.atomic():
        row = GmailConnection.objects.select_for_update().filter(pk=connection.pk).first()
        # The token as it is now: a reconnect may have replaced the one we were given.
        blob = row.sealed_token if row else ''
        if row:
            row.delete()
        GmailOAuthState.objects.filter(user_id=connection.user_id).delete()
        _forget_notices(connection.user_id)
    if not blob:
        return True
    if _grant_shared(row.email_key):
        return True  # ours is erased, and the grant now belongs only to the other account
    try:
        return client.revoke(crypto.unseal(blob))
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - local deletion already happened
        logger.warning('Gmail revoke failed: %s', type(exc).__name__)
        return False
