"""Usage retention per phone country (read-only, aggregate counts only).

Run on prod:
    ssh confio-prod 'cd /opt/confio && myvenv/bin/python manage.py shell' < scripts/ops/active_by_country.py

Active = User.last_activity_at (bumped on any app activity) inside the window,
over phone-verified active users — comparable to industry D7/D30 "opened the
app" retention, unlike push-token reachability (install, not use).
"""
from datetime import timedelta

from django.utils import timezone

from users.analytics import get_real_users_queryset

NOW = timezone.now()
q = get_real_users_queryset().filter(is_active=True)


def pct(a, b):
    return f"{100.0 * a / b:5.1f}%" if b else "   n/a"


print(f"{'cc':<4}{'users':>7}{'act7d':>8}{'%':>8}{'act30d':>8}{'%':>8}{'act90d':>8}{'%':>8}")
for cc in ['VE', 'AR', 'BO', 'CO', 'PE', 'MX', 'US', 'EC', 'ES', 'CL']:
    s = q.filter(phone_country=cc)
    n = s.count()
    a = [s.filter(last_activity_at__gte=NOW - timedelta(days=d)).count() for d in (7, 30, 90)]
    print(f"{cc:<4}{n:>7}{a[0]:>8}{pct(a[0], n):>8}{a[1]:>8}{pct(a[1], n):>8}{a[2]:>8}{pct(a[2], n):>8}")

n = q.count()
a = [q.filter(last_activity_at__gte=NOW - timedelta(days=d)).count() for d in (7, 30, 90)]
print(f"{'ALL':<4}{n:>7}{a[0]:>8}{pct(a[0], n):>8}{a[1]:>8}{pct(a[1], n):>8}{a[2]:>8}{pct(a[2], n):>8}")
print(f"never recorded activity: {q.filter(last_activity_at__isnull=True).count()}")

# Signup itself bumps last_activity_at, so a country with many fresh signups
# looks "active". Returning users only: joined before the window opened.
print("\nReturning users only (joined before the window): active ÷ users who already existed")
print(f"{'cc':<4}{'old30':>7}{'act30d':>8}{'%':>8}{'old90':>8}{'act90d':>8}{'%':>8}{'new30':>7}")
for cc in ['VE', 'AR', 'BO', 'CO', 'PE', 'MX', 'US', 'EC', 'ES', 'CL', None]:
    s = q if cc is None else q.filter(phone_country=cc)
    row = []
    for d in (30, 90):
        cut = NOW - timedelta(days=d)
        old = s.filter(date_joined__lt=cut)
        row += [old.count(), old.filter(last_activity_at__gte=cut).count()]
    new30 = s.filter(date_joined__gte=NOW - timedelta(days=30)).count()
    print(f"{cc or 'ALL':<4}{row[0]:>7}{row[1]:>8}{pct(row[1], row[0]):>8}"
          f"{row[2]:>8}{row[3]:>8}{pct(row[3], row[2]):>8}{new30:>7}")
