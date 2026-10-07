"""Assistant+ entitlement.

The app has no store purchases (Apple and Google in-app purchases were
dropped on 2026-10-07): an AssistantSubscription row is created and managed
by Confío itself, so Assistant+ is whatever an entitled row says.
"""
from __future__ import annotations

from django.utils import timezone

from .models import AssistantSubscription


def active_subscription(user):
    now = timezone.now()
    for sub in AssistantSubscription.objects.filter(user=user).order_by('-expires_at'):
        if sub.is_entitled(now):
            return sub
    return None


def has_plus(user):
    return active_subscription(user) is not None
