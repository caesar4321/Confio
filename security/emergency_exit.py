"""Confío Face for a banned account's emergency exit.

A banned user cannot reach GraphQL: SecurityMiddleware answers every
authenticated request with a 403. The emergency exit still has to work for
them, and it must not work for a ring that fakes that 403 (or holds a
recruited account the ban was meant to stop). So the ban route has its own
door:

- no JWT: the caller proves control of the account by signing a one-time
  challenge with the account's own BSC key (EIP-191), the same key the exit
  itself spends from;
- the server says whether the account is really banned, so a faked 403
  cannot route a healthy account here;
- a banned account that went through KYC must pass Confío Face before the
  exit runs, with no waiting-period fallback; one that never did (there is
  no face to check, and it is what a ring's pooling account looks like)
  waits the normal route's period instead;
- every step requires a Firebase App Check token (Play Integrity / App
  Attest), so the face capture comes from the genuine app on a genuine
  device, not a script or an injected camera.

The exit itself is signed and broadcast by the app, so the app enforces the
result; this module only answers "is this account banned" and grades the
face.
"""
import hashlib
import logging
import re
import secrets

from django.core import signing
from django.core.cache import cache

from .face_step_up import (
    FaceStepUpError, complete_face_check, start_face_check, step_up_applies, step_up_enabled,
)

logger = logging.getLogger(__name__)

CHALLENGE_TTL = 300
SESSION_TTL = 15 * 60
CHALLENGE_SALT = 'security.emergency_exit.challenge'
APP_CHECK_ACTION = 'emergency_exit_face'
ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')

INVALID_MESSAGE = 'No pudimos verificar tu cuenta. Intenta de nuevo.'
DEVICE_MESSAGE = 'Dispositivo no verificado. Usa la app oficial de Confío.'
EXPIRED_MESSAGE = 'La verificación expiró. Vuelve a empezar.'


class EmergencyExitError(Exception):
    """The message is safe to show."""


def _used_key(nonce: str) -> str:
    return f'emergency_exit:used:{hashlib.sha256(nonce.encode()).hexdigest()}'


def _session_key(token: str) -> str:
    return f'emergency_exit:session:{token}'


def _face_key(token: str) -> str:
    return f'emergency_exit:face:{token}'


def challenge_message(address: str, nonce: str) -> str:
    return f'Confío · Salida de emergencia\nCuenta: {address}\nCódigo: {nonce}'


def issue_challenge(address: str) -> dict:
    """A signed, expiring challenge: issuing one stores nothing.

    The endpoint is unauthenticated and addresses are public, so a challenge
    kept server-side would let anyone fill the cache or evict the owner's.
    Only a challenge that comes back signed by the account's own key is
    marked spent (open_session).
    """
    if not isinstance(address, str) or not ADDRESS_RE.match(address):
        raise EmergencyExitError(INVALID_MESSAGE)
    address = address.lower()
    nonce = signing.dumps({'a': address, 'r': secrets.token_hex(8)}, salt=CHALLENGE_SALT, compress=True)
    return {'nonce': nonce, 'message': challenge_message(address, nonce)}


def _challenge_address(nonce: str):
    try:
        data = signing.loads(nonce, salt=CHALLENGE_SALT, max_age=CHALLENGE_TTL)
    except signing.BadSignature:  # includes SignatureExpired
        return None
    return data.get('a') if isinstance(data, dict) else None


def _recover(message: str, signature: str) -> str:
    from eth_account import Account as EthAccount
    from eth_account.messages import encode_defunct
    try:
        return EthAccount.recover_message(encode_defunct(text=message), signature=signature).lower()
    except Exception:  # noqa: BLE001 — any malformed signature is just invalid
        return ''


def _account_for(address: str):
    from users.models import Account
    return Account.objects.filter(
        bsc_address__iexact=address, deleted_at__isnull=True,
    ).select_related('user').first()


def _require_app_check(user, app_check_token: str) -> None:
    from .integrity_service import app_check_service
    result = app_check_service.verify_and_record(
        user=user, token=app_check_token or '', action=APP_CHECK_ACTION, should_enforce=True)
    if not result.get('success'):
        raise EmergencyExitError(DEVICE_MESSAGE)


def _has_face_reference(user) -> bool:
    from .models import FaceReference
    return FaceReference.objects.filter(user=user, is_active=True).exists()


def _is_banned(user) -> bool:
    from .utils import check_user_banned
    return check_user_banned(user)[0]


def open_session(address: str, nonce: str, signature: str, app_check_token: str) -> dict:
    """Prove control of the account; say whether the ban route applies."""
    if not isinstance(address, str) or not ADDRESS_RE.match(address):
        raise EmergencyExitError(INVALID_MESSAGE)
    address = address.lower()
    if not isinstance(nonce, str) or len(nonce) > 512 or _challenge_address(nonce) != address:
        raise EmergencyExitError(EXPIRED_MESSAGE)
    if _recover(challenge_message(address, nonce), signature or '') != address:
        raise EmergencyExitError(INVALID_MESSAGE)
    # One signature, one session. Marked only after the owner's signature
    # checks out, so nobody else can spend it; add() is atomic, so two
    # concurrent requests cannot both use it.
    if not cache.add(_used_key(nonce), 1, CHALLENGE_TTL):
        raise EmergencyExitError(EXPIRED_MESSAGE)
    account = _account_for(address)
    if not account:
        raise EmergencyExitError(INVALID_MESSAGE)
    user = account.user
    _require_app_check(user, app_check_token)

    banned = _is_banned(user)
    # Confío Face needs a stored KYC selfie to compare against. A banned
    # account without one (never did KYC — what a ring's pooling account
    # looks like — or a selfie copy that was never stored, which a banned
    # user cannot fix by verifying again) gets the normal route's waiting
    # period instead: never an immediate exit, never a permanent lockout.
    face_required = banned and step_up_applies(user) and _has_face_reference(user)
    wait_required = banned and step_up_enabled() and not face_required
    result = {'banned': banned, 'face_required': face_required, 'wait_required': wait_required, 'token': ''}
    if face_required:
        token = secrets.token_urlsafe(32)
        cache.set(_session_key(token), user.id, SESSION_TTL)
        result['token'] = token
    logger.info('Emergency exit session: user=%s banned=%s face_required=%s wait_required=%s',
                user.id, banned, face_required, wait_required)
    return result


def _session_user(token: str):
    from django.contrib.auth import get_user_model
    user_id = cache.get(_session_key(token)) if isinstance(token, str) and token else None
    user = get_user_model().objects.filter(pk=user_id).first() if user_id else None
    if not user:
        raise EmergencyExitError(EXPIRED_MESSAGE)
    return user


def start_face(token: str, app_check_token: str) -> dict:
    user = _session_user(token)
    _require_app_check(user, app_check_token)
    try:
        data = start_face_check(user, 'emergency_exit')
    except FaceStepUpError as exc:
        raise EmergencyExitError(str(exc)) from None
    # Only the liveness session opened here may be graded for this exit: an
    # older passed check (a withdrawal the holder did weeks ago, whose id the
    # device may have logged) must not stand in for a face shown now.
    cache.set(_face_key(token), data['session_id'], SESSION_TTL)
    # Each capture gets the full window to be graded, so a retry late in
    # the session does not expire mid-grading.
    cache.touch(_session_key(token), SESSION_TTL)
    return data


def complete_face(token: str, session_id: str) -> bool:
    """Pass/fail; raises FaceStepUpPending while AWS is still processing."""
    user = _session_user(token)
    if not isinstance(session_id, str) or not session_id or cache.get(_face_key(token)) != session_id:
        raise EmergencyExitError(EXPIRED_MESSAGE)
    return complete_face_check(user, session_id)
