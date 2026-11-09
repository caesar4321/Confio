# Read-only: who invites people to Confío (everyone except the founder's
# creator account), to design the referral card's hook.
# Run: ssh confio-prod 'cd /opt/confio && CONFIO_ENV=mainnet
# ./myvenv/bin/python manage.py shell' < scripts/ops/referrer_profile.py
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from achievements.models import UserReferral
from security.identity_status import verified_user_ids
from users.models import User
from users.models_unified import UnifiedTransactionTable as U

FOUNDER = 'JulianMoonLuna'
now = timezone.now()

live = UserReferral.objects.filter(deleted_at__isnull=True, referrer_user__isnull=False)
others = live.exclude(referrer_user__username__iexact=FOUNDER)
referrer_ids = list(others.order_by().values_list('referrer_user_id', flat=True).distinct())
referrers = User.objects.filter(pk__in=referrer_ids)
print(f'NON-FOUNDER REFERRERS: {len(referrer_ids)} | their live referrals: {others.count()}')


def pct(n, d):
    return f'{n} ({(100 * n / d):.0f}%)' if d else str(n)


def show(title, counter, total, top=10):
    print(f'\n{title}')
    for key, n in counter.most_common(top):
        print(f'  {key or "?"}: {pct(n, total)}')


show('Referrer country (User.country)', Counter(referrers.values_list('country', flat=True)), len(referrer_ids))
show('Cohort of their referrals', Counter(others.values_list('cohort', flat=True)), others.count())
sources = Counter()
for data in others.values_list('attribution_data', flat=True):
    data = data or {}
    sources[str(data.get('utm_source') or data.get('source') or data.get('channel') or '')] += 1
show('How their friends arrived (attribution source)', sources, others.count())

ages = Counter()
for joined in referrers.values_list('date_joined', flat=True):
    days = (now - joined).days
    ages['<30d' if days < 30 else '30-90d' if days < 90 else '90-180d' if days < 180 else '180d+'] += 1
show('Referrer account age', ages, len(referrer_ids))
verified = set(verified_user_ids(referrer_ids))
print(f'\nReferrers Didit-verified: {pct(len(verified), len(referrer_ids))}')

# What referrers themselves do with money (last 90 days, confirmed rows).
recent = U.objects.filter(transaction_date__gte=now - timedelta(days=90), deleted_at__isnull=True)
acting = Counter()
active_any = set()
for ttype in ('send', 'payment', 'ramp', 'conversion', 'exchange', 'presale'):
    ids = set(recent.filter(transaction_type=ttype).filter(
        Q(sender_user_id__in=referrer_ids) | Q(counterparty_user_id__in=referrer_ids)
    ).values_list('sender_user_id', flat=True)) & set(referrer_ids)
    acting[ttype] = len(ids)
    active_any |= ids
print(f'\nReferrers with any money activity in 90d: {pct(len(active_any), len(referrer_ids))}')
for ttype, n in acting.most_common():
    print(f'  {ttype}: {pct(n, len(referrer_ids))}')

# Did they invite by SENDING money to someone not yet on Confío?
send_invite = others.filter(cohort='send_invite').values('referrer_user_id').distinct().count()
print(f'\nReferrers who invited by sending money (send_invite cohort): {pct(send_invite, len(referrer_ids))}')

# Their friends: verified, and doing anything.
friend_ids = list(others.values_list('referred_user_id', flat=True))
fv = set(verified_user_ids(friend_ids))
friend_active = set(recent.filter(sender_user_id__in=friend_ids).values_list('sender_user_id', flat=True))
print(f'Their friends verified: {pct(len(fv), len(friend_ids))} | active in 90d: {pct(len(friend_active), len(friend_ids))}')

# Same country as their friends? (family/neighbour network vs. cross-border)
pairs = others.values_list('referrer_user__country', 'referred_user__country')
same = sum(1 for a, b in pairs if a and b and a == b)
cross = sum(1 for a, b in pairs if a and b and a != b)
print(f'Friend in same country: {same} | different country: {cross}')
show('Cross-border pairs (referrer -> friend)',
     Counter(f'{a}->{b}' for a, b in pairs if a and b and a != b), cross or 1, top=8)

# Comunidad / investor presence: do referrers post or have followers?
try:
    from inbox.models import ContentItem
    posters = set(ContentItem.objects.filter(author_user_id__in=referrer_ids).values_list('author_user_id', flat=True))
    print(f'\nReferrers who posted in Comunidad: {pct(len(posters), len(referrer_ids))}')
except Exception as exc:  # noqa: BLE001 — field names differ: skip the line
    print('\nComunidad posts: n/a', type(exc).__name__)

# Business owners among referrers (merchants inviting customers?)
try:
    from users.models import Account
    owners = set(Account.objects.filter(user_id__in=referrer_ids, account_type='business',
                                        deleted_at__isnull=True).values_list('user_id', flat=True))
    print(f'Referrers with a business account: {pct(len(owners), len(referrer_ids))}')
except Exception as exc:  # noqa: BLE001
    print('Business accounts: n/a', type(exc).__name__)

print('\nTOP 10 non-founder referrers: country | friends | friends verified | referrer verified | 90d activity')
top = others.order_by().values('referrer_user_id').annotate(n=Count('id')).order_by('-n')[:10]
for row in top:
    uid = row['referrer_user_id']
    u = User.objects.filter(pk=uid).values('username', 'country').first()
    mine = set(others.filter(referrer_user_id=uid).values_list('referred_user_id', flat=True))
    kinds = sorted(set(recent.filter(sender_user_id=uid).values_list('transaction_type', flat=True)))
    print(f"  @{u['username']}: {u['country'] or '?'} | {row['n']} | {len(mine & fv)} | "
          f"{'yes' if uid in verified else 'no'} | {','.join(kinds) or '-'}")
