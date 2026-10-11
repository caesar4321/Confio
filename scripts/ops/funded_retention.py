"""Do users who put money in come back more? (read-only, aggregate counts only)

Run on prod:
    ssh confio-prod 'cd /opt/confio && myvenv/bin/python manage.py shell' < scripts/ops/funded_retention.py

Activity = User.last_activity_at, bumped by any authenticated GraphQL mutation
(users/graphql_middleware.py) — the app re-registers its FCM token on every
authenticated entry, so an app open counts when push permission is granted.
Users without push permission who only read can be missed (undercount).

Two measures, both over users who joined >30 days ago (no fresh-signup inflation):
  act30   = active in the last 30 days (current re-activation)
  ret30+  = ever active 30+ days after signup (survival: came back after day 30)
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from blockchain.models import Balance
from ramps.models import RampTransaction
from send.models import SendTransaction
from users.analytics import get_real_users_queryset

try:
    from usdc_transactions.models import USDCDeposit
except Exception:  # pragma: no cover
    USDCDeposit = None

NOW = timezone.now()
DOLLAR_TOKENS = ('CUSD', 'USDC', 'USDT', 'CUSD_PLUS')
DOLLAR_BAL = ('CUSD', 'USDC', 'CUSD_BSC', 'USDT_BSC', 'CUSD_PLUS')

users = {u['id']: u for u in get_real_users_queryset().filter(is_active=True, is_staff=False)
         .values('id', 'phone_country', 'date_joined', 'last_activity_at')}

first_in = {}


def add_inflow(uid, when):
    if uid in users and when and (uid not in first_in or when < first_in[uid]):
        first_in[uid] = when


for r in RampTransaction.objects.filter(direction='on_ramp', status='COMPLETED', actor_user__isnull=False) \
        .values('actor_user_id', 'created_at'):
    add_inflow(r['actor_user_id'], r['created_at'])
for r in SendTransaction.objects.filter(status='CONFIRMED', token_type__in=DOLLAR_TOKENS,
                                        recipient_user__isnull=False) \
        .values('recipient_user_id', 'sender_user_id', 'created_at'):
    if r['sender_user_id'] != r['recipient_user_id']:
        add_inflow(r['recipient_user_id'], r['created_at'])
if USDCDeposit is not None:
    for r in USDCDeposit.objects.filter(status='COMPLETED', actor_user__isnull=False) \
            .values('actor_user_id', 'created_at'):
        add_inflow(r['actor_user_id'], r['created_at'])

p2p_senders = set(SendTransaction.objects.filter(
    status='CONFIRMED', token_type__in=DOLLAR_TOKENS,
    sender_user__isnull=False, recipient_user__isnull=False,
).values_list('sender_user_id', flat=True))

bal = defaultdict(Decimal)
for r in Balance.objects.filter(token__in=DOLLAR_BAL, account__account_type='personal',
                                account__deleted_at__isnull=True).values('account__user_id', 'amount'):
    bal[r['account__user_id']] += r['amount'] or 0

old = [u for u in users.values() if u['date_joined'] and u['date_joined'] < NOW - timedelta(days=30)]


def act30(u):
    return bool(u['last_activity_at'] and u['last_activity_at'] >= NOW - timedelta(days=30))


def ret30(u):
    return bool(u['last_activity_at'] and u['last_activity_at'] >= u['date_joined'] + timedelta(days=30))


def pct(a, b):
    return f"{100.0 * a / b:5.1f}%" if b else "   n/a"


def row(label, group):
    n = len(group)
    a = sum(act30(u) for u in group)
    r = sum(ret30(u) for u in group)
    print(f"  {label:<34}{n:>7}{a:>7}{pct(a, n):>8}{r:>7}{pct(r, n):>8}")


def table(title, pool):
    print(f"\n=== {title} ===")
    print(f"  {'cohort':<34}{'users':>7}{'act30':>7}{'%':>8}{'ret30+':>7}{'%':>8}")
    funded = [u for u in pool if u['id'] in first_in]
    unfunded = [u for u in pool if u['id'] not in first_in]
    row('never funded', unfunded)
    row('funded at least once', funded)
    row('  ↳ holds ≥$1 now', [u for u in funded if bal[u['id']] >= 1])
    row('  ↳ funded, now < $1 (drained)', [u for u in funded if bal[u['id']] < 1])
    row('  ↳ funded in first 7 days', [u for u in funded
                                       if first_in[u['id']] <= u['date_joined'] + timedelta(days=7)])
    row('sent a P2P transfer', [u for u in pool if u['id'] in p2p_senders])
    row('ALL', pool)


print(f"Real active users: {len(users)}   joined >30d ago: {len(old)}   ever funded (all): {len(first_in)}")
table("All countries, joined >30 days ago", old)
for cc in ('VE', 'BO', 'AR'):
    table(f"{cc} only, joined >30 days ago", [u for u in old if (u['phone_country'] or '').upper() == cc])
print("\nact30 = active in last 30 days; ret30+ = ever active ≥30 days after own signup")
print("Done.")
