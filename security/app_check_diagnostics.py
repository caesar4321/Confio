"""Untrusted client hints, never authorization inputs or raw error dumps."""
import re


def login_diagnostics(request):
    headers = getattr(request, 'headers', {}) or {}
    meta = getattr(request, 'META', {}) or {}

    def header(name):
        return str(headers.get(name, meta.get('HTTP_' + name.upper().replace('-', '_'), '')))[:512]

    error = header('X-AppCheck-Debug-Error').lower()
    code = 'none' if not error else 'unknown'
    allowed = {'attestation_rejected', 'backoff', 'rate_limited', 'api_unavailable',
               'service_unavailable', 'play_store_missing', 'network_error', 'empty_token', 'fetch_timeout'}
    if error in allowed:
        code = error
    for needle, category in (
        ('app attestation failed', 'attestation_rejected'),
        ('too many attempts', 'backoff'), ('too_many_requests', 'rate_limited'),
        ('api_not_available', 'api_unavailable'),
        ('cannot_bind_to_service', 'service_unavailable'),
        ('play_store_not_found', 'play_store_missing'),
        ('appcheck_fetch_timeout', 'fetch_timeout'),
        ('network', 'network_error'), ('empty_token', 'empty_token'),
    ):
        if needle in error:
            code = category
            break
    build = header('X-Confio-Build')
    platform = header('X-Confio-Platform').lower()
    return {
        'client_error_code': code,
        'client_build': build if re.fullmatch(r'[0-9]{1,12}', build) else 'unknown',
        'client_platform': platform if platform in ('android', 'ios') else 'unknown',
        'client_reported': True,
    }
