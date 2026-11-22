"""Background: find needs, nudge, and erase what must not stay."""
import logging
import time
from datetime import timedelta

from celery.exceptions import SoftTimeLimitExceeded
from django.core.cache import cache
from django.db import transaction
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from . import config, crypto, oauth, reader, session, text
from .errors import GmailError, MailRefused
from .models import GmailConnection, GmailOAuthState, MailDraft, MailNeed

logger = logging.getLogger(__name__)

# Under the 15-minute sweep: at 15 exactly every other sweep found it not due yet.
INTERVAL = timedelta(minutes=14)
LEASE = timedelta(minutes=30)
BACKFILL = timedelta(days=30)
KEEP = timedelta(days=30)
MAX_BACKOFF = timedelta(hours=6)
LISTED = 100
MAX_PER_SYNC = 20
RUN_SECONDS = 30  # the analytics worker is shared with the daily snapshots
SYNCS_PER_SWEEP = 20
MAX_READS_PER_DAY = 200
MAX_TRIES = 3
LONE_FAILURES = 5  # about seven hours of backoff
SEEN_SECONDS = 2 * 86400
# Gmail's own index is the cheap filter: only these mails are ever fetched.
FILTER = ('{factura facturas fatura invoice bill boleto boleta vence vencen vencimiento vencimento "due date" pago '
          'pagamento payment pagar pague cobranza cobrança cobro plazo prazo expira expires renovar renovación '
          'renuévalo hotel estadía pasajes entradas '
          'cuota parcela recibo pasaje passagem ticket entrada ingresso reserva booking itinerario itinerary vuelo '
          'voo flight alquiler aluguel impuesto imposto} -category:promotions -category:social -in:sent -in:spam '
          '-in:trash')
# 09:00 in La Paz and Caracas: daytime across LATAM.
NUDGE_HOURS_UTC = range(13, 23)
NUDGE = ('Confío IA', 'Tienes algo pendiente en tu correo. Míralo en Confío IA: ✨ Tu asistente → Tu correo.')
RECONNECT = ('Confío IA', 'Tu Gmail se desconectó. Reconéctalo en Confío IA: ✨ Tu asistente → Tu correo.')


def due_connection_ids():
    testers = config.tester_ids() if config.configured() else set()
    if not testers:
        return []
    return list(GmailConnection.objects.filter(
        status=GmailConnection.Status.ACTIVE, next_sync_at__lte=timezone.now(),
        user_id__in=[int(pk) for pk in testers],
    ).order_by('next_sync_at').values_list('pk', flat=True)[:SYNCS_PER_SWEEP])


def sync(connection_id):
    now = timezone.now()
    if not GmailConnection.objects.filter(
            pk=connection_id, status=GmailConnection.Status.ACTIVE, next_sync_at__lte=now,
    ).update(next_sync_at=now + LEASE):
        return  # taken by another worker, or not due
    connection = GmailConnection.objects.select_related('user').filter(pk=connection_id).first()
    if connection is None or not config.user_allowed(connection.user):
        return
    mine = GmailConnection.objects.filter(pk=connection.pk, grant=connection.grant)
    try:
        finished = _read(connection, now)
    except MailRefused as exc:
        if exc.code == 'reconnect' and mine.filter(status=GmailConnection.Status.EXPIRED).exists():
            _notify(connection.user, RECONNECT)
        return
    except Exception as exc:  # noqa: BLE001 - reported by type: a message can quote mail
        logger.warning('Gmail sync %s failed: %s', connection.pk, type(exc).__name__)
        wait = min(INTERVAL * 2 ** min(connection.failures, 6), MAX_BACKOFF)
        mine.update(failures=min(connection.failures + 1, 100), next_sync_at=now + wait)
        return
    if finished:
        mine.update(last_sync_at=now, failures=0, next_sync_at=now + INTERVAL)
    else:
        # More to read: the next sweep continues, and what was read is not read again.
        mine.update(failures=0, next_sync_at=now + INTERVAL)


def _still_mine(connection) -> bool:
    """Disconnected, reconnected, banned, off the list or switched off: stop before the next mail."""
    row = GmailConnection.objects.select_related('user').filter(
        pk=connection.pk, grant=connection.grant, status=GmailConnection.Status.ACTIVE).first()
    return row is not None and config.user_allowed(row.user)


def _claim_read(connection, now) -> bool:
    key = f'assistant-gmail:reads:{connection.user_id}:{now.date().isoformat()}'
    try:
        cache.add(key, 0, 2 * 86400)
        count = cache.incr(key)
    except Exception:  # noqa: BLE001 - no counter, no paid call
        return False
    return isinstance(count, int) and count <= MAX_READS_PER_DAY


def _read(connection, now) -> bool:
    """True when every listed mail was dealt with."""
    # An hour of overlap: a mail can be indexed after the time it carries.
    since = connection.last_sync_at - timedelta(hours=1) if connection.last_sync_at else now - BACKFILL
    since = max(since, now - BACKFILL)
    box = session.mailbox(connection)
    prefix = f'assistant-gmail:seen:{connection.pk}:'  # disconnecting erases the needs, so it must read again
    waiting = []
    for message_id in box.search(f'after:{int(since.timestamp())} {FILTER}', LISTED):
        key = crypto.opaque(message_id)
        if cache.get(prefix + key) == 'done' or connection.needs.filter(source_key=key).exists():
            continue
        waiting.append((message_id, key))

    offset = config.utc_offset(connection.user)
    started, finished = time.monotonic(), len(waiting) <= MAX_PER_SYNC
    failed, worked, error = [], False, None
    for message_id, key in waiting[:MAX_PER_SYNC]:
        if time.monotonic() - started > RUN_SECONDS or not _still_mine(connection):
            finished = False
            break
        if not _claim_read(connection, now):
            finished = False
            break
        try:
            outcome = _one(connection, box, message_id, key, offset)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad mail must not stop the others
            if isinstance(exc, GmailError) and exc.status in (400, 404, 413):
                cache.set(prefix + key, 'done', SEEN_SECONDS)  # gone, or too large to read
                continue
            failed.append(key)
            error = exc
            continue
        if outcome == STOP:
            finished = False
            break
        # A skipped mail never called the model, so it proves nothing about an outage.
        worked = worked or outcome == READ
        cache.set(prefix + key, 'done', SEEN_SECONDS)
    if failed and not worked:
        # Google or the model is down: back off, blame no mail. Except one mail alone for hours: that is the mail.
        if len(failed) == 1 and connection.failures >= LONE_FAILURES:
            cache.set(prefix + failed[0], 'done', SEEN_SECONDS)
        raise error
    for key in failed:
        tries = cache.get(prefix + key) or 0
        tries += 1
        cache.set(prefix + key, 'done' if tries >= MAX_TRIES else tries, SEEN_SECONDS)
        if tries < MAX_TRIES:
            finished = False
    return finished


READ, SKIPPED, STOP = 'read', 'skipped', 'stop'


def _one(connection, box, message_id, key, offset):
    raw = box.message(message_id)
    try:
        mail = text.parse(raw)
        mail.utc_offset = offset
        if mail.is_security or mail.claims_confio:
            return SKIPPED
        mail.for_model(reader.MAX_MAIL_CHARS)
    except Exception as exc:  # noqa: BLE001 - unreadable by us: never worth a retry
        logger.warning('Unreadable mail skipped: %s', type(exc).__name__)
        return SKIPPED
    if not _still_mine(connection):
        return STOP
    need = reader.detect(mail, config.local_today(offset=offset))
    if need and not _store(connection, message_id, key, need):
        return STOP
    return READ


def _store(connection, message_id, key, need):
    with transaction.atomic():
        # Disconnected or reconnected meanwhile: write nothing.
        current = GmailConnection.objects.select_for_update().filter(pk=connection.pk, grant=connection.grant).first()
        if current is None:
            return False
        MailNeed.objects.get_or_create(connection=current, source_key=key, defaults={
            'kind': need['kind'], 'due_date': need['due_date'],
            'sealed': crypto.seal({'id': message_id, 'amount': need['amount'], 'currency': need['currency']}),
        })
        return True


def _notify(user, copy):
    try:
        from notifications.models import NotificationType
        from notifications.utils import create_notification
        # Fixed copy: a lock screen and our logs never show anything from the mail.
        create_notification(user=user, notification_type=NotificationType.SYSTEM, title=copy[0], message=copy[1],
                            data={'type': 'assistant_mail'})
    except Exception as exc:  # noqa: BLE001
        logger.warning('Gmail nudge failed: %s', type(exc).__name__)


def nudge(now=None):
    """At most one nudge a day for each person, for what is due today or tomorrow."""
    now = now or timezone.now()
    if now.hour not in NUDGE_HOURS_UTC or not config.configured():
        return 0
    today, sent = config.local_today(now), 0
    testers = [int(pk) for pk in config.tester_ids()]
    waiting = GmailConnection.objects.select_related('user').filter(
        Q(last_nudge_on__isnull=True) | Q(last_nudge_on__lt=today), user_id__in=testers)
    for connection in waiting:
        if not config.user_allowed(connection.user):
            continue
        needs = connection.needs.filter(dismissed=False, notified_at__isnull=True,
                                        due_date__gte=today, due_date__lte=today + timedelta(days=1))
        ids = list(needs.values_list('pk', flat=True))
        if not ids:
            continue
        claimed = GmailConnection.objects.filter(pk=connection.pk).filter(
            Q(last_nudge_on__isnull=True) | Q(last_nudge_on__lt=today)).update(last_nudge_on=today)
        if claimed:
            MailNeed.objects.filter(pk__in=ids).update(notified_at=now)
            _notify(connection.user, NUDGE)
            sent += 1
    return sent


def cleanup(now=None):
    """Runs even with the pilot off: deleting is never switched off."""
    now = now or timezone.now()
    cutoff = now - KEEP
    for connection in GmailConnection.objects.all():
        # all_objects: a deleted person is exactly who this is for.
        person = get_user_model().all_objects.filter(pk=connection.user_id).first()
        if person is None or not person.is_active or person.deleted_at or config.banned(person):
            oauth.disconnect(connection)
    MailNeed.objects.filter(
        Q(due_date__lt=cutoff.date()) | Q(due_date__isnull=True, created_at__lt=cutoff)).delete()
    MailDraft.objects.filter(expires_at__lte=now).delete()
    GmailOAuthState.objects.filter(expires_at__lte=now).delete()
    from assistant import connections
    try:
        for connection in connections.removed_connections()[:10]:
            oauth.disconnect(connection)
        connections.forget_addresses()
    except Exception as exc:  # noqa: BLE001 - the waitlist must not stop the rest of the sweep
        logger.warning('Connections cleanup failed: %s', type(exc).__name__)
