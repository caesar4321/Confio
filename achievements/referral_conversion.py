"""A referral is 'converted' once the referred member has funded.

The old trigger (achievements.signals._award_referral_pair) only fired on a
completed P2P trade, and its send hook was switched off, so status stayed
'pending' for almost everyone who went on to deposit. Funding is the
milestone the referral funnel measures, and ramps.metrics.deposit_events is
the one definition of it across every rail, so status follows that.
"""
import logging

from django.db.models import Value
from django.db.models.functions import Coalesce

logger = logging.getLogger(__name__)

OPEN_STATUSES = ('pending', 'active')


def sync_referral_conversions() -> int:
    """Mark open referrals converted when the referred member has a proven
    deposit, stamping first_transaction_at with the first one when it is
    blank, and date converted rows that have none. Idempotent; 'inactive' is
    an admin decision and stays. Returns how many rows changed."""
    from achievements.models import UserReferral
    from ramps.metrics import deposit_events

    live = UserReferral.objects.filter(deleted_at__isnull=True)
    open_rows = live.filter(status__in=OPEN_STATUSES)
    # Converted by hand in the admin ("rewards claimed") without a date: the
    # first deposit dates it, so the weekly count can see it.
    undated = live.filter(status='converted', first_transaction_at__isnull=True)
    referred = list(open_rows.values_list('referred_user_id', flat=True))
    referred += list(undated.values_list('referred_user_id', flat=True))
    if not referred:
        return 0
    first_deposit = {}
    for user_id, at in deposit_events(referred):
        if at is not None and (user_id not in first_deposit or at < first_deposit[user_id]):
            first_deposit[user_id] = at
    changed = 0
    for user_id, at in first_deposit.items():
        # Status in the filter: a row an admin closed meanwhile is left alone.
        changed += open_rows.filter(referred_user_id=user_id).update(
            status='converted', first_transaction_at=Coalesce('first_transaction_at', Value(at)))
        changed += undated.filter(referred_user_id=user_id).update(first_transaction_at=at)
    if changed:
        logger.info('referral conversions: %d marked converted', changed)
    return changed
