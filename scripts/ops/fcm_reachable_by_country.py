"""Push-reachable users per phone country (read-only, aggregate counts only).

Run on prod:
    ssh confio-prod 'cd /opt/confio && myvenv/bin/python manage.py shell' < scripts/ops/fcm_reachable_by_country.py

"Reachable" mirrors the admin's active_fcm_users (users/admin_analytics.py):
an active user with at least one is_active FCMDeviceToken. A token is only
deactivated when a push to it fails (UnregisteredError on uninstall), so an
active token can be stale until the next send. last_used is bumped on every
successful delivery AND on token registration from the app
(notifications/fcm_service.py), so "≤30d" = app confirmed alive in 30 days.
"""
from collections import Counter, defaultdict
from datetime import timedelta

from django.utils import timezone

from notifications.models import FCMDeviceToken
from users.analytics import get_real_users_queryset

NOW = timezone.now()

real = defaultdict(int)
for cc in get_real_users_queryset().filter(is_active=True).values_list('phone_country', flat=True):
    real[(cc or '??').upper()] += 1

rows = (FCMDeviceToken.objects.filter(is_active=True, user__is_active=True)
        .values('user_id', 'user__phone_country', 'device_type', 'last_used'))
user_cc, user_last, user_os = {}, {}, defaultdict(set)
for r in rows:
    uid = r['user_id']
    user_cc[uid] = (r['user__phone_country'] or '??').upper()
    if r['last_used'] and (uid not in user_last or r['last_used'] > user_last[uid]):
        user_last[uid] = r['last_used']
    user_os[uid].add((r['device_type'] or '?').lower())

reach = defaultdict(set)
for uid, cc in user_cc.items():
    reach[cc].add(uid)


def recent(uids, days):
    cut = NOW - timedelta(days=days)
    return sum(1 for u in uids if user_last.get(u) and user_last[u] >= cut)


def pct(a, b):
    return f"{100.0 * a / b:5.1f}%" if b else "   n/a"


total = len(user_cc)
print(f"Push-reachable users (active token, active user): {total}")
print(f"  alive ≤7d: {recent(user_cc, 7)}   ≤30d: {recent(user_cc, 30)}   ≤90d: {recent(user_cc, 90)}")
print(f"  not confirmed alive in 90d: {total - recent(user_cc, 90)}")
os_mix = Counter('+'.join(sorted(s)) for s in user_os.values())
print("  device mix:", dict(os_mix.most_common()))

print(f"\n{'cc':<4}{'real':>7}{'reach':>7}{'reach%':>8}{'share':>8}{'≤7d':>6}{'≤30d':>6}{'≤90d':>6}{'ios':>6}{'andr':>6}")
for cc in sorted(reach, key=lambda c: -len(reach[c])):
    u = reach[cc]
    ios = sum(1 for x in u if 'ios' in user_os[x])
    andr = sum(1 for x in u if 'android' in user_os[x])
    print(f"{cc:<4}{real.get(cc, 0):>7}{len(u):>7}{pct(len(u), real.get(cc, 0)):>8}{pct(len(u), total):>8}"
          f"{recent(u, 7):>6}{recent(u, 30):>6}{recent(u, 90):>6}{ios:>6}{andr:>6}")
print("\nreach% = reachable ÷ phone-verified active users of that country; share = of all reachable")
print("??  = reachable users with no verified phone country")
print("Done.")
