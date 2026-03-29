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


def get_referral_reward_policy_stats():
    """Return verification and review metrics for referral-earned CONFIO."""
    from security.models import IdentityVerification

    earned_by_user = {
        row['user']: row['total']
        for row in get_referral_reward_transactions()
        .values('user')
        .annotate(total=Coalesce(Sum('amount'), Decimal('0')))
    }
    spent_by_user = {
        row['user']: row['total']
        for row in ReferralWithdrawalLog.objects.values('user')
        .annotate(total=Coalesce(Sum('amount'), Decimal('0')))
    }

    available_by_user = {}
    for user_id, earned in earned_by_user.items():
        spent = spent_by_user.get(user_id, Decimal('0')) or Decimal('0')
        available = earned - spent
        if available < Decimal('0'):
            available = Decimal('0')
        available_by_user[user_id] = available

    rewarded_user_ids = set(earned_by_user.keys())
    verified_user_ids = set(
        IdentityVerification.objects.filter(
            status='verified',
            user_id__in=rewarded_user_ids,
        )
        .filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))
        .values_list('user_id', flat=True)
        .distinct()
    )

    verified_available_total = sum(
        available_by_user.get(user_id, Decimal('0'))
        for user_id in rewarded_user_ids
        if user_id in verified_user_ids
    )
    kyc_hold_total = sum(
        available_by_user.get(user_id, Decimal('0'))
        for user_id in rewarded_user_ids
        if user_id not in verified_user_ids
    )

    duplicate_identity_review_users = set(
        IdentityVerification.objects.filter(
            status='pending',
            risk_factors__duplicate_identity__isnull=False,
        )
        .filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))
        .values_list('user_id', flat=True)
        .distinct()
    )

    return {
        'rewarded_users': len(rewarded_user_ids),
        'verified_reward_users': len(verified_user_ids),
        'unverified_reward_users': len(rewarded_user_ids - verified_user_ids),
        'verified_available_total': verified_available_total,
        'kyc_hold_total': kyc_hold_total,
        'duplicate_identity_review_users': len(duplicate_identity_review_users),
    }
