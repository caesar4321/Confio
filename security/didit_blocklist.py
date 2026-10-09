"""Didit face blocklist for permanently banned accounts.

A ban stops an account, not a person: the same person can come back with a
new Google/Apple account and a different document (banned with the cédula,
back with the passport), which no document-number match catches. Didit's 1:N
face search checks every new verification against its face blocklist and
declines a match (FACE_IN_BLOCKLIST), whatever document is presented.

So each verified personal Didit session of a permanently banned user (and each
rejected one whose liveness Didit approved) goes on the face blocklist
(Lists API, reference_session_id), and comes off when the ban is lifted. Only the face: a reused document is already a review hold
(security/identity_reuse.py), not a decline. Temporary and partial bans
(trading, withdrawal) are not blocklisted.

Each ban change queues sync_face_blocklist; reconcile_face_blocklist runs
hourly for whatever that missed. Both are idempotent.
"""
import hashlib
import logging
from urllib.parse import urljoin, urlsplit

import requests
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from .didit import DIDIT_TIMEOUT_SECONDS, DiditAPIError, _didit_headers, _didit_url
from .models import DiditFaceBlocklistEntry, IdentityVerification, UserBan

logger = logging.getLogger(__name__)

COMMENT = 'Confío: cuenta suspendida de forma permanente'


def _call(method, path, payload=None, *, missing_ok=False):
    """Didit Management API call. {} for an empty body (DELETE answers 204),
    and for a 404 when missing_ok (an entry someone already removed)."""
    try:
        response = requests.request(method, _didit_url(path), headers=_didit_headers(), json=payload,
                                    timeout=DIDIT_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise DiditAPIError(f'Didit {method} {path} failed ({type(exc).__name__})') from None
    if missing_ok and response.status_code == 404:
        return {}
    if response.status_code >= 400:
        raise DiditAPIError(f'Didit {method} {path} answered HTTP {response.status_code}')
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        raise DiditAPIError(f'Didit {method} {path} returned invalid JSON') from None


def _all_rows(path, *, missing_ok=False):
    """Read all pages before callers mutate entries; never send credentials
    to a pagination URL outside the original Didit endpoint."""
    endpoint = urlsplit(_didit_url(path))
    seen = set()
    rows = []
    while path:
        if path in seen or len(seen) >= 1000:
            raise DiditAPIError('Didit list pagination did not terminate')
        seen.add(path)
        data = _call('GET', path, missing_ok=missing_ok)
        if missing_ok and data == {}:
            return rows
        page = data.get('results') if isinstance(data, dict) else data
        if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
            raise DiditAPIError('Didit returned an invalid list page')
        rows.extend(page)
        next_url = data.get('next') if isinstance(data, dict) else None
        if not next_url:
            break
        if not isinstance(next_url, str):
            raise DiditAPIError('Didit returned invalid pagination')
        next_page = urlsplit(urljoin(_didit_url(path), next_url))
        if (next_page.scheme, next_page.netloc, next_page.path) != (
                endpoint.scheme, endpoint.netloc, endpoint.path) or next_page.fragment:
            raise DiditAPIError('Didit pagination left the original endpoint')
        path = next_page.path + ('?' + next_page.query if next_page.query else '')
    return rows


def face_blocklist_uuid() -> str:
    """The application's face blocklist: system-provisioned, one per entry type."""
    rows = _all_rows('/v3/lists/?list_type=blocklist&entry_type=face')
    for row in rows or []:
        if isinstance(row, dict) and row.get('list_type', 'blocklist') == 'blocklist' \
                and row.get('entry_type', 'face') == 'face' and row.get('uuid'):
            return str(row['uuid'])
    raise DiditAPIError('Didit has no face blocklist for this application')


def blocks_face(user_id) -> bool:
    """A live permanent ban (a lifted ban is soft-deleted)."""
    return UserBan.objects.filter(user_id=user_id, ban_type='permanent').filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())).exists()


def _verified_sessions(user_id) -> set[str]:
    """Didit sessions of the user's personal documents whose face can be blocked:
    verified ones, and rejected ones whose liveness Didit approved (e.g. a
    session Confío rejected after the fact because someone else held the phone).
    Without that, a banned ring member whose KYC was rejected could come back
    with another document. Approved liveness only: a failed or unreviewed one
    may be a photo of someone else, whose face must never be blocked."""
    rows = IdentityVerification.all_objects.filter(user_id=user_id, status__in=('verified', 'rejected')).filter(
        Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'),
    ).values_list('status', 'risk_factors')
    sessions = set()
    for status, factors in rows:
        didit = (factors or {}).get('didit') or {}
        session_id = didit.get('session_id')
        if not session_id:
            continue
        if status == 'rejected':
            checks = (didit.get('session') or {}).get('liveness_checks')
            if not isinstance(checks, list) or not checks or not all(
                    isinstance(check, dict) and str(check.get('status') or '').strip().lower() == 'approved'
                    for check in checks):
                continue
        sessions.add(str(session_id))
    return sessions


def _label(user_id) -> str:
    return f'confio-user-{user_id}'


def _remove_untracked(user_id, list_uuids) -> None:
    """Entries with this user's label that no row tracks: an add Didit carried
    out whose answer never arrived. Only for a user who is not banned."""
    label = _label(user_id)
    for list_uuid in sorted(set(list_uuids) or {face_blocklist_uuid()}):
        rows = _all_rows(f'/v3/lists/{list_uuid}/entries/?search={label}', missing_ok=True)
        for row in rows or []:
            if isinstance(row, dict) and row.get('display_label') == label and row.get('uuid'):
                _call('DELETE', f"/v3/lists/{list_uuid}/entries/{row['uuid']}/", missing_ok=True)
                logger.info('Untracked face blocklist entry removed: user=%s entry=%s', user_id, row['uuid'])


def sync_face_blocklist(user_id) -> None:
    from django.contrib.auth import get_user_model
    failure = None
    with transaction.atomic():
        # One sync per user at a time: never two entries for one session. Its
        # own advisory lock, not the user's row: Didit calls can take a while,
        # and withdrawals lock that row.
        if connection.vendor == 'postgresql':
            lock_id = int.from_bytes(hashlib.sha256(f'face-blocklist:{user_id}'.encode()).digest()[:8],
                                     'big', signed=True)
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(%s)', [lock_id])
        else:
            get_user_model().all_objects.select_for_update().filter(pk=user_id).first()
        active = list(DiditFaceBlocklistEntry.objects.filter(user_id=user_id, removed_at__isnull=True))
        if blocks_face(user_id):
            missing = _verified_sessions(user_id) - {entry.session_id for entry in active}
            if not missing:
                return
            list_uuid = face_blocklist_uuid()
            for session_id in sorted(missing):
                try:
                    created = _call('POST', f'/v3/lists/{list_uuid}/entries/', {
                        'reference_session_id': session_id,
                        'display_label': _label(user_id),
                        'comment': COMMENT,
                        'metadata': {'reference_type': 'vendor_user', 'confio_user_id': user_id},
                    })
                    entry_uuid = created.get('uuid') or created.get('id') if isinstance(created, dict) else None
                    if not isinstance(entry_uuid, str) or not entry_uuid or len(entry_uuid) > 64:
                        raise DiditAPIError('Didit did not return a valid blocklist entry id')
                except DiditAPIError as exc:
                    # Keep the entries Didit already created: rolling their
                    # rows back would leave them on Didit untracked, never
                    # removed when the ban is lifted. One session Didit refuses
                    # must not keep the others off the blocklist.
                    failure = failure or exc
                    continue
                DiditFaceBlocklistEntry.objects.create(user_id=user_id, session_id=session_id,
                                                       list_uuid=list_uuid, entry_uuid=entry_uuid)
                logger.info('Face blocklisted: user=%s session=%s', user_id, session_id)
        else:
            for entry in active:
                try:
                    _call('DELETE', f'/v3/lists/{entry.list_uuid}/entries/{entry.entry_uuid}/', missing_ok=True)
                except DiditAPIError as exc:
                    failure = failure or exc
                    continue
                entry.removed_at = timezone.now()
                entry.save(update_fields=['removed_at'])
                logger.info('Face blocklist entry removed: user=%s session=%s', user_id, entry.session_id)
            # Only someone once banned permanently can have an untracked entry.
            if UserBan.all_objects.filter(user_id=user_id, ban_type='permanent').exists():
                try:
                    _remove_untracked(user_id, {entry.list_uuid for entry in active})
                except DiditAPIError as exc:
                    failure = failure or exc
    if failure is not None:
        raise failure


FACE_IN_BLOCKLIST = 'FACE_IN_BLOCKLIST'
AUTO_BAN_LOOKBACK_DAYS = 7


def blocklisted_sessions_matched(decision) -> set[str]:
    """Blocklisted sessions a Didit decision confirmed the face against.
    Only Didit's confirmed match (FACE_IN_BLOCKLIST), never a POSSIBLE_*."""
    matched = set()
    for key in ('liveness_checks', 'face_matches'):
        items = (decision or {}).get(key)
        for item in items if isinstance(items, list) else []:
            for warning in (item or {}).get('warnings') or []:
                if isinstance(warning, dict) and warning.get('risk') == FACE_IN_BLOCKLIST:
                    session_id = (warning.get('additional_data') or {}).get('blocklisted_session_id')
                    if session_id:
                        matched.add(str(session_id))
    return matched


def ban_if_face_blocklisted(verification):
    """A new account showing the face of a permanently banned person is that
    person back: ban it too, the way staff did by hand (Lucas Martins De
    Souza, 2026-10-06/09). Only when the match is one of OUR entries whose
    user is still banned, so a lifted ban or an unknown entry never bans."""
    from django.contrib.auth import get_user_model
    from django.db.models import F
    didit = (verification.risk_factors or {}).get('didit') or {}
    matched = blocklisted_sessions_matched(didit.get('session'))
    if not matched:
        return None
    user_id = verification.user_id
    sources = set(DiditFaceBlocklistEntry.objects.filter(session_id__in=matched, removed_at__isnull=True)
                  .exclude(user_id=user_id).values_list('user_id', flat=True))
    banned_sources = sorted(uid for uid in sources if blocks_face(uid))
    if not banned_sources:
        return None
    User = get_user_model()
    with transaction.atomic():
        user = User.all_objects.select_for_update().filter(pk=user_id).first()
        # Live: nothing to do. Lifted: staff decided, never re-ban it.
        if user is None or UserBan.all_objects.filter(user_id=user_id, ban_type='permanent').exists():
            return None
        ban = UserBan.objects.create(
            user=user, ban_type='permanent', reason='multiple_accounts',
            reason_details=(
                f'Restricción automática {timezone.now():%Y-%m-%d}. Observado en nuestros registros: la '
                f"verificación de identidad (sesión Didit {didit.get('session_id') or '-'}) coincidió con el "
                f"rostro de la(s) cuenta(s) restringida(s) de forma permanente {', '.join(map(str, banned_sources))}."))
        User.all_objects.filter(pk=user_id).update(is_active=False, auth_token_version=F('auth_token_version') + 1)
    logger.warning('Auto-banned: user=%s face matches permanently banned %s (session=%s)',
                   user_id, banned_sources, didit.get('session_id'))
    return ban


def auto_ban_face_blocklisted() -> int:
    """Hourly safety net for decisions whose immediate auto-ban failed."""
    from datetime import timedelta
    since = timezone.now() - timedelta(days=AUTO_BAN_LOOKBACK_DAYS)
    banned = 0
    for verification in IdentityVerification.all_objects.filter(
            created_at__gte=since, risk_factors__didit__session__isnull=False).iterator():
        try:
            banned += bool(ban_if_face_blocklisted(verification))
        except Exception:
            logger.exception('Face blocklist auto-ban failed: verification=%s', verification.pk)
    return banned


LIFTED_CLEANUP_DAYS = 7


def reconcile_face_blocklist() -> int:
    """Sync every user with a live permanent ban or an active entry, and for
    LIFTED_CLEANUP_DAYS every user whose permanent ban was lifted or expired
    (an untracked entry has no row to keep them listed). Returns how many
    failed (retried on the next run)."""
    from datetime import timedelta
    auto_ban_face_blocklisted()
    now = timezone.now()
    banned = set(UserBan.objects.filter(ban_type='permanent').filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)).values_list('user_id', flat=True))
    listed = set(DiditFaceBlocklistEntry.objects.filter(removed_at__isnull=True).values_list('user_id', flat=True))
    since = now - timedelta(days=LIFTED_CLEANUP_DAYS)
    lifted = set(UserBan.all_objects.filter(ban_type='permanent').filter(
        Q(deleted_at__gte=since) | Q(expires_at__gte=since, expires_at__lte=now)).values_list('user_id', flat=True))
    failed = 0
    for user_id in sorted(banned | listed | lifted):
        try:
            sync_face_blocklist(user_id)
        except Exception:
            failed += 1
            logger.exception('Face blocklist sync failed: user=%s', user_id)
    return failed
