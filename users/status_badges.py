"""A person's public badges: referral tier (Embajador...) and the checkmark.

Public by design, like @usuario. They travel WITH the row or person they
belong to, never through a phone-number lookup (users/schema.py
check_users_by_phones answers only saved contacts).
"""
from django.db.models import Count


def _badge(count: int) -> tuple:
    from users.models import User
    tier = next((slug for threshold, slug in User.STATUS_TIER_THRESHOLDS if count >= threshold), 'member')
    return tier, count >= 1


def badges_for(user_ids) -> dict:
    """{user_id: (status_tier, is_referral_verified)} in one query."""
    from achievements.models import UserReferral
    ids = {uid for uid in user_ids if uid}
    if not ids:
        return {}
    counts = dict(UserReferral.objects.filter(
        referrer_user_id__in=ids, referrer_reward_status__in=('eligible', 'claimed'), deleted_at__isnull=True,
    ).order_by().values_list('referrer_user_id').annotate(total=Count('id')))
    return {uid: _badge(counts.get(uid, 0)) for uid in ids}


def _memo(info) -> dict:
    memo = getattr(info.context, '_status_badges', None)
    if memo is None:
        memo = {}
        info.context._status_badges = memo
    return memo


def preload_badges(info, user_ids) -> None:
    """A whole page's people in one query, before its rows resolve."""
    memo = _memo(info)
    memo.update(badges_for(set(user_ids) - set(memo)))


def badge_of(info, user_id) -> tuple:
    """(status_tier, is_referral_verified), from the page's preload."""
    if not user_id:
        return None, None
    memo = _memo(info)
    if user_id not in memo:
        memo.update(badges_for([user_id]))
    return memo[user_id]
