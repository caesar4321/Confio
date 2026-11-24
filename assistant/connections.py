"""How people find out about mail and calendar in the assistant, and what they
see when there is no place for them.

A pure intent probe until there is something to connect: "Próximamente", with
"Sí, avísame" or "Solo miraba". A place is given by hand in two steps, because
Google only lets in addresses typed into its console: reserve() freezes the
address the person typed, the operator adds it in Google, give() opens access.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.db import connection as database, transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from . import conf
from .connections_models import AssistantConnectionRequest as Request
from .gmail import config as gmail, text
from .gmail.models import GmailConnection

logger = logging.getLogger(__name__)
SEATS_LOCK = 77_100_100  # pg advisory lock for reserving places
# A removal takes its clock before it commits: a connect in that gap still counts as before it.
REMOVAL_SLACK = timedelta(minutes=1)
INVITED = ('Tu asistente', 'Ya tienes tu cupo para conectar Gmail. Ábrelo en tu asistente: Correo y calendario.')
NEWS = ('Tu asistente', 'Hay novedades de Correo y calendario. Ábrelo en tu asistente para verlas.')
# A place is one of 100 for life, and only these surely are a Gmail mailbox (any address can be a Google account).
GMAIL_DOMAINS = ('@gmail.com', '@googlemail.com')


class ConnectionRefused(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def discovery_on() -> bool:
    return bool(conf.get('CONFIO_ASSISTANT_ENABLED')) and bool(
        getattr(settings, 'ASSISTANT_CONNECTIONS_DISCOVERY_ENABLED', False))


def seats_used() -> int:
    """Places given here, and the configured accounts. Google's own console has the last word."""
    given = list(Request.objects.filter(
        feature=Request.Feature.GMAIL, invited_at__isnull=False).values_list('user_id', flat=True))
    people = set(gmail.configured_tester_ids()) | {str(pk) for pk in given if pk is not None}
    return len(people) + given.count(None)


def seats_left() -> int:
    # Google's count can be ahead of ours (added by hand, corrected addresses): the owner says when it is full.
    if getattr(settings, 'GMAIL_PILOT_FULL', False):
        return 0
    used = seats_used()
    if gmail.self_serve():
        from .gmail.models import GmailGrant, GmailOAuthState
        # Google counts every account that consented, and anyone on its screen now may become one.
        holders = set(gmail.tester_ids()) | {str(pk) for pk in Request.objects.filter(
            feature=Request.Feature.GMAIL, invited_at__isnull=False, ready_at__isnull=True,
            removed_at__isnull=True).values_list('user_id', flat=True)}
        open_attempts = GmailOAuthState.objects.filter(expires_at__gt=timezone.now()).exclude(
            user_id__in=list(holders)).count()
        used = GmailGrant.objects.count() + used - _counted_by_grant(GmailGrant) + open_attempts
    return max(gmail.MAX_TESTERS - used, 0)


def _counted_by_grant(grant_model) -> int:
    """People with a place whose current mailbox is already a recorded grant: counted once, not twice."""
    given = Request.objects.filter(feature=Request.Feature.GMAIL, invited_at__isnull=False,
                                   user__isnull=False).values_list('user_id', flat=True)
    people = {str(pk) for pk in given} | set(gmail.configured_tester_ids())
    keys = dict(GmailConnection.objects.filter(user_id__in=list(people)).values_list('user_id', 'email_key'))
    recorded = set(grant_model.objects.filter(key__in=list(keys.values())).values_list('key', flat=True))
    return sum(1 for key in keys.values() if key in recorded)


def pilot_open() -> bool:
    return gmail.configured() and bool(gmail.configured_tester_ids())


def login_gmail(user) -> str:
    """Only to prefill the field. Never stored or used unless they send it."""
    login = (getattr(user, 'email', '') or '').strip()
    return login if login.lower().endswith(GMAIL_DOMAINS) else ''


def _gmail_state(user, request):
    """(state, the Google account Google will accept, or '' when we don't hold it)."""
    row = GmailConnection.objects.filter(user=user).first()
    address = request.google_email if request else ''
    if gmail.user_allowed(user):
        if row is None:
            return 'invited', address
        return ('connected' if row.status == GmailConnection.Status.ACTIVE else 'reconnect'), address
    if row is not None:
        return 'paused', ''  # nothing is read; disconnecting still works
    wants = bool(request) and request.answer == Request.Answer.YES
    if request and request.ready_at:
        # Their account is already in Google: no address to ask for again.
        return ('waiting', address) if wants else ('left', '')
    running = pilot_open()
    if request and request.invited_at:
        # Reserved, never added in Google: the place is theirs, full or not, but it needs an address.
        if wants:
            return ('request', '') if running and not address else ('waiting', address)
        return ('request' if running else 'soon'), ''
    full = running and seats_left() == 0
    if wants:
        if full:
            return 'waiting_full', ''
        if running and not address:
            return 'request', ''  # they said yes before places opened: now they choose the account
        return 'waiting', address
    if not running:
        return 'soon', ''
    return ('full' if full else 'request'), ''


def overview(user, account, jwt_context):
    """None = show nothing."""
    if not gmail.is_personal(account, jwt_context):
        return None
    if not discovery_on() and not gmail.user_allowed(user):
        return None
    asked = {row.feature: row for row in Request.objects.filter(user=user)}
    mail, calendar = asked.get(Request.Feature.GMAIL), asked.get(Request.Feature.CALENDAR)
    state, address = _gmail_state(user, mail)
    return {
        'gmail': state,
        'gmail_answered': (
            mail is not None and not (state == 'request' and mail.answer == Request.Answer.YES)
            # A configured account has no place to decline: it is the owner's own.
            and not (state == 'invited' and str(user.pk) in gmail.configured_tester_ids())),
        'google_email': address or None,
        'suggested_email': login_gmail(user) or None,
        'calendar': 'waiting' if calendar and calendar.answer == Request.Answer.YES else 'soon',
        'calendar_answered': calendar is not None,
    }


def answer(user, account, jwt_context, feature, wants, google_email=''):
    if not gmail.is_personal(account, jwt_context) or not (discovery_on() or gmail.user_allowed(user)):
        raise ConnectionRefused('Esto todavía no está disponible.')
    if feature not in Request.Feature.values:
        raise ConnectionRefused('No pude guardar tu respuesta.')
    with transaction.atomic():
        row = Request.objects.select_for_update().filter(user=user, feature=feature).first()
        address = ''
        spent = bool(row and row.invited_at)
        # Frozen: in Google already, or reserved for the operator to type there.
        frozen = bool(row and (row.ready_at or (spent and not row.removed_at and row.google_email)))
        # An address is asked only while a place can be given. Until then it is just an answer.
        if (wants and feature == Request.Feature.GMAIL and not frozen and pilot_open()
                and (spent or seats_left() > 0)):
            address = (google_email or '').strip()
            if len(address) > 254 or not text.ADDRESS.fullmatch(address):
                raise ConnectionRefused('Escribe el Gmail que quieres conectar.')
            if not _is_gmail(address):
                raise ConnectionRefused('Por ahora solo se puede con una dirección @gmail.com.')
        chosen = Request.Answer.YES if wants else Request.Answer.NO
        if row is None:
            row, created = Request.objects.select_for_update().get_or_create(
                user=user, feature=feature, defaults={'answer': chosen, 'google_email': address})
            if created:
                return
            spent = bool(row.invited_at)
            frozen = bool(row.ready_at or (spent and not row.removed_at and row.google_email))
        now = timezone.now()
        if wants and row.answer != Request.Answer.YES:
            row.asked_at = now  # the queue starts at their first yes
        row.answer = chosen
        if not wants:
            row.google_email = ''
            if spent:
                row.removed_at = row.removed_at or now  # access ends; the place stays spent
        elif not frozen:
            row.google_email = address
            if spent and address:
                row.removed_at = row.removed_at or now  # a new address is reserved again before it is given
        # (A frozen address is the one typed into Google's console.)
        row.save(update_fields=['answer', 'google_email', 'asked_at', 'removed_at'])


def _can_have_a_place(row) -> bool:
    user = row.user
    return (user is not None and row.answer == Request.Answer.YES and user.is_active and not user.deleted_at
            and not gmail.banned(user))


def can_reserve(row) -> bool:
    return bool(_can_have_a_place(row) and not row.ready_at and _is_gmail(row.google_email)
                and (not row.invited_at or row.removed_at))


def can_give(row) -> bool:
    return bool(_can_have_a_place(row) and row.invited_at and not row.ready_at and not row.removed_at
                and _is_gmail(row.google_email))


def can_return(row) -> bool:
    return bool(_can_have_a_place(row) and row.ready_at and row.removed_at)


def _is_gmail(address) -> bool:
    return address.lower().endswith(GMAIL_DOMAINS)


def can_undo(row) -> bool:
    """Reserved and never given. Whether it reached Google's console only the operator knows."""
    return bool(row.invited_at and not row.ready_at)


def as_shown(row) -> str:
    """What a confirmation page binds: the latest reservation or removal, and this address."""
    moment = row.removed_at or row.invited_at
    reservation = moment.strftime('%Y%m%d%H%M%S%f') if moment else '0'
    return f'{reservation}:{row.google_email}'


def _unchanged(row, seen) -> bool:
    """seen = {pk: as_shown(row) on the page}. Changed since = not what was confirmed."""
    return seen is None or seen.get(row.pk) == as_shown(row)


def reserve(request_ids, seen=None, log=None) -> dict:
    """Step 1: the place is taken and the address freezes. No access, no notice. Never past 100.

    log(row) writes who did it, in the same transaction: no change without its record.
    """
    counts = {'reserved': 0, 'skipped': 0, 'no_seat': 0}
    rows = Request.objects.filter(pk__in=list(request_ids), feature=Request.Feature.GMAIL)
    if not pilot_open():
        counts['skipped'] = rows.count()
        return counts
    with transaction.atomic():
        with database.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [SEATS_LOCK])
        left, now = seats_left(), timezone.now()
        configured = gmail.configured_tester_ids()
        for row in rows.select_for_update(of=('self',)).order_by('asked_at', 'pk'):
            spent = bool(row.invited_at)
            if not can_reserve(row) or not _unchanged(row, seen):
                counts['skipped'] += 1
                continue
            costs = not spent and str(row.user_id) not in configured
            if costs and left <= 0:
                counts['no_seat'] += 1
                continue
            left -= costs
            row.invited_at, row.removed_at = row.invited_at or now, None
            row.save(update_fields=['invited_at', 'removed_at'])
            if log:
                log(row)
            counts['reserved'] += 1
    return counts


def undo_reserve(request_ids, seen=None, log=None) -> dict:
    """A place reserved by mistake whose address NEVER went into Google's console: free again.

    The one way invited_at is cleared. Never after give(): ready_at is the proof it is in Google.
    """
    counts = {'undone': 0, 'skipped': 0}
    with transaction.atomic():
        rows = Request.objects.filter(pk__in=list(request_ids), feature=Request.Feature.GMAIL)
        for row in rows.select_for_update(of=('self',)):
            if not can_undo(row) or not _unchanged(row, seen):
                counts['skipped'] += 1
                continue
            row.invited_at = row.removed_at = None
            row.save(update_fields=['invited_at', 'removed_at'])
            if log:
                log(row)
            counts['undone'] += 1
    return counts


def give(request_ids, seen=None, log=None) -> dict:
    """Step 2, AFTER that address was added in Google's console: access, and the notice.

    Never for someone removed: selecting the whole queue must not let them back in.
    """
    return _open_access(request_ids, lambda row: can_give(row) and _unchanged(row, seen), log)


def give_back(request_ids, seen=None, log=None) -> dict:
    """Someone who had access and was removed or left, and says yes: no new place, no console step."""
    return _open_access(request_ids, lambda row: can_return(row) and _unchanged(row, seen), log)


def _open_access(request_ids, due, log=None) -> dict:
    counts = {'given': 0, 'skipped': 0}
    rows = Request.objects.filter(pk__in=list(request_ids), feature=Request.Feature.GMAIL)
    if not pilot_open():
        counts['skipped'] = rows.count()
        return counts
    told = []
    with transaction.atomic():
        now = timezone.now()
        for row in rows.select_for_update(of=('self',)):
            if not due(row) or not _can_have_a_place(row):
                counts['skipped'] += 1
                continue
            row.ready_at, row.removed_at, row.notified_at = row.ready_at or now, None, now
            row.save(update_fields=['ready_at', 'removed_at', 'notified_at'])
            if log:
                log(row)
            told.append(row.user)
            counts['given'] += 1
    for user in told:
        _notify(user, INVITED)
    return counts


def tell_waiting(request_ids) -> int:
    """Keeps "Te avisamos": places opened, or it opened to everyone. Nothing personal in the notice."""
    rows = Request.objects.filter(
        pk__in=list(request_ids), answer=Request.Answer.YES,
        user__is_active=True, user__deleted_at__isnull=True).select_related('user')
    # Everyone who reads "En la lista", a spent place included. Not who already has Gmail (self-serve can still come in).
    members = gmail.tester_ids()
    waiting = [row for row in rows if row.feature != Request.Feature.GMAIL or str(row.user_id) not in members]
    people = {row.user.pk: row.user for row in waiting}
    Request.objects.filter(pk__in=[row.pk for row in waiting]).update(notified_at=timezone.now())
    for user in people.values():
        _notify(user, NEWS)
    return len(people)


def remove(request_ids, log=None) -> int:
    """Takes access away and erases the connection. The place stays spent."""
    from .gmail import oauth

    rows = Request.objects.filter(pk__in=list(request_ids), feature=Request.Feature.GMAIL,
                                  invited_at__isnull=False, removed_at__isnull=True)
    # A configured account keeps access whatever is done here: not counted as removed.
    rows = rows.exclude(user_id__in=gmail.configured_tester_ids())
    with transaction.atomic():
        changed = list(rows.select_for_update(of=('self',)))
        done = Request.objects.filter(pk__in=[row.pk for row in changed]).update(
            removed_at=timezone.now(), google_email='')
        if log:
            for row in changed:
                log(row)
    people = [row.user_id for row in changed if row.user_id]
    for row in GmailConnection.objects.filter(user_id__in=people):
        oauth.disconnect(row)
    return done


def removed_connections():
    """Connections that outlived their place (they left, a removal was cut short): for the sweep to erase."""
    # Removed after connecting. A configured account that connected later is only paused by the switch.
    gone = Request.objects.filter(
        feature=Request.Feature.GMAIL, user_id=OuterRef('user_id'), removed_at__gte=OuterRef('connected_at') - REMOVAL_SLACK)
    return GmailConnection.objects.filter(Exists(gone)).exclude(user_id__in=gmail.configured_tester_ids())


def forget_addresses() -> int:
    """An address is for giving a place: gone once connected, with the account, or when a running pilot is full.

    With the pilot off it stays, for whoever is waiting. The Gmail privacy draft says so (a limit is a question for counsel).
    """
    from security.models import UserBan

    banned = UserBan.objects.filter(deleted_at__isnull=True).exclude(
        ban_type='temporary', expires_at__lt=timezone.now()).values('user_id')
    unneeded = (Q(user__isnull=True) | Q(user__deleted_at__isnull=False) | Q(user__is_active=False)
                | Q(user__in=banned) | Q(user__in=GmailConnection.objects.values('user_id')))
    if pilot_open() and seats_left() == 0:
        unneeded |= Q(invited_at__isnull=True)
    return Request.objects.exclude(google_email='').filter(unneeded).update(google_email='')


def _notify(user, words):
    try:
        from notifications.models import NotificationType
        from notifications.utils import create_notification
        create_notification(user=user, notification_type=NotificationType.SYSTEM, title=words[0], message=words[1],
                            data={'type': 'assistant_connections'})
    except Exception as exc:  # noqa: BLE001
        logger.warning('Connections notice failed: %s', type(exc).__name__)
