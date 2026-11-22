from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from assistant import conf

READ_SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
SEND_SCOPE = 'https://www.googleapis.com/auth/gmail.send'
CONSENT_VERSION = 1
# Google's own limit for a project in Testing.
MAX_TESTERS = 100


def value(name):
    return str(getattr(settings, name, '') or '').strip()


def configured() -> bool:
    return all(value(name) for name in (
        'GMAIL_OAUTH_CLIENT_ID', 'GMAIL_OAUTH_CLIENT_SECRET', 'GMAIL_OAUTH_REDIRECT_URI', 'GMAIL_TOKEN_KEY'))


def tester_ids() -> set:
    # No '*': the pilot is a named list, capped like Google's.
    ids = [part.strip() for part in value('GMAIL_PILOT_USER_IDS').split(',') if part.strip().isdigit()]
    return set(ids[:MAX_TESTERS])


def user_allowed(user) -> bool:
    if user is None or not getattr(user, 'is_active', False) or getattr(user, 'deleted_at', None):
        return False
    return (bool(conf.get('CONFIO_ASSISTANT_ENABLED')) and configured() and str(user.pk) in tester_ids()
            and not banned(user))


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
