"""
Helpers for post-deposit ICP capture + Rating modal triggers.

note_dollars_received() is called from post_save signal handlers on incoming
Conversion (usdc_transactions/signals.py) and received cUSD/Dollar+
SendTransaction (send/models.py). Every route money comes in ends in one of them.
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


def note_dollars_received(user, received_at):
    """A user just received dollars by any route: arm the ICP poll / rating.

    Routes: an incoming conversion (USDT/USDC -> Dollar+/cUSD) or a received
    cUSD/Dollar+ send. first_cusd_acquired_at keeps
    its historical name but now means "first dollars in", whatever the token.
    Callers swallow exceptions: modal arming must never fail a money write.
    received_at must be the inflow's own fixed time (completed_at, created_at),
    never a moving updated_at: providers re-save finished rows, and the rating
    prompt may only arm for dollars that arrived after the ICP answer, not for
    a re-save of the inflow that opened the poll.
    """
    if user is None or received_at is None:
        return
    with transaction.atomic():
        mark_first_cusd_acquired_if_null(user, received_at)
        user.refresh_from_db(
            fields=['first_cusd_acquired_at', 'confio_icp_captured_at',
                    'rating_prompt_due_at', 'confio_rating_prompted_at']
        )
        if user.confio_icp_captured_at and received_at > user.confio_icp_captured_at:
            arm_rating_prompt_if_eligible(user)


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
