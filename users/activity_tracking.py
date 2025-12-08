"""
Centralized user activity tracking for DAU/MAU/WAU metrics

This module provides a single source of truth for tracking user activity.
All user actions that should count toward DAU/MAU should call touch_last_activity().

Activity Definition (what counts as "active"):
- Login / session recovery
- Financial actions (send, payment, conversion, P2P trade)
- P2P interactions (messages, trade confirmations)
- Achievement earnings
- Any other meaningful app interaction

This unified approach ensures:
1. Consistent DAU/MAU/WAU calculations across all dashboards
2. Single query for metrics (fast & simple)
3. Easy policy changes (modify activity criteria in one place)
"""

from django.utils import timezone
from django.db import transaction
from django.core.cache import cache
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


# Minimum interval between updates (prevents excessive DB writes)
ACTIVITY_UPDATE_COOLDOWN = timedelta(minutes=5)


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

    # Cooldown check to prevent excessive updates
    # Uses cache to track recent updates without hitting DB
    if not force:
        cache_key = f"last_activity_touch:{user_id}"
        last_touch = cache.get(cache_key)

        if last_touch:
            # Already updated recently, skip
            return False

        # Set cache for cooldown period
        cache.set(cache_key, True, timeout=int(ACTIVITY_UPDATE_COOLDOWN.total_seconds()))

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
    return User.objects.filter(last_activity_at__gte=cutoff)


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

    total_users = User.objects.count()

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
   - Any authenticated GraphQL mutation

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

Note: Pure read operations (queries) should NOT update activity,
only mutations that represent meaningful user engagement.
"""
