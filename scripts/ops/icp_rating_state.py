"""ICP poll + rating modal pipeline, week by week (read-only, aggregate counts only).

Run on prod:
    ssh confio-prod 'cd /opt/confio && myvenv/bin/python manage.py shell' < scripts/ops/icp_rating_state.py

pendingModal = ICP when first_cusd_acquired_at is set and confio_icp_captured_at
is not; RATING when rating_prompt_due_at is set and confio_rating_prompted_at is
not. first_cusd_acquired_at is only written by the usdc_to_cusd Conversion and
the confirmed cUSD SendTransaction signals.
"""
from django.db.models import Count
from django.db.models.functions import TruncWeek

from users.models import User

COLS = [
    'date_joined',
    'first_cusd_acquired_at',
    'confio_icp_captured_at',
    'rating_prompt_due_at',
    'confio_rating_prompted_at',
]
LABELS = ['joined', 'first_cusd', 'icp_done', 'rate_due', 'rate_done']


def weekly(field):
    rows = (
        User.all_objects.filter(**{f'{field}__gte': '2026-06-01'})
        .annotate(w=TruncWeek(field)).values('w').annotate(n=Count('id'))
    )
    return {r['w'].date(): r['n'] for r in rows}


data = {c: weekly(c) for c in COLS}
weeks = sorted({w for d in data.values() for w in d})
print(f"{'week':<12}" + ''.join(f'{l:>12}' for l in LABELS))
for w in weeks:
    print(f'{str(w):<12}' + ''.join(f'{data[c].get(w, 0):>12}' for c in COLS))

print()
for c in COLS[1:]:
    latest = User.all_objects.exclude(**{c: None}).order_by(f'-{c}').values_list(c, flat=True).first()
    print(f'latest {c:<28} {latest}')

print()
print('pending ICP now   ', User.objects.filter(first_cusd_acquired_at__isnull=False, confio_icp_captured_at__isnull=True).count())
print('pending RATING now', User.objects.filter(rating_prompt_due_at__isnull=False, confio_rating_prompted_at__isnull=True).count())

# How many users first brought dollars in through a path that never arms the poll
# (same inflow definition as funded_retention.py), per month since August.
from collections import Counter

from ramps.models import RampTransaction
from send.models import SendTransaction

first_in = {}


def add(uid, when):
    if uid and when and (uid not in first_in or when < first_in[uid]):
        first_in[uid] = when


for r in RampTransaction.objects.filter(direction='on_ramp', status='COMPLETED').values_list('actor_user_id', 'created_at'):
    add(*r)
for s, rcp, when in SendTransaction.objects.filter(
        status='CONFIRMED', token_type__in=('CUSD', 'USDC', 'USDT', 'CUSD_PLUS'),
        recipient_user__isnull=False).values_list('sender_user_id', 'recipient_user_id', 'created_at'):
    if s != rcp:
        add(rcp, when)
armed = set(User.all_objects.filter(first_cusd_acquired_at__isnull=False).values_list('id', flat=True))
by_month, missed = Counter(), Counter()
for uid, when in first_in.items():
    if when.date().isoformat() >= '2026-08-01':
        m = when.strftime('%Y-%m')
        by_month[m] += 1
        if uid not in armed:
            missed[m] += 1
print()
print('month    first-funded  never armed')
for m in sorted(by_month):
    print(f'{m}  {by_month[m]:>12}  {missed[m]:>11}')
