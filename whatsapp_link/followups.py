"""Follow-ups for what Confío IA told about WhatsApp, until the next day (founder, 2026-11-26), on the schedule of
assistant.gmail.followups.step. Someone waiting for her reply, an appointment, a payment or something urgent, told
in her conversation (told_at): once about 4 hours later, once more the next morning, then never. Right before, her
chat is checked: a message of hers after it (written on her phone, or sent from Confío's card and kept as hers), a
reply sent or of unknown outcome, or a newer message of that chat that was told and is followed up itself settles
it for good.

Never a burst: per person and run, ONE message with ONE push, at most MAX_NAMED named (the rest are named in a later
one, each after its own check), and at most PER_DAY follow-up messages a day. Only
people with something due now take one of a run's PER_RUN places.
"""
import logging
import time as clock
from datetime import datetime, timedelta, timezone as dt_timezone

from celery.exceptions import SoftTimeLimitExceeded
from django.db.models import F
from django.db.models.functions import Coalesce
from django.utils import timezone

from assistant.gmail.followups import (CANDIDATES, MAX_FOLLOWUPS, MAX_NAMED, PER_DAY, RUN_SECONDS, WINDOW,
                                       posted_today, step, zone_of)

from .models import WhatsAppDraft, WhatsAppInbox, WhatsAppLink, WhatsAppNotice

logger = logging.getLogger(__name__)

KINDS = ('reply', 'appointment', 'payment', 'urgent')
PER_RUN = 60  # people with something due, per run
PUSH_TITLE = 'Pendiente · WhatsApp'
PUSH_WORDS = {
    'reply': '{name} sigue esperando tu respuesta',
    'appointment': 'La cita con {name} sigue pendiente',
    'payment': 'El cobro o pago de {name} sigue pendiente',
    'urgent': 'Lo de {name} sigue pendiente',
}


def _message_time(data, fallback):
    return datetime.fromtimestamp(data['at'], tz=dt_timezone.utc) if data.get('at') else fallback


def answered(link, notice, data) -> bool:
    from . import service
    jid, phone = data.get('jid') or '', data.get('phone') or ''
    if not jid and not phone:
        return False
    since = _message_time(data, notice.created_at)  # the newest message the notice told
    if jid:
        # Hers in that chat, by each message's own time (a row's arrival can lag it, or come from history).
        mine = WhatsAppInbox.objects.filter(link=link, chat_key=service._chat_key(link, jid), from_me=True,
                                            created_at__gte=since - timedelta(days=1)).only('sealed', 'created_at')
        if any(_message_time(service._unseal(row.sealed, {}) or {}, row.created_at) > since for row in mine):
            return True
    # Sent after that message, or of unknown outcome (it may well have gone). One still sending may yet fail.
    sent = WhatsAppDraft.objects.filter(link=link, sending_at__gt=since,
                                        status__in=(WhatsAppDraft.Status.SENT, WhatsAppDraft.Status.UNKNOWN))
    for draft in sent:
        fields = service._unseal(draft.sealed, {})
        if (jid and fields.get('jid') == jid) or (phone and fields.get('phone') == phone):
            return True
    # A newer message of the chat that was told and is followed up itself speaks for it.
    newer = WhatsAppNotice.objects.filter(link=link, created_at__gt=notice.created_at, kind__in=KINDS,
                                          told_at__isnull=False).exclude(pk=notice.pk)
    return bool(jid) and any(service._unseal(other.sealed, {}).get('jid') == jid for other in newer)


def push_words(notices):
    """(title, words) of a follow-up's push: read as a reminder, never as a new message."""
    from . import service
    if len(notices) == 1:
        notice = notices[0]
        name = service._push_name(service._unseal(notice.sealed, {}).get('chat'))
        return PUSH_TITLE, PUSH_WORDS.get(notice.kind, 'Lo de {name} sigue pendiente').format(name=name)
    return PUSH_TITLE, f'{len(notices)} conversaciones siguen pendientes. Te las recuerdo en Confío IA.'


def run(now=None) -> int:
    """One sweep. Returns how many follow-up messages were posted."""
    from . import service
    now = now or timezone.now()
    if not service.enabled():
        return 0
    started = clock.monotonic()
    # Only what was told and is still open; the longest waiting first.
    notices = WhatsAppNotice.objects.select_related('link__user').filter(
        kind__in=KINDS, told_at__isnull=False, told_at__gte=now - WINDOW, resolved_at__isnull=True,
        dismissed=False, followups__lt=MAX_FOLLOWUPS, link__state=WhatsAppLink.State.LINKED,
    ).exclude(link__reason='unlinking').annotate(
        waiting=Coalesce(F('followed_at'), F('told_at'))).order_by('waiting', 'pk')[:CANDIDATES]
    people = {}
    for notice in notices:
        people.setdefault(notice.link_id, []).append(notice)
    posted = places = 0
    for pending in people.values():
        if places >= PER_RUN or clock.monotonic() - started > RUN_SECONDS:
            break
        try:
            due = _due_for(pending, now)
            if not due:
                continue  # nothing due now: takes no place
            places += 1
            posted += _person(pending[0].link, due, now)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:  # noqa: BLE001 - one person never stops the run; logged by type only
            logger.warning('WhatsApp follow-up for link %s failed: %s', pending[0].link_id, type(exc).__name__)
    return posted


def _due_for(pending, now):
    from . import service
    link = pending[0].link
    if link.consent_version < service.CONSENT_VERSION or service.note_pending(link):
        return None
    zone = zone_of(link.user)
    due = [(notice, number) for notice in pending
           if (number := step(notice.told_at, notice.followups, notice.followed_at, now, zone))]
    if not due or posted_today(link.user, 'whatsapp-followup:', now, zone) >= PER_DAY:
        return None  # waits for the next window, or expires: never a burst
    return zone, due


def _person(link, due_for, now) -> int:
    from . import chat, service
    zone, due = due_for
    ready = []
    for notice, number in due:
        if len(ready) == MAX_NAMED:
            break  # the rest are named later, each after its own check
        data = service._unseal(notice.sealed, {})
        if answered(link, notice, data if isinstance(data, dict) else {}):
            WhatsAppNotice.objects.filter(pk=notice.pk, resolved_at__isnull=True).update(resolved_at=now)
            continue
        ready.append((notice, number))
    claimed, posted = [], None
    try:
        # Claimed before it is posted: two sweeps never post the same one. Released if the post does not happen
        # (also when the run is cut between the two).
        for notice, number in ready:
            if WhatsAppNotice.objects.filter(pk=notice.pk, followups=notice.followups, resolved_at__isnull=True,
                                             dismissed=False, link__state=WhatsAppLink.State.LINKED).update(
                    followups=number, followed_at=now):
                claimed.append((notice, number))
        if claimed:
            posted = chat.follow_up(link, claimed, now, zone)
    finally:
        if posted is None:
            for notice, _number in claimed:
                WhatsAppNotice.objects.filter(pk=notice.pk, followed_at=now).update(
                    followups=notice.followups, followed_at=notice.followed_at)
    if posted is None:
        return 0
    if not _still_linked(link):
        chat.erase(link.user)  # unlinked while it was being posted: it goes too
        return 0
    title, words = push_words([notice for notice, _number in claimed])
    service._notify(link.user, words, {'kind': 'messages'}, title=title)
    if not _still_linked(link):
        service._forget_pushes(link.user_id, kind='messages')  # unlinked while it was being told: it goes too
    return 1


def _still_linked(link) -> bool:
    return WhatsAppLink.objects.filter(pk=link.pk, grant=link.grant, state=WhatsAppLink.State.LINKED).exclude(
        reason='unlinking').exists()
