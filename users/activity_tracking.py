"""
Centralized user activity tracking for DAU/MAU/WAU metrics

This module provides a single source of truth for tracking user activity.
All user actions that should count toward DAU/MAU should call touch_last_activity().

Activity Definition (what counts as "active"):
- Login / session recovery
- Financial actions (send, payment, conversion, P2P trade)
- P2P interactions (messages, trade confirmations)
- Achievement earnings
- Any authenticated GraphQL query or mutation (opening the app counts)

Each touch also records a UserActivityDay row (one per member per day), which
is what D1/D7 retention is measured from; last_activity_at only keeps the
latest visit.

This unified approach ensures:
1. Consistent DAU/MAU/WAU calculations across all dashboards
2. Single query for metrics (fast & simple)
3. Easy policy changes (modify activity criteria in one place)
"""

from django.utils import timezone
from django.db import transaction
from django.core.cache import cache
from datetime import timedelta
from zoneinfo import ZoneInfo
import logging

logger = logging.getLogger(__name__)


# Minimum interval between updates (prevents excessive DB writes)
ACTIVITY_UPDATE_COOLDOWN = timedelta(minutes=5)

# Calendar day used for UserActivityDay. Most members live in UTC-3..-6, so a
# fixed UTC-4 day keeps a LATAM evening on one day instead of splitting at
# 8 p.m. Bolivia time, as a UTC day would.
ACTIVITY_DAY_TZ = ZoneInfo('America/La_Paz')
ACTIVITY_DAY_CACHE_TTL = int(timedelta(hours=26).total_seconds())


def activity_day(ts):
    return timezone.localtime(ts, ACTIVITY_DAY_TZ).date()


def record_activity_day(user_id, ts=None):
    """Insert the member's UserActivityDay row for ts's day, once per day.

    Never raises: activity tracking must not break the request or the
    transaction that triggered it (the insert runs in its own savepoint).
    The cache marker is set only once the row is committed, so a rolled-back
    caller or a failed insert leaves the day free to be recorded again.
    """
    from users.models_analytics import UserActivityDay

    if not user_id:
        return False
    ts = ts or timezone.now()
    day = activity_day(ts)
    cache_key = f"activity_day:{user_id}:{day.isoformat()}"
    try:
        if cache.get(cache_key):
            return False
        with transaction.atomic():
            UserActivityDay.objects.bulk_create(
                [UserActivityDay(user_id=user_id, day=day, first_seen_at=ts)],
                ignore_conflicts=True,
            )
        transaction.on_commit(lambda: _mark_activity_day(cache_key))
        return True
    except Exception as e:
        logger.error(f"Failed to record activity day for user {user_id}: {e}")
        return False


def _mark_activity_day(cache_key):
    try:
        cache.set(cache_key, True, timeout=ACTIVITY_DAY_CACHE_TTL)
    except Exception as e:
        logger.error(f"Failed to cache activity day {cache_key}: {e}")


def touch_last_activity(user, ts=None, force=False):
    """
    Update user's last_activity_at timestamp to mark them as active.

    This is the ONLY function that should update last_activity_at.
    All activity tracking should go through this function.

    Args:
        user: User instance or user_id (int)
        ts: Timestamp to use (defaults to now)
        force: Skip cooldown check and force update

    Returns:
        bool: True if updated, False if skipped due to cooldown

    Usage:
        # Simple usage
        touch_last_activity(request.user)

        # With specific timestamp (e.g., for backfills)
        touch_last_activity(user, ts=transaction_time)

        # Force update (bypass cooldown)
        touch_last_activity(user, force=True)
    """
    from users.models import User

    # Handle both User instances and user IDs
    if isinstance(user, int):
        user_id = user
    else:
        user_id = user.id

    # Use provided timestamp or current time
    ts = ts or timezone.now()

    # The day row has its own once-a-day marker, so it runs outside the
    # cooldown: a visit at 23:59 must not hide one at 00:01.
    record_activity_day(user_id, ts)

    # Cooldown check to prevent excessive updates. cache.add is an atomic
    # claim, so concurrent requests from one member write at most once.
    cache_key = f"last_activity_touch:{user_id}"
    if not force:
        if not cache.add(cache_key, True, timeout=int(ACTIVITY_UPDATE_COOLDOWN.total_seconds())):
            # Already updated recently, skip
            return False

    # Update last_activity_at
    # Using update() instead of save() to avoid:
    # 1. Loading the full user object
    # 2. Triggering signals unnecessarily
    # 3. Race conditions on concurrent updates
    try:
        rows_updated = User.objects.filter(id=user_id).update(last_activity_at=ts)

        if rows_updated > 0:
            logger.debug(f"Updated last_activity_at for user {user_id}")
            return True
        else:
            logger.warning(f"User {user_id} not found for activity update")
            return False

    except Exception as e:
        logger.error(f"Failed to update last_activity_at for user {user_id}: {e}")
        # Free the cooldown so the next request retries the write.
        if not force:
            cache.delete(cache_key)
        return False


def touch_last_activity_bulk(user_ids, ts=None):
    """
    Bulk update last_activity_at for multiple users.
    Useful for batch operations like backfills.

    Args:
        user_ids: List of user IDs
        ts: Timestamp to use (defaults to now)

    Returns:
        int: Number of users updated
    """
    from users.models import User

    ts = ts or timezone.now()

    try:
        count = User.objects.filter(id__in=user_ids).update(last_activity_at=ts)
        logger.info(f"Bulk updated last_activity_at for {count} users")
        return count
    except Exception as e:
        logger.error(f"Failed to bulk update last_activity_at: {e}")
        return 0


def get_active_users(days=1):
    """
    Get queryset of users active in the last N days.

    Args:
        days: Number of days to look back

    Returns:
        QuerySet of active users

    Usage:
        # DAU (Daily Active Users)
        dau = get_active_users(days=1).count()

        # WAU (Weekly Active Users)
        wau = get_active_users(days=7).count()

        # MAU (Monthly Active Users)
        mau = get_active_users(days=30).count()
    """
    from users.models import User

    cutoff = timezone.now() - timedelta(days=days)
    return User.objects.exclude(is_platform_test_account=True).filter(last_activity_at__gte=cutoff)


def get_activity_metrics():
    """
    Get standard activity metrics: DAU, WAU, MAU.

    Returns:
        dict: Activity metrics

    Usage:
        metrics = get_activity_metrics()
        print(f"DAU: {metrics['dau']}, WAU: {metrics['wau']}, MAU: {metrics['mau']}")
    """
    from users.models import User

    total_users = User.objects.exclude(is_platform_test_account=True).count()

    return {
        'dau': get_active_users(days=1).count(),
        'wau': get_active_users(days=7).count(),
        'mau': get_active_users(days=30).count(),
        'total_users': total_users,
        'dau_percentage': (get_active_users(days=1).count() / total_users * 100) if total_users > 0 else 0,
        'wau_percentage': (get_active_users(days=7).count() / total_users * 100) if total_users > 0 else 0,
        'mau_percentage': (get_active_users(days=30).count() / total_users * 100) if total_users > 0 else 0,
    }


# Activity tracking points (for documentation)
ACTIVITY_POINTS = """
The following actions should call touch_last_activity():

1. Authentication & Sessions
   - Login (Firebase Auth)
   - Session recovery with valid JWT
   - Any authenticated GraphQL query or mutation

2. Financial Actions (Critical - always track)
   - Send transaction created/completed
   - Payment transaction created/completed
   - Conversion (USDC ↔ cUSD) created/completed
   - USDC deposit/withdrawal
   - P2P trade created/completed

3. P2P Marketplace Interactions
   - P2P offer created
   - P2P trade initiated
   - P2P message sent
   - P2P trade confirmation
   - P2P dispute opened

4. Achievement & Rewards
   - Achievement earned
   - Referral reward claimed

5. Business Account Actions
   - Business account created
   - Employee invitation sent/accepted
   - Payroll run created

Note: authenticated queries count as activity (an app open is a visit).
Subscriptions do not.
"""
