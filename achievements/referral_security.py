from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce

from achievements.models import ConfioRewardTransaction, ReferralWithdrawalLog, UserAchievement
from blockchain.constants import REFERRAL_ACHIEVEMENT_SLUGS


def get_referral_reward_transactions(user=None):
    """Return reward ledger rows that represent referral-earned CONFIO."""
    achievement_qs = UserAchievement.objects.filter(
        achievement_type__slug__in=REFERRAL_ACHIEVEMENT_SLUGS,
        deleted_at__isnull=True,
    )
    if user is not None:
        achievement_qs = achievement_qs.filter(user=user)

    referral_achievement_ids = [str(pk) for pk in achievement_qs.values_list('id', flat=True)]

    tx_qs = ConfioRewardTransaction.objects.all()
    if user is not None:
        tx_qs = tx_qs.filter(user=user)

    referral_claim_filter = Q(
        transaction_type__in=['earned', 'unlocked'],
        reference_type='referral_claim',
    )
    if not referral_achievement_ids:
        return tx_qs.filter(referral_claim_filter)

    return tx_qs.filter(
        referral_claim_filter
        | Q(
            transaction_type='earned',
            reference_type='achievement',
            reference_id__in=referral_achievement_ids,
        )
    )


def get_referral_reward_summary(user=None):
    """Aggregate referral-earned CONFIO and logged referral withdrawals."""
    earned = (
        get_referral_reward_transactions(user=user).aggregate(
            total=Coalesce(Sum('amount'), Decimal('0'))
        )['total']
        or Decimal('0')
    )

    withdrawal_qs = ReferralWithdrawalLog.objects.all()
    if user is not None:
        withdrawal_qs = withdrawal_qs.filter(user=user)
    spent = withdrawal_qs.aggregate(total=Coalesce(Sum('amount'), Decimal('0')))['total'] or Decimal('0')

    available = earned - spent
    if available < Decimal('0'):
        available = Decimal('0')

    return {
        'earned': earned,
        'spent': spent,
        'available': available,
    }
