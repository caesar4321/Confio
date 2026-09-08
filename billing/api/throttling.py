import time

from django.conf import settings
from django.core.cache import cache
from rest_framework.throttling import BaseThrottle


class BillingApiKeyRateThrottle(BaseThrottle):
    """Fixed one-minute limit shared by every process through Django cache."""

    def allow_request(self, request, view):
        principal = getattr(request, 'user', None)
        if not getattr(principal, 'api_key_id', None):
            return True
        self.limit = int(getattr(settings, 'BILLING_API_RATE_LIMIT_PER_MINUTE', 600))
        self.window = int(time.time() // 60)
        key = f'billing-rate:{principal.business_id}:{principal.api_key_id}:{self.window}'
        if cache.add(key, 1, timeout=70):
            count = 1
        else:
            try:
                count = cache.incr(key)
            except ValueError:
                cache.set(key, 1, timeout=70)
                count = 1
        request.billing_rate_limit = self.limit
        request.billing_rate_remaining = max(0, self.limit - count)
        request.billing_rate_reset = (self.window + 1) * 60
        return count <= self.limit

    def wait(self):
        return max(1, (self.window + 1) * 60 - int(time.time()))
