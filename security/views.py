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
    signature_v2 = request.headers.get('X-Signature-V2')
    signature_simple = request.headers.get('X-Signature-Simple')
    timestamp_header = request.headers.get('X-Timestamp')
    test_webhook = request.headers.get('X-Didit-Test-Webhook') == 'true'

    logger.info(
        'Didit webhook received: test=%s signature_present=%s content_length=%s',
        test_webhook,
        bool(signature),
        request.META.get('CONTENT_LENGTH'),
    )

    if not verify_didit_webhook_signature(
        request.body,
        signature,
        signature_v2_header=signature_v2,
        signature_simple_header=signature_simple,
        timestamp_header=timestamp_header,
    ):
        logger.warning('Didit webhook rejected due to invalid signature: test=%s', test_webhook)
        return JsonResponse({'ok': False, 'error': 'Invalid signature'}, status=403)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        logger.warning('Didit webhook rejected due to invalid JSON: test=%s', test_webhook)
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    webhook_type = payload.get('webhook_type') or payload.get('type')
    session_id = (
        payload.get('session_id')
        or (payload.get('data') or {}).get('session_id')
        or (payload.get('session') or {}).get('session_id')
    )
    if not session_id:
        logger.warning(
            'Didit webhook rejected due to missing session_id: test=%s webhook_type=%s',
            test_webhook,
            webhook_type,
        )
        return JsonResponse({'ok': False, 'error': 'Missing session_id'}, status=400)

    logger.info(
        'Didit webhook processing: session_id=%s webhook_type=%s test=%s',
        session_id,
        webhook_type,
        test_webhook,
    )

    try:
        verification, _ = sync_didit_session(session_id=str(session_id))
    except DiditAPIError as exc:
        logger.warning('Didit webhook sync failed for %s: %s', session_id, exc)
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    except Exception:
        logger.exception('Unexpected Didit webhook failure for %s', session_id)
        return JsonResponse({'ok': False, 'error': 'Unexpected error'}, status=500)

    logger.info(
        'Didit webhook sync succeeded: session_id=%s verification_id=%s status=%s test=%s',
        session_id,
        verification.id,
        verification.status,
        test_webhook,
    )

    return JsonResponse({
        'ok': True,
        'verification_id': verification.id,
        'status': verification.status,
    })
