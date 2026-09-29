"""HTTP endpoints for the banned-account emergency exit (security/emergency_exit.py).

Plain JSON views rather than GraphQL: the caller carries no JWT (a banned
user's authenticated requests are refused by SecurityMiddleware), and the
account is proved by a wallet signature instead.
"""
import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from security.emergency_exit import (
    EmergencyExitError, complete_face, issue_challenge, open_session, start_face,
)
from security.face_step_up import FaceStepUpError, FaceStepUpPending

logger = logging.getLogger(__name__)

GENERIC_ERROR = 'No pudimos completar la verificación. Intenta de nuevo.'


def _body(request) -> dict:
    try:
        data = json.loads(request.body or b'{}')
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _app_check(request) -> str:
    return request.headers.get('X-Firebase-AppCheck', '')


def _error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({'success': False, 'error': message}, status=status)


@csrf_exempt
@require_POST
def emergency_exit_challenge(request):
    try:
        return JsonResponse({'success': True, **issue_challenge(_body(request).get('address'))})
    except EmergencyExitError as exc:
        return _error(str(exc))


@csrf_exempt
@require_POST
def emergency_exit_session(request):
    data = _body(request)
    try:
        result = open_session(data.get('address'), data.get('nonce'), data.get('signature'), _app_check(request))
    except EmergencyExitError as exc:
        return _error(str(exc))
    except Exception:  # noqa: BLE001
        logger.exception('Emergency exit session failed')
        return _error(GENERIC_ERROR, 500)
    return JsonResponse({
        'success': True,
        'banned': result['banned'],
        'faceRequired': result['face_required'],
        'waitRequired': result['wait_required'],
        'token': result['token'],
    })


@csrf_exempt
@require_POST
def emergency_exit_face_start(request):
    try:
        data = start_face(_body(request).get('token'), _app_check(request))
    except EmergencyExitError as exc:
        return _error(str(exc))
    except Exception:  # noqa: BLE001
        logger.exception('Emergency exit face check could not start')
        return _error(GENERIC_ERROR, 500)
    # Same shape as the startFaceCheck mutation, so the app's capture code is shared.
    return JsonResponse({
        'success': True,
        'sessionId': data['session_id'],
        'region': data['region'],
        'accessKeyId': data['access_key_id'],
        'secretAccessKey': data['secret_access_key'],
        'sessionToken': data['session_token'],
        'expiration': data['expiration'],
    })


@csrf_exempt
@require_POST
def emergency_exit_face_complete(request):
    data = _body(request)
    try:
        passed = complete_face(data.get('token'), data.get('sessionId'))
    except FaceStepUpPending as exc:
        # Same contract as completeFaceCheck: success=false with the pending text; retry.
        return JsonResponse({'success': False, 'passed': False, 'error': str(exc)}, status=202)
    except (EmergencyExitError, FaceStepUpError) as exc:
        return JsonResponse({'success': False, 'passed': False, 'error': str(exc)}, status=400)
    except Exception:  # noqa: BLE001
        logger.exception('Emergency exit face check could not complete')
        return JsonResponse({'success': False, 'passed': False, 'error': GENERIC_ERROR}, status=500)
    return JsonResponse({'success': True, 'passed': passed, 'error': None})
