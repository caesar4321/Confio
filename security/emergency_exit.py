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
- a banned account must pass Confío Face before the exit runs, with no
  waiting-period fallback;
- every step requires a Firebase App Check token (Play Integrity / App
  Attest), so the face capture comes from the genuine app on a genuine
  device, not a script or an injected camera.

The exit itself is signed and broadcast by the app, so the app enforces the
result; this module only answers "is this account banned" and grades the
face.
"""
import logging
import re
import secrets

from django.core.cache import cache

from .face_step_up import (
    FaceStepUpError, complete_face_check, start_face_check, step_up_enabled,
)

logger = logging.getLogger(__name__)

CHALLENGE_TTL = 300
SESSION_TTL = 15 * 60
MAX_CHALLENGES_PER_HOUR = 10
APP_CHECK_ACTION = 'emergency_exit_face'
ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')

INVALID_MESSAGE = 'No pudimos verificar tu cuenta. Intenta de nuevo.'
DEVICE_MESSAGE = 'Dispositivo no verificado. Usa la app oficial de Confío.'
TOO_MANY_MESSAGE = 'Demasiados intentos. Intenta de nuevo más tarde.'
EXPIRED_MESSAGE = 'La verificación expiró. Vuelve a empezar.'


class EmergencyExitError(Exception):
    """The message is safe to show."""


def _challenge_key(address: str) -> str:
    return f'emergency_exit:challenge:{address}'


def _session_key(token: str) -> str:
    return f'emergency_exit:session:{token}'


def challenge_message(address: str, nonce: str) -> str:
    return f'Confío · Salida de emergencia\nCuenta: {address}\nCódigo: {nonce}'


def issue_challenge(address: str) -> dict:
    if not isinstance(address, str) or not ADDRESS_RE.match(address):
        raise EmergencyExitError(INVALID_MESSAGE)
    address = address.lower()
    count_key = f'emergency_exit:challenges:{address}'
    cache.add(count_key, 0, 3600)
    try:
        count = cache.incr(count_key)
    except ValueError:  # expired between add and incr
        cache.set(count_key, 1, 3600)
        count = 1
    if count > MAX_CHALLENGES_PER_HOUR:
        raise EmergencyExitError(TOO_MANY_MESSAGE)
    nonce = secrets.token_hex(16)
    cache.set(_challenge_key(address), nonce, CHALLENGE_TTL)
    return {'nonce': nonce, 'message': challenge_message(address, nonce)}


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


def _is_banned(user) -> bool:
    from .utils import check_user_banned
    return check_user_banned(user)[0]


def open_session(address: str, nonce: str, signature: str, app_check_token: str) -> dict:
    """Prove control of the account; say whether the ban route applies."""
    if not isinstance(address, str) or not ADDRESS_RE.match(address):
        raise EmergencyExitError(INVALID_MESSAGE)
    address = address.lower()
    expected = cache.get(_challenge_key(address))
    # One signature, one session: the challenge is spent even on failure.
    cache.delete(_challenge_key(address))
    if not expected or not isinstance(nonce, str) or not secrets.compare_digest(expected, nonce):
        raise EmergencyExitError(EXPIRED_MESSAGE)
    if _recover(challenge_message(address, nonce), signature or '') != address:
        raise EmergencyExitError(INVALID_MESSAGE)
    account = _account_for(address)
    if not account:
        raise EmergencyExitError(INVALID_MESSAGE)
    user = account.user
    _require_app_check(user, app_check_token)

    banned = _is_banned(user)
    face_required = banned and step_up_enabled()
    result = {'banned': banned, 'face_required': face_required, 'token': ''}
    if face_required:
        token = secrets.token_urlsafe(32)
        cache.set(_session_key(token), user.id, SESSION_TTL)
        result['token'] = token
    logger.info('Emergency exit session: user=%s banned=%s face_required=%s', user.id, banned, face_required)
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
        return start_face_check(user, 'emergency_exit')
    except FaceStepUpError as exc:
        raise EmergencyExitError(str(exc)) from None


def complete_face(token: str, session_id: str) -> bool:
    """Pass/fail; raises FaceStepUpPending while AWS is still processing."""
    user = _session_user(token)
    return complete_face_check(user, session_id)
