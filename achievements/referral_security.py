from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from achievements.models import (
    ConfioRewardTransaction,
    ReferralRewardEvent,
    ReferralWithdrawalLog,
    UserAchievement,
    UserReferral,
)
from blockchain.constants import REFERRAL_ACHIEVEMENT_SLUGS

DUPLICATE_REFEREE_REWARD_ERROR = (
    "Este documento ya fue utilizado para una recompensa de referido en otra cuenta. "
    "Solo se permite un bono de referido por identidad verificada."
)
DUPLICATE_REFERRER_REWARD_ERROR = (
    "Este referido fue bloqueado por identidad duplicada. No se otorga bono al referidor "
    "cuando la misma identidad verificada intenta reclamar más de una recompensa."
)


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


def _get_verified_identity_user_ids(document_issuing_country: str, document_number_normalized: str):
    from security.models import IdentityVerification

    if not document_issuing_country or not document_number_normalized:
        return []

    return list(
        IdentityVerification.objects.filter(
            status='verified',
            document_issuing_country=document_issuing_country,
            document_number_normalized=document_number_normalized,
        )
        .filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))
        .values_list('user_id', flat=True)
        .distinct()
    )


def _get_identity_referrals(document_issuing_country: str, document_number_normalized: str):
    user_ids = _get_verified_identity_user_ids(document_issuing_country, document_number_normalized)
    if not user_ids:
        return []

    return list(
        UserReferral.objects.filter(
            referred_user_id__in=user_ids,
            deleted_at__isnull=True,
        ).order_by('created_at', 'id')
    )


def enforce_referee_reward_uniqueness_for_identity(document_issuing_country: str, document_number_normalized: str):
    referrals = _get_identity_referrals(document_issuing_country, document_number_normalized)
    if len(referrals) <= 1:
        return {'winner_referral_id': referrals[0].id if referrals else None, 'blocked_referral_ids': []}

    winner = referrals[0]
    blocked_referrals = referrals[1:]
    now = timezone.now()

    with transaction.atomic():
        for referral in blocked_referrals:
            reward_metadata = dict(referral.reward_metadata or {})
            reward_metadata['duplicate_identity_referee_block'] = {
                'document_issuing_country': document_issuing_country,
                'document_number_normalized': document_number_normalized,
                'winner_referral_id': winner.id,
                'blocked_at': now.isoformat(),
            }

            referral.reward_metadata = reward_metadata
            referral.reward_error = DUPLICATE_REFEREE_REWARD_ERROR
            referral.reward_last_attempt_at = now

            update_fields = ['reward_metadata', 'reward_error', 'reward_last_attempt_at', 'updated_at']

            if referral.referee_reward_status != 'claimed':
                referral.referee_reward_status = 'failed'
                update_fields.append('referee_reward_status')
            if referral.referrer_reward_status != 'claimed':
                referral.referrer_reward_status = 'failed'
                update_fields.append('referrer_reward_status')

            if referral.reward_status in {'pending', 'eligible', 'skipped'}:
                referral.reward_status = 'failed'
                update_fields.append('reward_status')

            referral.save(update_fields=update_fields)

            ReferralRewardEvent.objects.filter(
                referral=referral,
            ).exclude(reward_status='claimed').update(
                reward_status='failed',
                updated_at=now,
            )
            ReferralRewardEvent.objects.filter(
                referral=referral,
                actor_role='referee',
            ).exclude(reward_status='claimed').update(
                error=DUPLICATE_REFEREE_REWARD_ERROR,
                updated_at=now,
            )
            ReferralRewardEvent.objects.filter(
                referral=referral,
                actor_role='referrer',
            ).exclude(reward_status='claimed').update(
                error=DUPLICATE_REFERRER_REWARD_ERROR,
                updated_at=now,
            )

    return {
        'winner_referral_id': winner.id,
        'blocked_referral_ids': [referral.id for referral in blocked_referrals],
    }


def get_duplicate_referee_reward_error(referral: UserReferral | None):
    if not referral or not referral.referred_user_id:
        return None

    from security.models import IdentityVerification

    verification = (
        IdentityVerification.objects.filter(
            user_id=referral.referred_user_id,
            status='verified',
        )
        .filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))
        .exclude(document_number_normalized='')
        .order_by('-verified_at', '-updated_at', '-created_at')
        .first()
    )
    if not verification:
        return None

    result = enforce_referee_reward_uniqueness_for_identity(
        verification.document_issuing_country,
        verification.document_number_normalized,
    )
    if result['winner_referral_id'] and result['winner_referral_id'] != referral.id:
        return DUPLICATE_REFEREE_REWARD_ERROR
    return None


def get_duplicate_referral_reward_error(referral: UserReferral | None, actor_role: str = 'referee'):
    referee_error = get_duplicate_referee_reward_error(referral)
    if not referee_error:
        return None
    if (actor_role or '').lower() == 'referrer':
        return DUPLICATE_REFERRER_REWARD_ERROR
    return referee_error


def get_referrer_claim_verification_error(referral: UserReferral | None):
    if not referral or not referral.referred_user:
        return "No encontramos al referido para esta recompensa."

    referred_user = referral.referred_user
    if referred_user.is_identity_verified:
        return None

    verification_status = (getattr(referred_user, 'verification_status', None) or 'unverified').lower()
    if verification_status == 'pending':
        return (
            "Tu referido ya activó este bono, pero todavía debe terminar su verificación de identidad en Didit "
            "para que puedas reclamar la recompensa."
        )
    return (
        "Tu referido ya activó este bono, pero debe completar su verificación de identidad en Didit "
        "para liberar esta recompensa."
    )


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
