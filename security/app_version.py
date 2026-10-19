"""Tells the app whether it must, or may, update from its store.

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
# Builds older than this status (before 5.2.6) ignore it and keep running;
# only the gate shipped with it can block.
UPDATE_REQUIRED = 'update_required'


def update_status(policy, version):
    """An unparseable client version is never prompted or forced: a header
    we cannot read is our bug, and locking users out over it would be worse.
    A blank minimum_version never blocks."""
    reported = _version(version)
    if policy is None or reported is None:
        return CURRENT
    minimum = _version(policy.minimum_version)
    if minimum is not None and reported < minimum:
        return UPDATE_REQUIRED
    latest = _version(policy.latest_version)
    if latest is not None and reported < latest:
        return UPDATE_AVAILABLE
    return CURRENT


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
        'minimumVersion': policy.minimum_version if policy else '',
        'message': policy.message if policy else '',
        'status': update_status(policy, version),
    })
    response['Cache-Control'] = 'no-store'
    return response
