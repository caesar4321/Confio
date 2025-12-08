# Activity Tracking - Quick Reference

## TL;DR

**DAU/MAU now uses ONE field**: `User.last_activity_at`

**Auto-tracked**: GraphQL middleware tracks all mutations automatically

**Manual tracking**: Only needed for non-GraphQL operations:
```python
from users.activity_tracking import touch_last_activity
touch_last_activity(user)
```

## Common Operations

### Get Current Metrics
```python
from users.activity_tracking import get_activity_metrics

metrics = get_activity_metrics()
print(f"DAU: {metrics['dau']}, MAU: {metrics['mau']}")
```

### Get Active Users
```python
from users.activity_tracking import get_active_users

dau = get_active_users(days=1).count()
wau = get_active_users(days=7).count()
mau = get_active_users(days=30).count()
```

### Track Activity Manually
```python
from users.activity_tracking import touch_last_activity

# Simple
touch_last_activity(user)

# With timestamp
touch_last_activity(user, ts=event_time)

# Force (bypass cooldown)
touch_last_activity(user, force=True)
```

## Command Line

```bash
# View metrics
myvenv/bin/python manage.py activity_metrics

# Detailed view
myvenv/bin/python manage.py activity_metrics --detailed

# Validate
myvenv/bin/python manage.py activity_metrics --validate

# Compare old vs new
myvenv/bin/python manage.py activity_metrics --compare-methods

# Backfill historical data
myvenv/bin/python manage.py backfill_last_activity
```

## What Counts as Active?

✅ **YES - Counts as Active:**
- Login
- Send money
- Receive payment
- P2P trade
- P2P message
- Conversion
- Any GraphQL mutation

❌ **NO - Doesn't Count:**
- GraphQL queries (read-only)
- Passive data fetching
- Background jobs

## Key Files

- `users/activity_tracking.py` - Core utilities
- `users/graphql_middleware.py` - Auto-tracking
- `config/admin_dashboard.py` - Dashboard metrics
- `docs/DAU_MAU_TRACKING.md` - Full documentation

## Quick Checks

### Is it working?
```bash
myvenv/bin/python manage.py activity_metrics --validate
```

### How many active users?
```bash
myvenv/bin/python manage.py activity_metrics
```

### Compare with old method?
```bash
myvenv/bin/python manage.py activity_metrics --compare-methods
```

## Django Shell

```python
from users.models import User
from users.activity_tracking import touch_last_activity
from django.utils import timezone
from datetime import timedelta

# Get DAU count
last_24h = timezone.now() - timedelta(hours=24)
dau = User.objects.filter(last_activity_at__gte=last_24h).count()

# Update activity for a user
user = User.objects.get(email='test@example.com')
touch_last_activity(user)

# Check user's last activity
print(user.last_activity_at)
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Low DAU | Run backfill: `manage.py backfill_last_activity` |
| NULL timestamps | Run backfill + check middleware enabled |
| Numbers seem wrong | Compare methods: `--compare-methods` |
| Not updating | Check 5-min cooldown or use `force=True` |

## Important Notes

- **Cooldown**: 5 minutes between updates (prevents DB spam)
- **Cache**: Uses cache to track recent updates
- **Middleware**: Auto-tracks all GraphQL mutations
- **Performance**: Single indexed query (very fast)

## Migration Checklist

- [ ] Deploy code
- [ ] Run backfill: `manage.py backfill_last_activity`
- [ ] Validate: `manage.py activity_metrics --validate`
- [ ] Compare: `manage.py activity_metrics --compare-methods`
- [ ] Monitor for 1 week
- [ ] Update dashboards/reports

## That's It!

For full details: `docs/DAU_MAU_TRACKING.md`
