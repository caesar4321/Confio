"""
Helpers for post-deposit ICP capture + Rating modal triggers.

Both helpers are called from post_save signal handlers on Conversion
(usdc_transactions/signals.py) and SendTransaction (send/models.py).
They are idempotent: the fast-path early-return avoids the DB hit when the
target field is already set; the select_for_update inside the transaction
serializes concurrent writers so the earliest acquisition timestamp wins.
"""
from django.db import transaction


def _strip_control_chars(s):
    if s is None:
        return None
    return ''.join(ch for ch in s if ch == '\n' or ch == '\t' or ord(ch) >= 32)


def mark_first_cusd_acquired_if_null(user, acquired_at):
    """Idempotent: only sets first_cusd_acquired_at if currently null."""
    if user is None or acquired_at is None:
        return
    if user.first_cusd_acquired_at is not None:
        return
    from .models import User
    with transaction.atomic():
        u = User.all_objects.select_for_update().filter(pk=user.pk).first()
        if u is None:
            return
        if u.first_cusd_acquired_at is None:
            u.first_cusd_acquired_at = acquired_at
            u.save(update_fields=['first_cusd_acquired_at'])


def arm_rating_prompt_if_eligible(user):
    """Arm rating_prompt_due_at on first post-ICP cUSD activity.

    No-op unless: ICP already captured, prompt not already armed, and modal
    not already prompted. Race-safe via select_for_update inside atomic block.
    """
    if user is None:
        return
    if not user.confio_icp_captured_at:
        return
    if user.rating_prompt_due_at:
        return
    if user.confio_rating_prompted_at:
        return
    from django.utils import timezone
    from .models import User
    with transaction.atomic():
        u = User.all_objects.select_for_update().filter(pk=user.pk).first()
        if u is None:
            return
        if (
            u.confio_icp_captured_at
            and not u.rating_prompt_due_at
            and not u.confio_rating_prompted_at
        ):
            u.rating_prompt_due_at = timezone.now()
            u.save(update_fields=['rating_prompt_due_at'])
