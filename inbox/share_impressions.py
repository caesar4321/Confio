"""Share-sheet impressions (inbox.models.ActivityShareImpression).

Bookkeeping only: every function swallows its own errors, so a failed write
can never stop the sheet from showing or a share from publishing.
"""
import logging

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

logger = logging.getLogger(__name__)

_PLATFORMS = ('ios', 'android')


def _client(meta):
    from users.paid_offers import app_version

    platform = str((meta or {}).get('HTTP_X_CONFIO_PLATFORM', '') or '').strip().lower()
    return (platform if platform in _PLATFORMS else ''), app_version(meta)


def record_preview(user, group, reference, meta, *, offered, block_code='', unified_transaction_id=None):
    """The sheet fetched its preview for this movement."""
    from .models import ActivityShareImpression

    try:
        platform, version = _client(meta)
        fields = {
            'offered': bool(offered),
            'block_code': (block_code or '')[:40],
            'unified_transaction_id': int(unified_transaction_id) if unified_transaction_id else None,
            'platform': platform,
            'app_version': version[:20],
        }
        key = {'user': user, 'group': (group or '')[:16], 'reference': (reference or '')[:128]}
        with transaction.atomic():
            updated = ActivityShareImpression.objects.filter(**key).update(
                fetches=F('fetches') + 1, last_seen_at=timezone.now(), **fields)
            if not updated:
                try:
                    with transaction.atomic():
                        ActivityShareImpression.objects.create(**key, **fields)
                except IntegrityError:  # a concurrent first fetch created it
                    ActivityShareImpression.objects.filter(**key).update(
                        fetches=F('fetches') + 1, last_seen_at=timezone.now(), **fields)
    except Exception:  # noqa: BLE001 — bookkeeping never breaks the sheet
        logger.exception('share impression: preview not recorded')


def record_outcome(user, group, reference, outcome):
    """How the sheet ended. A share is final: a later dismissal (the person
    closing the "done" state) never overwrites it."""
    from .models import ActivityShareImpression

    if outcome not in (ActivityShareImpression.OUTCOME_SHARED, ActivityShareImpression.OUTCOME_DISMISSED):
        return
    try:
        rows = ActivityShareImpression.objects.filter(
            user=user, group=(group or '')[:16], reference=(reference or '')[:128])
        if outcome == ActivityShareImpression.OUTCOME_DISMISSED:
            rows = rows.exclude(outcome=ActivityShareImpression.OUTCOME_SHARED)
        # Savepoint: a failure here must not break the caller's transaction
        # (the share it follows, under ATOMIC_REQUESTS).
        with transaction.atomic():
            rows.update(outcome=outcome, closed_at=timezone.now())
    except Exception:  # noqa: BLE001
        logger.exception('share impression: outcome not recorded')
