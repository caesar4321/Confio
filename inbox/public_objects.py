"""The ledger behind every public object Comunidad writes.

    reserve()  before uploading, in its own committed transaction
    mark_live() in the same transaction that starts referencing the object
    doom()      in the same transaction that stops referencing it
    sweep()     deletes doomed objects and stale reservations until S3 confirms

So a crash between upload and commit, a rolled-back publish, or a failed
delete can never leave public bytes that nothing in the database points at.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import PublicObject, PublicObjectState

logger = logging.getLogger(__name__)

# A publish holds its reservation for at most this long before the sweeper
# treats it as abandoned. Comfortably above an upload plus a review commit.
RESERVATION_GRACE = timedelta(minutes=30)


def reserve(bucket: str, key: str) -> None:
    """Record the key before any byte is uploaded. Must not run inside the
    transaction that will reference it: it has to survive that one's rollback."""
    with transaction.atomic():
        PublicObject.objects.create(bucket=bucket, key=key)


def mark_live(bucket: str, key: str) -> None:
    updated = PublicObject.objects.filter(bucket=bucket, key=key).update(
        state=PublicObjectState.LIVE, updated_at=timezone.now(),
    )
    if not updated:
        # Uploaded without a reservation: record it so it is never untracked.
        try:
            with transaction.atomic():
                PublicObject.objects.create(bucket=bucket, key=key, state=PublicObjectState.LIVE)
        except IntegrityError:
            pass


def doom(bucket: str, key: str) -> None:
    """Call in the same transaction that stops referencing the object."""
    if not key:
        return
    updated = PublicObject.objects.filter(bucket=bucket, key=key).exclude(
        state=PublicObjectState.DELETED,
    ).update(state=PublicObjectState.DOOMED, updated_at=timezone.now())
    if not updated and not PublicObject.objects.filter(bucket=bucket, key=key).exists():
        try:
            with transaction.atomic():
                PublicObject.objects.create(bucket=bucket, key=key, state=PublicObjectState.DOOMED)
        except IntegrityError:
            pass


def mark_deleted(bucket: str, key: str) -> None:
    PublicObject.objects.filter(bucket=bucket, key=key).update(
        state=PublicObjectState.DELETED, updated_at=timezone.now(),
    )


def owed(limit: int = 200):
    """(id) of objects that must be deleted: doomed, or reservations whose
    publish never committed."""
    stale = timezone.now() - RESERVATION_GRACE
    return list(
        PublicObject.objects.filter(state=PublicObjectState.DOOMED).values_list('id', flat=True)[:limit]
    ) + list(
        PublicObject.objects.filter(state=PublicObjectState.RESERVED, updated_at__lt=stale)
        .values_list('id', flat=True)[:limit]
    )


def delete_owed(object_id: int) -> bool:
    """Delete one owed object and record it. Raises on S3 errors (retried)."""
    from security.s3_utils import delete_object

    stale = timezone.now() - RESERVATION_GRACE
    with transaction.atomic():
        obj = PublicObject.objects.select_for_update().filter(id=object_id).first()
        if obj is None:
            return False
        owed_now = obj.state == PublicObjectState.DOOMED or (
            obj.state == PublicObjectState.RESERVED and obj.updated_at < stale
        )
        if not owed_now:
            return False
        delete_object(key=obj.key, bucket=obj.bucket)
        obj.state = PublicObjectState.DELETED
        obj.save(update_fields=['state', 'updated_at'])
    return True
