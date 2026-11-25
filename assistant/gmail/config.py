from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from assistant import conf

READ_SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
SEND_SCOPE = 'https://www.googleapis.com/auth/gmail.send'
# Optional on Google's screen: without it the daily notice counts mail only.
CALENDAR_SCOPE = 'https://www.googleapis.com/auth/calendar.events.readonly'
# 2: reads beyond bills, keeps a one-line summary, and reads Google Calendar. The floor for reading at all.
CONSENT_VERSION = 2
# 3: what needs the person is told in the Confío IA conversation, and mail is written and answered there.
# Only a connection accepted under it gets that; one under 2 keeps being read and noticed as before.
CHAT_CONSENT_VERSION = 3
ACCEPTED_CONSENT = (2, 3)  # what an app may connect under: older builds show the text of 2
# Google's own limit for a project in Testing.
MAX_TESTERS = 100


def value(name):
    return str(getattr(settings, name, '') or '').strip()


def configured() -> bool:
    return all(value(name) for name in (
        'GMAIL_OAUTH_CLIENT_ID', 'GMAIL_OAUTH_CLIENT_SECRET', 'GMAIL_OAUTH_REDIRECT_URI', 'GMAIL_TOKEN_KEY'))


def configured_tester_ids() -> list:
    """The owner's own accounts, and the switch: empty = the pilot is off."""
    # No '*': the pilot is a named list, capped like Google's.
    ids = [part.strip() for part in value('GMAIL_PILOT_USER_IDS').split(',') if part.strip().isdigit()]
    return list(dict.fromkeys(ids))[:MAX_TESTERS]


def tester_ids() -> set:
    """The configured accounts plus whoever was given a place from the admin."""
    listed = configured_tester_ids()
    if not listed:
        return set()
    from assistant.connections_models import AssistantConnectionRequest as Request
    given = Request.objects.filter(
        feature=Request.Feature.GMAIL, answer=Request.Answer.YES, invited_at__isnull=False, ready_at__isnull=False,
        removed_at__isnull=True, user__isnull=False,
    ).values_list('user_id', flat=True)
    # Not cut at 100: reserving is what keeps to it, and a new configured id must not drop someone who is in.
    return set(listed) | {str(pk) for pk in given}


def eligible(user) -> bool:
    """Could use the pilot at all, place or not."""
    if user is None or not getattr(user, 'is_active', False) or getattr(user, 'deleted_at', None):
        return False
    return bool(conf.get('CONFIO_ASSISTANT_ENABLED')) and configured() and not banned(user)


def user_allowed(user) -> bool:
    return eligible(user) and (str(user.pk) in tester_ids() or may_take_place(user))


def self_serve() -> bool:
    """The Google project is in (unverified) production: no address has to be typed into its console."""
    return bool(getattr(settings, 'GMAIL_PILOT_SELF_SERVE', False)) and bool(configured_tester_ids())


def had_place(user) -> bool:
    """Given a place once (by hand or self-serve). One taken away is not taken again by connecting."""
    from assistant.connections_models import AssistantConnectionRequest as Request
    return Request.objects.filter(user=user, feature=Request.Feature.GMAIL).filter(
        models.Q(ready_at__isnull=False) | models.Q(removed_at__isnull=False)).exists()


def reserved_place(user) -> bool:
    """Reserved from the admin and not given yet: the place is already counted as theirs."""
    from assistant.connections_models import AssistantConnectionRequest as Request
    return Request.objects.filter(user=user, feature=Request.Feature.GMAIL, invited_at__isnull=False,
                                  ready_at__isnull=True, removed_at__isnull=True).exists()


def holds_place(user) -> bool:
    """Never held back by the count: a member, or a place reserved for them."""
    return str(user.pk) in tester_ids() or reserved_place(user)


def may_take_place(user) -> bool:
    """Self-serve: never had a place, and one is reserved for them, held by their open attempt, or left."""
    if not self_serve() or had_place(user):
        return False
    if reserved_place(user):
        return True
    from assistant import connections
    from .models import GmailOAuthState
    if GmailOAuthState.objects.filter(user=user).exclude(challenge='').exists():
        # Their own attempt holds the place and must not count against them. An expired one still lets
        # them come back, so the account Google counted is recorded (oauth.complete) before the refusal.
        return True
    return connections.seats_left() > 0


def chat_consented(connection) -> bool:
    """Agreed to mail being told and written in the Confío IA conversation."""
    return connection is not None and connection.consent_version >= CHAT_CONSENT_VERSION


def consented(connection) -> bool:
    """Agreed to what is read today. An older agreement covered less: nothing is read under it."""
    return connection is not None and connection.consent_version >= CONSENT_VERSION


def banned(user) -> bool:
    # is_active stays true for a banned person.
    from security.utils import check_user_banned
    return check_user_banned(user)[0]


DEFAULT_OFFSET = -6
# Standard time is close enough for a date.
_OFFSETS = {'AR': -3, 'BR': -3, 'UY': -3, 'PY': -3, 'CL': -3, 'BO': -4, 'VE': -4, 'DO': -4, 'PR': -4, 'CU': -5,
            'CO': -5, 'PE': -5, 'EC': -5, 'PA': -5, 'US': -5, 'ES': 1}


def utc_offset(user) -> int:
    from security.geo import country_of
    try:
        return _OFFSETS.get(country_of(user) or '', DEFAULT_OFFSET)
    except Exception:  # noqa: BLE001 - only a date depends on it
        return DEFAULT_OFFSET


def local_today(now=None, offset=DEFAULT_OFFSET):
    """The person's date. The default (UTC-6, the westernmost) is for hiding what is past."""
    return ((now or timezone.now()) + timedelta(hours=offset)).date()


def allowed(user, account, jwt_context) -> bool:
    return is_personal(account, jwt_context) and user_allowed(user)


def is_personal(account, jwt_context) -> bool:
    return account is not None and (jwt_context or {}).get('account_type') == 'personal'
