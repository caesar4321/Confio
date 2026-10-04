"""Store server notifications for IA+ (no auth cookies; verified per store)."""
import json
import logging

from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import billing

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def app_store_notifications(request):
    """App Store Server Notifications V2. The payload is a JWS signed by
    Apple; anything that doesn't verify is rejected, so no shared secret."""
    try:
        body = json.loads(request.body or b'{}')
        billing.handle_apple_notification(body['signedPayload'])
    except (ValueError, KeyError):
        return HttpResponseBadRequest()
    except billing.BillingError:
        logger.warning('Rejected App Store notification')
        return HttpResponseBadRequest()
    return HttpResponse(status=200)


@csrf_exempt
@require_POST
def google_play_notifications(request):
    """Play RTDN via Pub/Sub push. The OIDC token proves Pub/Sub sent it;
    the subscription state itself is re-read from the Play Developer API."""
    if not billing.verify_rtdn_push(request.META.get('HTTP_AUTHORIZATION', '')):
        return HttpResponseForbidden()
    try:
        billing.handle_google_rtdn(json.loads(request.body or b'{}'))
    except ValueError:
        return HttpResponseBadRequest()
    except billing.BillingTransient:
        # Any non-2xx makes Pub/Sub retry; a 204 would drop the event.
        return HttpResponse(status=503)
    return HttpResponse(status=204)
