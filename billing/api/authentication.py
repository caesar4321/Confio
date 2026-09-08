import hashlib
import hmac
import secrets
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from billing.models import BusinessApiKey


SUPPORTED_SCOPES = frozenset({
    'subjects:read', 'subjects:write',
    'obligations:read', 'obligations:write',
    'payments:read', 'applications:read', 'settlements:read',
    'events:read', 'webhook_endpoints:read', 'webhook_endpoints:write',
    'reconciliation:read',
})


@dataclass(frozen=True)
class ApiPrincipal:
    api_key_id: int
    business_id: int
    mode: str
    scopes: frozenset

    @property
    def is_authenticated(self):
        return True


def _pepper():
    value = getattr(settings, 'BILLING_API_KEY_PEPPER', '')
    if not value:
        raise RuntimeError('BILLING_API_KEY_PEPPER is not configured')
    return value.encode('utf-8')


def _digest(token):
    return hmac.new(_pepper(), token.encode('utf-8'), hashlib.sha256).hexdigest()


def create_business_api_key(*, business, name, mode='test', scopes=()):
    """Provision a high-entropy key; the plaintext is returned exactly once."""
    normalized_scopes = sorted(set(scopes))
    unknown = set(normalized_scopes) - SUPPORTED_SCOPES
    if unknown:
        raise ValueError(f'unknown API scopes: {sorted(unknown)}')
    if mode not in ('test', 'live'):
        raise ValueError('mode must be test or live')
    if mode == 'live' and not getattr(
            settings, 'BILLING_LIVE_API_KEYS_ENABLED', False):
        raise ValueError('live billing API keys are not enabled')
    prefix = secrets.token_hex(8)
    token = f'sk_{mode}_{prefix}_{secrets.token_urlsafe(32)}'
    row = BusinessApiKey.objects.create(
        business=business, name=name, mode=mode, prefix=prefix,
        secret_hmac=_digest(token), scopes=normalized_scopes)
    return row, token


class BusinessApiKeyAuthentication(BaseAuthentication):
    keyword = b'bearer'

    def authenticate_header(self, request):
        return 'Bearer'

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts:
            return None
        if len(parts) != 2 or parts[0].lower() != self.keyword:
            raise AuthenticationFailed('Invalid Authorization header.')
        try:
            token = parts[1].decode('ascii')
            marker, mode, prefix, secret = token.split('_', 3)
        except (UnicodeDecodeError, ValueError):
            raise AuthenticationFailed('Invalid API key.')
        if marker != 'sk' or mode not in ('test', 'live') or not prefix or not secret:
            raise AuthenticationFailed('Invalid API key.')
        if mode == 'live' and not getattr(
                settings, 'BILLING_LIVE_API_KEYS_ENABLED', False):
            raise AuthenticationFailed('Live billing API access is disabled.')
        try:
            key = BusinessApiKey.objects.get(
                prefix=prefix, mode=mode, business__deleted_at__isnull=True)
        except BusinessApiKey.DoesNotExist:
            raise AuthenticationFailed('Invalid API key.')
        now = timezone.now()
        if (key.revoked_at is not None
                or (key.expires_at is not None and key.expires_at <= now)
                or not hmac.compare_digest(key.secret_hmac, _digest(token))):
            raise AuthenticationFailed('Invalid API key.')
        scopes = frozenset(key.scopes or ())
        if not scopes.issubset(SUPPORTED_SCOPES):
            raise AuthenticationFailed('API key contains an unsupported scope.')
        BusinessApiKey.objects.filter(id=key.id).update(last_used_at=now)
        principal = ApiPrincipal(
            api_key_id=key.id, business_id=key.business_id,
            mode=key.mode, scopes=scopes)
        return principal, key
