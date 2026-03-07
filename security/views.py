import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from security.didit import DiditAPIError, sync_didit_session, verify_didit_webhook_signature

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def didit_webhook(request):
    signature = request.headers.get('X-Signature-V2') or request.headers.get('X-Signature')
    if not verify_didit_webhook_signature(request.body, signature):
        return JsonResponse({'ok': False, 'error': 'Invalid signature'}, status=403)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    session_id = (
        payload.get('session_id')
        or (payload.get('data') or {}).get('session_id')
        or (payload.get('session') or {}).get('session_id')
    )
    if not session_id:
        return JsonResponse({'ok': False, 'error': 'Missing session_id'}, status=400)

    try:
        verification, _ = sync_didit_session(session_id=str(session_id))
    except DiditAPIError as exc:
        logger.warning('Didit webhook sync failed for %s: %s', session_id, exc)
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    except Exception:
        logger.exception('Unexpected Didit webhook failure for %s', session_id)
        return JsonResponse({'ok': False, 'error': 'Unexpected error'}, status=500)

    return JsonResponse({
        'ok': True,
        'verification_id': verification.id,
        'status': verification.status,
    })
