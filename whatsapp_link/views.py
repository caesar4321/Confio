"""What whatsapp-bridge delivers: events from the person's linked WhatsApp, in order.

Reached only from the bridge on the same host: a token from the parameter store, compared in constant time,
and never through the public proxy (nginx adds X-Forwarded-For / X-Real-IP; the bridge never does)."""
import hmac
import json
import logging

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import conf, service

logger = logging.getLogger(__name__)


def _token():
    from config.secrets import get_secret
    value = get_secret(conf.get('WHATSAPP_LINK_BRIDGE_SECRET'))
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return ''
    return str((value or {}).get('token') or '') if isinstance(value, dict) else ''


@csrf_exempt
@require_POST
def bridge_events(request):
    if request.META.get('HTTP_X_FORWARDED_FOR') or request.META.get('HTTP_X_REAL_IP'):
        return HttpResponse(status=404)  # came through the public proxy: not the bridge
    expected = _token()
    given = request.META.get('HTTP_AUTHORIZATION', '')
    if not expected or not hmac.compare_digest(given.encode(), f'Bearer {expected}'.encode()):
        return HttpResponse(status=404)
    try:
        events = json.loads(request.body or b'{}').get('events') or []
    except (ValueError, AttributeError):
        return HttpResponse(status=400)
    if not isinstance(events, list):
        return HttpResponse(status=400)
    if not service.on_events([event for event in events if isinstance(event, dict)]):
        return JsonResponse({'ok': False}, status=500)  # the bridge keeps them and delivers them again
    return JsonResponse({'ok': True})
