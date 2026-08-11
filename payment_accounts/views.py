import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from payment_accounts.providers import get_provider
from payment_accounts.tasks import process_webhook
from payment_accounts.webhooks import store_webhook

logger = logging.getLogger(__name__)


def _webhook(request, provider):
    adapter = get_provider(provider)
    if not adapter.verify_webhook(request.body, request.headers):
        return JsonResponse({'ok': False, 'error': 'Invalid signature'}, status=403)
    try:
        json.loads(request.body.decode('utf-8'))
        event, created = store_webhook(
            provider=provider,
            raw_body=request.body,
            headers=request.headers,
        )
    except (ValueError, json.JSONDecodeError):
        return JsonResponse({'ok': False, 'error': 'Invalid webhook'}, status=400)
    if created or event.status in {'received', 'failed'}:
        try:
            process_webhook.delay(event.id)
        except Exception:
            # Return a retryable response. The uniquely stored event remains
            # available, and a provider retry will enqueue it even though the
            # second delivery is a duplicate.
            logger.exception('Unable to enqueue %s webhook %s', provider, event.event_id)
            return JsonResponse(
                {'ok': False, 'error': 'Webhook processing unavailable'}, status=503
            )
    return JsonResponse({'ok': True, 'duplicate': not created})


@csrf_exempt
@require_POST
def cobre_webhook(request):
    return _webhook(request, 'cobre')


@csrf_exempt
@require_POST
def infinia_webhook(request):
    return _webhook(request, 'infinia')
