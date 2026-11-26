"""Follow-ups for what Confío IA told about her Gmail, until the next day (founder, 2026-11-26).

Someone waiting for her reply, or an appointment: once about 4 hours after it was told (in her daytime), once more
the next morning, then never. A payment or deadline with a date: once on the morning it is due. Only what was told
in her conversation (told_at) is followed up, named as it was shown then (chat.tell keeps the sender and subject):
the mail's text is never read again. Right before, Gmail is asked only for labels and dates (format=minimal): for
a reply or an appointment, of its whole thread (under the thread consent), and a reply she sent there (from Gmail
or from Confío's card) settles it for good, as a dismissal does; for a payment, of that mail, to know it is still
there. A failed read posts nothing and waits an hour.

Never a burst: per person and run, ONE message with ONE push, at most MAX_NAMED named (the rest are named in a later
one, each after its own check), and at most PER_DAY follow-up messages a day. Only
people with something due now take one of a run's PER_RUN places.

WhatsApp's notices follow the same schedule (whatsapp_link.followups uses `step`, `zone_of` and `when_words`).
"""
import logging
import time as clock
from datetime import datetime, time, timedelta, timezone as dt_timezone

from celery.exceptions import SoftTimeLimitExceeded
from django.core.cache import cache
from django.db.models import F, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from . import config, crypto, limits, session
from .errors import GmailError, MailRefused
from .models import GmailConnection, MailNeed

logger = logging.getLogger(__name__)

FIRST_AFTER = timedelta(hours=4)
WINDOW = timedelta(hours=36)  # nothing told longer ago than this is followed up
DAYTIME = range(7, 22)
MORNING = range(7, 11)
MAX_FOLLOWUPS = 2
REPLY_KINDS = ('reply', 'appointment')
DUE_KINDS = ('payment', 'deadline')
PER_DAY = 2      # follow-up messages per person per day, for each of Gmail and WhatsApp
MAX_NAMED = 3    # items named (and claimed) in one follow-up message
PER_RUN = 40     # people with something due, per run
CANDIDATES = 2000
RUN_SECONDS = 70  # of the task's 100: what is left waits for the next run
COOLDOWN = 3600  # seconds a need waits after a failed Gmail read


def zone_of(user):
    """The person's clock, as Confío IA's own (Viewer.tz): the zone her phone last gave us (a call's), else her
    country's; the country's standard offset only when neither is known."""
    try:
        from security.geo import country_of
        from users.cashflow import TIMEZONE_BY_PHONE_COUNTRY, resolve_timezone

        from assistant.models import VoiceSession
        country = (country_of(user) or '').upper()
        device = VoiceSession.objects.filter(user=user).exclude(tz_name='').order_by('-started_at').values_list(
            'tz_name', flat=True).first()
        if device or TIMEZONE_BY_PHONE_COUNTRY.get(country):
            zone = resolve_timezone(device, country)
            if str(zone) != 'UTC' or device == 'UTC':
                return zone
    except Exception:  # noqa: BLE001 - the fallback below is a clock too
        logger.warning('Follow-up zone unknown', exc_info=True)
    return dt_timezone(timedelta(hours=config.utc_offset(user)))


def step(told_at, followups, followed_at, now, zone) -> int:
    """Which follow-up is due now (1 or 2), or 0, on the person's clock (`zone`)."""
    if told_at is None or followups >= MAX_FOLLOWUPS or now - told_at > WINDOW:
        return 0
    local = now.astimezone(zone)
    if followups == 0:
        return 1 if now - told_at >= FIRST_AFTER and local.hour in DAYTIME else 0
    if followed_at is None:
        return 0
    return 2 if local.date() > followed_at.astimezone(zone).date() and local.hour in MORNING else 0


def when_words(then, now, zone) -> str:
    """«hace 4 h», «ayer», «anteayer», «hace 3 días»: by her calendar days, not by 24 hours."""
    days = (now.astimezone(zone).date() - then.astimezone(zone).date()).days
    if days <= 0:
        return f'hace {max(1, int((now - then).total_seconds() // 3600))} h'
    return {1: 'ayer', 2: 'anteayer'}.get(days, f'hace {days} días')


def posted_today(user, prefix, now, zone) -> int:
    """Follow-up messages of one kind (`prefix`, e.g. 'gmail-followup:') posted on her calendar day."""
    from inbox.models import SupportMessage
    midnight = datetime.combine(now.astimezone(zone).date(), time.min, tzinfo=zone)
    return SupportMessage.objects.filter(conversation__user=user, metadata__notice__startswith=prefix,
                                         created_at__gte=midnight).count()


def resolve(need, now=None):
    MailNeed.objects.filter(pk=need.pk, resolved_at__isnull=True).update(resolved_at=now or timezone.now())


def run(now=None) -> int:
    """One sweep. Returns how many follow-up messages were posted."""
    now = now or timezone.now()
    if not config.configured():
        return 0
    started = clock.monotonic()
    due_range = ((now - timedelta(days=1)).date(), (now + timedelta(days=1)).date())
    # Only what was told and is still open; the longest waiting first.
    needs = MailNeed.objects.select_related('connection__user').filter(
        told_at__isnull=False, resolved_at__isnull=True, dismissed=False,
        connection__status=GmailConnection.Status.ACTIVE,
    ).filter(Q(kind__in=REPLY_KINDS, followups__lt=MAX_FOLLOWUPS, told_at__gte=now - WINDOW)
             | Q(kind__in=DUE_KINDS, followups=0, due_date__range=due_range)
             ).annotate(waiting=Coalesce(F('followed_at'), F('told_at'))).order_by('waiting', 'pk')[:CANDIDATES]
    people = {}
    for need in needs:
        people.setdefault(need.connection_id, []).append(need)
    posted = places = 0
    for pending in people.values():
        if places >= PER_RUN or clock.monotonic() - started > RUN_SECONDS:
            break
        try:
            due = _due_for(pending, now)
            if not due:
                continue  # nothing due now: takes no place
            places += 1
            posted += _person(pending[0].connection, due, now)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - one person never stops the run; logged by type only
            logger.warning('Gmail follow-up for connection %s failed: %s', pending[0].connection_id,
                           type(exc).__name__)
    return posted


def _due_for(pending, now):
    """(zone, [(need, number)]) of what is due now for this person, or None. No Gmail call."""
    connection = pending[0].connection
    user = connection.user
    if not (config.user_allowed(user) and config.consented(connection) and config.chat_consented(connection)):
        return None
    zone = zone_of(user)
    local = now.astimezone(zone)
    threads = config.thread_consented(connection)
    due = []
    for need in pending:
        if cache.get(f'gmail-followup-wait:{need.pk}'):
            continue
        if need.kind in DUE_KINDS:
            # Told this very day: that is today's word on it.
            if (need.due_date == local.date() and local.hour in MORNING
                    and need.told_at.astimezone(zone).date() != local.date()):
                due.append((need, 1))
        elif threads:  # no thread read without that consent, and never a guessed follow-up
            if number := step(need.told_at, need.followups, need.followed_at, now, zone):
                due.append((need, number))
    if not due or posted_today(user, 'gmail-followup:', now, zone) >= PER_DAY:
        return None  # waits for the next window, or expires: never a burst
    return zone, due


def _abouts(needs):
    """need pk → the sender-and-subject mark its told post carries (chat._about)."""
    from inbox.models import SupportMessage
    tags = {f'gmail-need:{need.pk}': need.pk for need in needs}
    found = SupportMessage.objects.filter(conversation__user_id=needs[0].connection.user_id,
                                          metadata__notice__in=list(tags)).values_list('metadata__notice',
                                                                                       'metadata__mail_about')
    return {tags[tag]: about for tag, about in found if about}


def _same_mail_settled(need, about, now, zone) -> bool:
    """Another need for the same mail (as told) that she dismissed, or that was already reminded today."""
    from inbox.models import SupportMessage
    if not about:
        return False
    others = [str(tag).split(':', 1)[1] for tag in SupportMessage.objects.filter(
        conversation__user_id=need.connection.user_id, metadata__mail_about=about,
        metadata__notice__startswith='gmail-need:').values_list('metadata__notice', flat=True)]
    midnight = datetime.combine(now.astimezone(zone).date(), time.min, tzinfo=zone)
    return MailNeed.objects.filter(connection=need.connection, pk__in=[pk for pk in others if pk.isdigit()]).exclude(
        pk=need.pk).filter(Q(dismissed=True) | Q(followed_at__gte=midnight)).exists()


def _newer_in_thread(connection, now):
    """thread → the newest told, open reply or appointment need of it (chat.tell keeps the thread): an older need of
    the same thread is spoken for by the newer one."""
    newest = {}
    for need in MailNeed.objects.filter(connection=connection, kind__in=REPLY_KINDS, told_at__isnull=False,
                                        resolved_at__isnull=True, dismissed=False,
                                        told_at__gte=now - WINDOW).order_by('told_at', 'pk'):
        thread = crypto.unseal(need.sealed).get('thread')
        if thread:
            newest[thread] = need.pk
    return newest


def _person(connection, due_for, now) -> int:
    zone, due = due_for
    user = connection.user
    abouts = _abouts([need for need, _number in due])
    newest = _newer_in_thread(connection, now)
    ready, seen_about, threads, box = [], set(), {}, None
    for need, number in due:
        if len(ready) == MAX_NAMED:
            break  # the rest are named later, each after its own check
        about = abouts.get(need.pk)
        if about and about in seen_about:
            continue  # the same mail, told twice: once is enough
        if need.kind in REPLY_KINDS:
            told_thread = crypto.unseal(need.sealed).get('thread')
            if told_thread and newest.get(told_thread, need.pk) != need.pk:
                resolve(need, now)  # a newer mail of this thread was told: that one is followed up
                continue
        if need.kind in DUE_KINDS and _same_mail_settled(need, about, now, zone):
            resolve(need, now)
            continue
        try:
            limits.claim(user, 'followup')  # its own count: never the person's questions'
            box = box or session.mailbox(connection)
            marks = box.message_marks(crypto.unseal(need.sealed)['id'])
            if 'TRASH' in marks['labelIds'] or 'SPAM' in marks['labelIds']:
                resolve(need, now)  # she threw it away
                continue
            if need.kind in REPLY_KINDS:
                thread = marks.get('threadId')
                after = int(marks.get('internalDate') or 0)
                if thread and any('SENT' in m['labelIds'] and int(m.get('internalDate') or 0) > after
                                  for m in box.thread_marks(thread)):
                    resolve(need, now)
                    continue
                if thread in threads:
                    # Two needs of one thread in this run: the newer one speaks for it, the older is settled.
                    older = threads[thread]
                    resolve(older, now)
                    ready = [(n, k) for n, k in ready if n.pk != older.pk]
                threads[thread] = need
        except MailRefused as exc:
            logger.info('Gmail follow-up %s skipped: %s', need.pk, exc.code)
            if exc.code == 'rate_limited':
                break
            return 0  # the connection itself: nothing for this person now
        except GmailError as exc:
            # Never a guessed follow-up: nothing is posted, and this one waits an hour before it is read again.
            cache.set(f'gmail-followup-wait:{need.pk}', 1, COOLDOWN)
            logger.info('Gmail follow-up %s skipped: %s', need.pk, exc.status)
            if exc.status == 404:
                resolve(need, now)  # the mail is gone from her Gmail: nothing to follow up
            continue
        if about:
            seen_about.add(about)
        ready.append((need, number))
    from . import chat
    claimed, posted = [], None
    try:
        # Claimed before it is posted: two sweeps never post the same one. Released if the post does not happen
        # (also when the run is cut between the two).
        for need, number in ready:
            if MailNeed.objects.filter(pk=need.pk, followups=need.followups, resolved_at__isnull=True,
                                       dismissed=False).update(
                    followups=number if need.kind in REPLY_KINDS else MAX_FOLLOWUPS, followed_at=now):
                claimed.append((need, number))
        if claimed:
            posted = chat.follow_up(connection, claimed)
    finally:
        if posted is None:
            for need, _number in claimed:
                MailNeed.objects.filter(pk=need.pk, followed_at=now).update(followups=need.followups,
                                                                             followed_at=need.followed_at)
    if posted is None:
        return 0
    chat.push_follow_up(connection, len(claimed))
    return 1
