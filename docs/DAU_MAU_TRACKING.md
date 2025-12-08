# DAU/MAU/WAU Activity Tracking System

## Overview

Confío uses a centralized, database-backed system for tracking Daily Active Users (DAU), Weekly Active Users (WAU), and Monthly Active Users (MAU). This system provides accurate, investor-grade metrics that reflect real user engagement with the platform.

## Philosophy

**Single Source of Truth**: All activity tracking is centralized through the `User.last_activity_at` field. This ensures:
- Consistent metrics across all dashboards
- Fast, simple queries (single table lookup)
- Easy policy changes (modify activity criteria in one place)
- No discrepancies between different calculation methods

**Activity Definition**: A user is considered "active" when they perform any meaningful action in the app:
- Login / session recovery
- Financial transactions (send, payment, conversion, P2P trade)
- P2P interactions (messages, trade actions)
- Achievement earnings
- Business account operations

**Not Tracked as Activity**: Pure read operations (GraphQL queries without mutations) do not count as activity.

## Implementation

### 1. Core Function: `touch_last_activity()`

Location: `users/activity_tracking.py`

This is the ONLY function that should update `last_activity_at`. All activity tracking goes through this centralized function.

```python
from users.activity_tracking import touch_last_activity

# Simple usage
touch_last_activity(request.user)

# With specific timestamp (for backfills)
touch_last_activity(user, ts=transaction_time)

# Force update (bypass cooldown)
touch_last_activity(user, force=True)
```

**Features**:
- **Cooldown mechanism**: Prevents excessive DB writes (5-minute minimum between updates)
- **Uses cache**: Tracks recent updates without hitting DB
- **Efficient updates**: Uses `UPDATE` query, doesn't load full user object
- **Error handling**: Logs errors but doesn't fail operations

### 2. Automatic Tracking via GraphQL Middleware

Location: `users/graphql_middleware.py`

All authenticated GraphQL mutations automatically trigger activity tracking. This ensures comprehensive coverage without requiring manual calls in every mutation.

```python
# Configured in settings.py
GRAPHENE = {
    'MIDDLEWARE': [
        'graphql_jwt.middleware.JSONWebTokenMiddleware',
        'users.graphql_middleware.ActivityTrackingMiddleware',  # Auto-tracks activity
    ],
}
```

### 3. Explicit Tracking Points

Some critical operations have explicit `touch_last_activity()` calls for clarity:

**Login** (users/web3auth_schema.py):
```python
# Track login activity for DAU/MAU
from users.activity_tracking import touch_last_activity
touch_last_activity(user)
```

**Important**: Most other mutations are automatically tracked by the middleware, so manual calls are usually not needed.

## Calculating Metrics

### Standard Metrics

```python
from users.activity_tracking import get_activity_metrics

metrics = get_activity_metrics()
# Returns: {
#   'dau': 1234,
#   'wau': 5678,
#   'mau': 12345,
#   'total_users': 50000,
#   'dau_percentage': 2.47,
#   'wau_percentage': 11.36,
#   'mau_percentage': 24.69
# }
```

### Custom Queries

```python
from users.activity_tracking import get_active_users
from django.utils import timezone
from datetime import timedelta

# DAU (last 24 hours)
dau = get_active_users(days=1).count()

# WAU (last 7 days)
wau = get_active_users(days=7).count()

# MAU (last 30 days)
mau = get_active_users(days=30).count()

# Custom period
active_3_days = get_active_users(days=3).count()
```

### Dashboard Implementation

The admin dashboard (config/admin_dashboard.py) uses the centralized method:

```python
# Before: Complex union of multiple tables (70+ lines)
# After: Simple, fast single query
context['active_users_today'] = User.objects.filter(
    last_activity_at__gte=last_24h
).count()
```

## Management Commands

### View Current Metrics

```bash
# Standard DAU/WAU/MAU display
myvenv/bin/python manage.py activity_metrics

# Detailed breakdown by time periods
myvenv/bin/python manage.py activity_metrics --detailed

# Compare new vs old calculation methods
myvenv/bin/python manage.py activity_metrics --compare-methods

# Validate tracking completeness
myvenv/bin/python manage.py activity_metrics --validate
```

### Backfill Historical Data

```bash
# Backfill last 365 days (default)
myvenv/bin/python manage.py backfill_last_activity

# Backfill specific period
myvenv/bin/python manage.py backfill_last_activity --days 90
```

## Monitoring & Validation

### Health Checks

1. **Coverage Check**: What percentage of users have activity timestamps?
```python
total_users = User.objects.count()
users_with_activity = User.objects.filter(last_activity_at__isnull=False).count()
coverage = (users_with_activity / total_users * 100)
```

2. **Tracking Validation**: Compare with old multi-table method
```bash
myvenv/bin/python manage.py activity_metrics --compare-methods
```

3. **Stale Data Check**: Users with recent transactions but stale activity
```bash
myvenv/bin/python manage.py activity_metrics --validate
```

### Expected Results

After implementation:
- ✅ Coverage should be >95% for active users
- ✅ New method should match or exceed old method counts
- ✅ No users with recent activity but NULL `last_activity_at`

## Comparison: Old vs New System

### Old System (Before)
- **DAU Calculation**: Union of 8+ different tables
- **Query Complexity**: 70+ lines of code
- **Performance**: Multiple table scans, slow with scale
- **Consistency**: Different methods for DAU vs MAU
- **Maintainability**: Easy to miss new activity sources

### New System (After)
- **DAU Calculation**: Single field lookup
- **Query Complexity**: 1 line of code
- **Performance**: Single indexed query, scales well
- **Consistency**: Same method for DAU/WAU/MAU
- **Maintainability**: Auto-tracks via middleware

## Firebase Analytics vs Confío Metrics

**When to use which:**

### Confío DB Metrics (Official)
Use for:
- Investor presentations and pitch decks
- Internal KPIs and OKRs
- Tokenomics calculations
- User growth reporting
- Financial planning

**Why**: Account-based (not session-based), reflects real registered users performing financial actions.

### Firebase Analytics
Use for:
- Marketing funnel analysis
- Device/platform breakdown
- Geographic distribution
- Screen flow and user journeys
- A/B testing results
- Campaign attribution

**Why**: Better for understanding behavior patterns and marketing effectiveness.

**Discrepancies are normal**: Firebase counts sessions/devices, we count authenticated users. Our numbers are typically more conservative and accurate for business metrics.

## Activity Policy Options

You can adjust what counts as "active" by modifying where `touch_last_activity()` is called:

### Option A: Login-Inclusive (Current)
- **Tracks**: Login + all financial/engagement actions
- **Philosophy**: "Opened the app = active user"
- **Effect**: Higher MAU numbers
- **Best for**: Demonstrating app adoption and reach

### Option B: Transaction-Only
- **Tracks**: Only financial actions (send/payment/P2P/conversion)
- **Philosophy**: "Did something with money = active user"
- **Effect**: Lower but stronger MAU numbers
- **Best for**: Demonstrating real platform utility

**Recommendation**: Use Option A (current) for public metrics, track Option B separately for internal analysis.

## Best Practices

### Adding New Activity Points

If you add a new feature that should count as activity:

1. **If it's a GraphQL mutation**: No action needed, middleware auto-tracks
2. **If it's a non-GraphQL operation**: Add explicit call:
```python
from users.activity_tracking import touch_last_activity
touch_last_activity(user)
```

### Performance Considerations

- ✅ **Cooldown prevents spam**: 5-minute minimum between updates
- ✅ **Cache-first**: Checks cache before DB
- ✅ **Async-safe**: Safe to call from tasks/signals
- ✅ **Non-blocking**: Activity update failures don't fail operations

### Testing

When testing new features:
```python
from users.activity_tracking import touch_last_activity

# In your test
touch_last_activity(user, force=True)  # Bypass cooldown
assert User.objects.get(id=user.id).last_activity_at is not None
```

## Troubleshooting

### Issue: DAU lower than expected

**Check**:
1. Run validation: `python manage.py activity_metrics --validate`
2. Compare methods: `python manage.py activity_metrics --compare-methods`
3. Verify middleware is enabled in settings.py
4. Check for errors in logs related to activity tracking

**Solution**: Usually fixed by running backfill command

### Issue: Some users missing activity timestamps

**Check**:
1. Are they legacy users from before this system?
2. Have they performed any actions since deployment?

**Solution**:
```bash
# Backfill from historical data
myvenv/bin/python manage.py backfill_last_activity
```

### Issue: Activity timestamp not updating

**Check**:
1. Is the cooldown period (5 min) still active?
2. Are there errors in application logs?
3. Is the cache service running?

**Solution**: Use `force=True` or wait for cooldown to expire

## Migration Path

For existing deployments:

1. **Deploy code changes** (this PR)
2. **Run backfill** to populate historical data:
```bash
myvenv/bin/python manage.py backfill_last_activity --days 365
```
3. **Validate** the migration:
```bash
myvenv/bin/python manage.py activity_metrics --compare-methods
```
4. **Monitor** for 7 days to ensure consistency
5. **Optional**: Remove old calculation code after validation

## Summary

This system provides:
- ✅ **Accurate metrics**: Real user activity, not sessions
- ✅ **Investor-grade**: Suitable for pitch decks and reporting
- ✅ **Performant**: Single indexed query vs multi-table unions
- ✅ **Maintainable**: One place to update activity logic
- ✅ **Comprehensive**: Auto-tracks all mutations via middleware
- ✅ **Validated**: Tools to verify correctness

The result is a robust, scalable foundation for measuring Confío's real growth and engagement.
