import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from ramps.koywe_client import KoyweClient, KoyweError
from ramps.koywe_sync import (
    extract_koywe_event_id,
    extract_koywe_event_type,
    extract_koywe_order_id,
    sync_koywe_ramp_transaction_from_order,
    verify_koywe_webhook_signature,
)
from ramps.models import RampTransaction, RampWebhookEvent

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def koywe_webhook(request):
    signature = request.headers.get('Koywe-Signature') or request.headers.get('KOYWE-SIGNATURE')

    logger.info(
        'Koywe webhook received: signature_present=%s content_length=%s',
        bool(signature),
        request.META.get('CONTENT_LENGTH'),
    )

    if not verify_koywe_webhook_signature(request.body, signature):
        logger.warning('Koywe webhook rejected due to invalid signature')
        return JsonResponse({'ok': False, 'error': 'Invalid signature'}, status=403)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except json.JSONDecodeError:
        logger.warning('Koywe webhook rejected due to invalid JSON')
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    event_type = extract_koywe_event_type(payload)
    event_id = extract_koywe_event_id(payload)
    if not event_id:
        logger.warning('Koywe webhook rejected due to missing event id: type=%s', event_type)
        return JsonResponse({'ok': False, 'error': 'Missing event id'}, status=400)

    event, created = RampWebhookEvent.objects.get_or_create(
        event_id=event_id,
        defaults={
            'provider': 'koywe',
            'event_type': event_type,
            'payload': payload,
        },
    )
    if not created:
        return JsonResponse({'ok': True, 'duplicate': True})

    order_id = extract_koywe_order_id(payload)
    if not order_id:
        logger.info('Koywe webhook stored without order id: event_id=%s type=%s', event_id, event_type)
        return JsonResponse({'ok': True, 'stored': True})

    ramp_tx = RampTransaction.objects.filter(
        provider='koywe',
        provider_order_id=order_id,
    ).first()
    if not ramp_tx:
        logger.info('Koywe webhook stored for unknown order: event_id=%s order_id=%s', event_id, order_id)
        return JsonResponse({'ok': True, 'stored': True, 'order_id': order_id})

    client = KoyweClient()
    if not client.is_configured:
        logger.warning('Koywe webhook could not reconcile order %s: client not configured', order_id)
        return JsonResponse({'ok': True, 'stored': True, 'order_id': order_id})

    try:
        auth_email = str((ramp_tx.metadata or {}).get('auth_email') or '').strip() or None
        result = client.get_ramp_order_status(order_id=order_id, email=auth_email)
        sync_koywe_ramp_transaction_from_order(
            ramp_tx=ramp_tx,
            order_payload=result.raw_response,
            next_action_url=result.next_action_url,
        )
    except KoyweError as exc:
        logger.warning('Koywe webhook reconcile failed for %s: %s', order_id, exc)
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    except Exception:
        logger.exception('Unexpected Koywe webhook failure for %s', order_id)
        return JsonResponse({'ok': False, 'error': 'Unexpected error'}, status=500)

    return JsonResponse({'ok': True, 'order_id': order_id, 'status': ramp_tx.status})
