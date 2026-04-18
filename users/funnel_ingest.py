"""Funnel event ingest endpoint for trusted external sources.

Currently used by the Cloudflare Worker at workers/link-shortener/src/index.ts
to forward `/invite/{USERNAME}` click events into Postgres.

Authentication: shared-secret header (FUNNEL_INGEST_SECRET). Keep the secret
in env/SSM, not settings.py. If the secret is absent the endpoint refuses
every request so misconfiguration fails closed.
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)


# Events that trusted external sources (Worker) are allowed to emit.
EXTERNAL_INGEST_EVENTS = frozenset({
    'referral_link_clicked',
    'invite_link_clicked',
})


@csrf_exempt
@require_POST
def funnel_ingest(request):
    """Ingest funnel events from trusted external sources."""

    expected_secret = getattr(settings, 'FUNNEL_INGEST_SECRET', None)
    if not expected_secret:
        logger.error('[funnel_ingest] FUNNEL_INGEST_SECRET not configured')
        return JsonResponse({'error': 'not configured'}, status=503)

    provided = request.headers.get('X-Funnel-Secret', '')
    # Constant-time compare
    import hmac
    if not hmac.compare_digest(provided, expected_secret):
        return JsonResponse({'error': 'unauthorized'}, status=401)

    try:
        payload = json.loads(request.body.decode('utf-8'))
    except Exception:
        return JsonResponse({'error': 'invalid json'}, status=400)

    event_name = (payload.get('event_name') or '').strip()
    if event_name not in EXTERNAL_INGEST_EVENTS:
        return JsonResponse({'error': 'event not allowed'}, status=400)

    session_id = (payload.get('session_id') or '')[:64]
    country = (payload.get('country') or '').upper()[:2]
    platform = (payload.get('platform') or '').lower()[:16]
    source_type = (payload.get('source_type') or '').lower()[:32]
    channel = (payload.get('channel') or '').lower()[:32]
    properties = payload.get('properties') or {}
    if not isinstance(properties, dict):
        properties = {}
    # Bound properties size.
    try:
        if len(json.dumps(properties)) > 2048:
            properties = {'_truncated': True}
    except Exception:
        properties = {}

    try:
        from users.funnel import emit_event
        emit_event(
            event_name,
            user=None,
            session_id=session_id,
            country=country,
            platform=platform,
            source_type=source_type,
            channel=channel,
            properties=properties,
        )
    except Exception:
        logger.exception('[funnel_ingest] emit failed')
        return JsonResponse({'error': 'emit failed'}, status=500)

    return JsonResponse({'ok': True})
