"""Didit face blocklist for permanently banned accounts.

A ban stops an account, not a person: the same person can come back with a
new Google/Apple account and a different document (banned with the cédula,
back with the passport), which no document-number match catches. Didit's 1:N
face search checks every new verification against its face blocklist and
declines a match (FACE_IN_BLOCKLIST), whatever document is presented.

So each verified personal Didit session of a permanently banned user goes on
the face blocklist (Lists API, reference_session_id), and comes off when the
ban is lifted. Only the face: a reused document is already a review hold
(security/identity_reuse.py), not a decline. Temporary and partial bans
(trading, withdrawal) are not blocklisted.

Each ban change queues sync_face_blocklist; reconcile_face_blocklist runs
hourly for whatever that missed. Both are idempotent.
"""
import logging

import requests
from django.db import transaction
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


def face_blocklist_uuid() -> str:
    """The application's face blocklist: system-provisioned, one per entry type."""
    data = _call('GET', '/v3/lists/?list_type=blocklist&entry_type=face')
    rows = data.get('results') if isinstance(data, dict) else data
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
    """Didit sessions of the user's verified personal documents, primary or extra."""
    rows = IdentityVerification.all_objects.filter(user_id=user_id, status='verified').filter(
        Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'),
    ).values_list('risk_factors__didit__session_id', flat=True)
    return {str(session_id) for session_id in rows if session_id}


def sync_face_blocklist(user_id) -> None:
    from django.contrib.auth import get_user_model
    failure = None
    with transaction.atomic():
        # One sync per user at a time: never two entries for one session.
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
                        'display_label': f'confio-user-{user_id}',
                        'comment': COMMENT,
                        'metadata': {'reference_type': 'vendor_user', 'confio_user_id': user_id},
                    })
                except DiditAPIError as exc:
                    # Keep the entries Didit already created: rolling their
                    # rows back would leave them on Didit untracked, never
                    # removed when the ban is lifted.
                    failure = exc
                    break
                entry_uuid = str(created.get('uuid') or created.get('id') or '')
                if not entry_uuid:
                    failure = DiditAPIError('Didit did not return the blocklist entry id')
                    break
                DiditFaceBlocklistEntry.objects.create(user_id=user_id, session_id=session_id,
                                                       list_uuid=list_uuid, entry_uuid=entry_uuid)
                logger.info('Face blocklisted: user=%s session=%s', user_id, session_id)
        else:
            for entry in active:
                try:
                    _call('DELETE', f'/v3/lists/{entry.list_uuid}/entries/{entry.entry_uuid}/', missing_ok=True)
                except DiditAPIError as exc:
                    failure = exc
                    break
                entry.removed_at = timezone.now()
                entry.save(update_fields=['removed_at'])
                logger.info('Face blocklist entry removed: user=%s session=%s', user_id, entry.session_id)
    if failure is not None:
        raise failure


def reconcile_face_blocklist() -> int:
    """Sync every user with a live permanent ban or an active entry. Returns
    how many failed (retried on the next run)."""
    banned = set(UserBan.objects.filter(ban_type='permanent').filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())).values_list('user_id', flat=True))
    listed = set(DiditFaceBlocklistEntry.objects.filter(removed_at__isnull=True).values_list('user_id', flat=True))
    failed = 0
    for user_id in sorted(banned | listed):
        try:
            sync_face_blocklist(user_id)
        except Exception:
            failed += 1
            logger.exception('Face blocklist sync failed: user=%s', user_id)
    return failed
