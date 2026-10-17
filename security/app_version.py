"""Tells the app whether its store has a newer version to suggest.

Public and unauthenticated: the check runs before sign-in, and a version
number is no secret. The app reports what it is (query params, else the
X-Confio-* headers every mobile request carries); the server answers with
the policy and its verdict so the comparison rules live in one place.
"""
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from security.face_client import _version
from security.models import AppVersionPolicy

CURRENT = 'current'
UPDATE_AVAILABLE = 'update_available'


def update_status(policy, version):
    """An unparseable client version gets no prompt: a header we cannot
    read is our bug, not a reason to nag."""
    reported = _version(version)
    latest = _version(policy.latest_version) if policy else None
    if reported is None or latest is None or reported >= latest:
        return CURRENT
    return UPDATE_AVAILABLE


@require_GET
def app_version(request):
    platform = (request.GET.get('platform') or request.headers.get('X-Confio-Platform', '')).lower()
    version = request.GET.get('version') or request.headers.get('X-Confio-Version', '')
    if platform not in ('ios', 'android'):
        return JsonResponse({'error': 'platform must be ios or android'}, status=400)
    policy = AppVersionPolicy.objects.filter(platform=platform).first()
    response = JsonResponse({
        'platform': platform,
        'latestVersion': policy.latest_version if policy else '',
        'message': policy.message if policy else '',
        'status': update_status(policy, version),
    })
    response['Cache-Control'] = 'no-store'
    return response
