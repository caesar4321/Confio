"""Background: find needs, nudge, and erase what must not stay."""
import logging
import time
from datetime import timedelta

from celery.exceptions import SoftTimeLimitExceeded
from django.core.cache import cache
from django.db import transaction
from django.contrib.auth import get_user_model
from django.db.models import F, Q
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
# Everything a person would read: bills land in Updates, so only advertising, social and forums stay out.
FILTER = ('-category:promotions -category:social -category:forums -in:sent -in:draft -in:chats -in:spam '
          '-in:trash')
# Without a date, only a recent mail is still something to attend.
UNDATED_DAYS = 3
# The person's own clock. The calendar is counted once, in the morning.
DAYTIME, MORNING = range(7, 21), range(7, 11)
# All the calendar calls of one sweep: the sweep also has to queue the syncs.
CALENDAR_SECONDS = 60
# A calendar that failed this often today no longer holds the mail part of the notice.
CALENDAR_TRIES = 3
MANY = 9
TITLE, WHERE = 'Confío IA', 'Míralo en Confío IA: ✨ Tu asistente → Tu correo.'
# Fixed words and counts: a lock screen never shows anything from a mail or an event.
WORDS = {'payment': ('pago', 'pagos'), 'deadline': ('vencimiento', 'vencimientos'),
         'reply': ('correo por responder', 'correos por responder'), 'appointment': ('cita', 'citas'),
         'trip': ('viaje', 'viajes'), 'ticket': ('pasaje o entrada', 'pasajes o entradas'),
         'delivery': ('entrega', 'entregas'), 'money': ('aviso de dinero', 'avisos de dinero')}
EVENTS = ('evento', 'eventos')
RECONNECT = ('Confío IA', 'Tu Gmail se desconectó. Reconéctalo en Confío IA: ✨ Tu asistente → Tu correo.')


def due_connection_ids():
    testers = config.tester_ids() if config.configured() else set()
    if not testers:
        return []
    return list(GmailConnection.objects.filter(
        status=GmailConnection.Status.ACTIVE, next_sync_at__lte=timezone.now(),
        user_id__in=[int(pk) for pk in testers], consent_version__gte=config.CONSENT_VERSION,
    ).order_by('next_sync_at').values_list('pk', flat=True)[:SYNCS_PER_SWEEP])


def sync(connection_id):
    now = timezone.now()
    if not GmailConnection.objects.filter(
            pk=connection_id, status=GmailConnection.Status.ACTIVE, next_sync_at__lte=now,
    ).update(next_sync_at=now + LEASE):
        return  # taken by another worker, or not due
    connection = GmailConnection.objects.select_related('user').filter(pk=connection_id).first()
    if connection is None or not config.user_allowed(connection.user) or not config.consented(connection):
        return
    mine = GmailConnection.objects.filter(pk=connection.pk, grant=connection.grant)
    try:
        finished = _read(connection, now)
    except MailRefused as exc:
        # ended_now: this call saw it end. Whoever sees it first says so, and nobody says it twice.
        if exc.code == 'reconnect' and getattr(exc, 'ended_now', False):
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
    if need and not need['due_date'] and mail.sent_at < timezone.now() - timedelta(days=UNDATED_DAYS):
        need = None  # the first read goes back 30 days: an old letter is not news
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
            'sealed': crypto.seal({'id': message_id, 'amount': need['amount'], 'currency': need['currency'],
                                   'summary': need.get('summary') or ''}),
        })
        return True


def _notify(user, copy):
    try:
        from notifications.models import NotificationType
        from notifications.utils import create_notification
        # Fixed copy: a lock screen and our logs never show anything from the mail.
        create_notification(user=user, notification_type=NotificationType.SYSTEM, title=copy[0], message=copy[1],
                            data={'type': oauth.NOTICE_TYPE})
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning('Gmail nudge failed: %s', type(exc).__name__)


def _counted(count, words) -> str:
    # Capped: how many mails arrive is in a sender's hands.
    return f'más de {MANY} {words[1]}' if count > MANY else f'{count} {words[0] if count == 1 else words[1]}'


def notice(kinds, events) -> tuple:
    """The whole push: counts by fixed kind, then today's calendar."""
    parts = [_counted(kinds[kind], WORDS[kind]) for kind in WORDS if kinds.get(kind)]
    lines = []
    if parts:
        listed = parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} y {parts[-1]}"
        lines.append(f'Tienes por atender: {listed}.')
    if events:
        lines.append(f'Hoy en tu calendario: {_counted(events, EVENTS)}.')
    return TITLE, ' '.join([*lines, WHERE])


def events_today(connection, now, offset) -> int:
    """How many, and nothing else: no title leaves this call."""
    return len(session.calendar(connection).events(now, 1, offset))


def _count_calendar(connection, now, offset):
    """A number, or None when it could not be counted now."""
    try:
        events = events_today(connection, now, offset)
    except SoftTimeLimitExceeded:
        raise
    except MailRefused as exc:
        if exc.code == 'reconnect' and getattr(exc, 'ended_now', False):
            # The grant ended here, not in a sync: say so, as a sync would have.
            _notify(connection.user, RECONNECT)
        return None
    except Exception as exc:  # noqa: BLE001 - by type only: a message can quote a title
        logger.warning('Calendar count failed: %s', type(exc).__name__)
        return None
    return events


def _calendar_failures(connection, today, add=0) -> int:
    """How often the calendar failed today for this connection; `add` counts one more."""
    key = f'assistant-gmail:calendar-failed:{connection.pk}:{today.isoformat()}'
    try:
        if add:
            cache.add(key, 0, 86400)
            return cache.incr(key)
        return int(cache.get(key) or 0)
    except Exception:  # noqa: BLE001 - no counter: keep trying until the morning ends
        return 0


def nudge(now=None):
    """A notice a day for each person: what the mail brought, plus today's calendar, in their morning.

    One more that day at most, and only for something due today that arrived after the first.
    """
    now = now or timezone.now()
    if not config.configured():
        return 0
    sent, spent = 0, 0.0
    testers = [int(pk) for pk in config.tester_ids()]
    waiting = GmailConnection.objects.select_related('user').filter(
        user_id__in=testers, status=GmailConnection.Status.ACTIVE, consent_version__gte=config.CONSENT_VERSION,
    ).order_by(F('calendar_checked_on').asc(nulls_first=True), 'pk')  # whoever waited longest for a count goes first
    for connection in waiting:
        offset = config.utc_offset(connection.user)
        local = now + timedelta(hours=offset)
        today = local.date()
        first = connection.last_nudge_on != today
        if local.hour not in DAYTIME or not (first or connection.last_urgent_on != today):
            continue
        if not config.user_allowed(connection.user):
            continue
        needs = connection.needs.filter(dismissed=False, notified_at__isnull=True)
        if first:
            # Undated: since the person's yesterday began, so a late or missed sweep loses none.
            since = now - timedelta(hours=local.hour + 24, minutes=local.minute)
            needs = needs.filter(Q(due_date__gte=today, due_date__lte=today + timedelta(days=1))
                                 | Q(due_date__isnull=True, created_at__gte=since))
        else:
            needs = needs.filter(due_date=today)
        found = list(needs.values_list('pk', 'kind'))
        events, checked = 0, {}
        if (first and local.hour in MORNING and connection.can_calendar
                and connection.calendar_checked_on != today):
            counted, gave_up = None, _calendar_failures(connection, today) >= CALENDAR_TRIES
            if not gave_up and spent < CALENDAR_SECONDS:
                began = time.monotonic()
                counted = _count_calendar(connection, now, offset)
                spent += time.monotonic() - began
                if counted is None:
                    gave_up = _calendar_failures(connection, today, add=1) >= CALENDAR_TRIES
            if counted is None and not gave_up and local.hour != MORNING[-1]:
                continue  # the whole notice waits for the next sweep, so the calendar is not left out of it
            events = counted or 0
            if counted is not None:
                # Written with the claim below when there is a notice: a sweep killed in between counts again.
                checked = {'calendar_checked_on': today}
                if not found and not events:
                    GmailConnection.objects.filter(pk=connection.pk, grant=connection.grant).update(**checked)
        if not found and not events:
            continue
        field = 'last_nudge_on' if first else 'last_urgent_on'
        claimed = GmailConnection.objects.filter(
            pk=connection.pk, grant=connection.grant, status=GmailConnection.Status.ACTIVE,
        ).filter(Q(**{f'{field}__isnull': True}) | Q(**{f'{field}__lt': today})).update(**{field: today, **checked})
        if claimed:
            MailNeed.objects.filter(pk__in=[pk for pk, _kind in found]).update(notified_at=now)
            kinds = {}
            for _pk, kind in found:
                kinds[kind] = kinds.get(kind, 0) + 1
            _notify(connection.user, notice(kinds, events))
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
            try:
                oauth.disconnect(connection)
            except SoftTimeLimitExceeded:
                raise
            except Exception as exc:  # noqa: BLE001 - one row must not stop the others, nor the sweep
                logger.warning('Gmail cleanup of %s failed: %s', connection.pk, type(exc).__name__)
    MailNeed.objects.filter(
        Q(due_date__lt=cutoff.date()) | Q(due_date__isnull=True, created_at__lt=cutoff)).delete()
    MailDraft.objects.filter(expires_at__lte=now).delete()
    # Kept a while after expiring: someone who comes back from Google late is still counted (oauth.complete).
    GmailOAuthState.objects.filter(expires_at__lte=now - timedelta(hours=oauth.LATE_HOURS)).delete()
    from assistant import connections
    try:
        for connection in connections.removed_connections()[:10]:
            oauth.disconnect(connection)
        connections.forget_addresses()
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # noqa: BLE001 - the waitlist must not stop the rest of the sweep
        logger.warning('Connections cleanup failed: %s', type(exc).__name__)
