# Read-only: who holds referral badge tiers, and how referral counts are
# distributed. Run: ssh confio-prod 'cd /opt/confio && CONFIO_ENV=mainnet
# ./myvenv/bin/python manage.py shell' < scripts/ops/referral_badges.py
from collections import Counter

from django.db.models import Count

from achievements.models import UserReferral
from security.identity_status import verified_user_ids
from users.models import User

live = UserReferral.objects.filter(deleted_at__isnull=True, referrer_user__isnull=False)
qualified = live.filter(referrer_reward_status__in=('eligible', 'claimed'))

q_counts = dict(qualified.order_by().values_list('referrer_user_id').annotate(n=Count('id')))
all_counts = dict(live.order_by().values_list('referrer_user_id').annotate(n=Count('id')))

tiers = Counter()
for uid, n in q_counts.items():
    tier = next((slug for t, slug in User.STATUS_TIER_THRESHOLDS if n >= t), 'member')
    tiers[tier] += 1
print('BADGE TIERS (qualified = friend completed first US$20 deposit)')
for t in ('early_supporter', 'community_builder', 'embajador'):
    print(f'  {t}: {tiers[t]}')
print('  users with >=1 qualified referral:', len(q_counts))

print('\nREFERRERS by live referrals (any status)')
buckets = Counter()
for n in all_counts.values():
    b = '1' if n == 1 else '2' if n == 2 else '3-9' if n < 10 else '10-49' if n < 50 else '50+'
    buckets[b] += 1
for b in ('1', '2', '3-9', '10-49', '50+'):
    print(f'  {b}: {buckets[b]}')
print('  total referrers:', len(all_counts), '| total live referrals:', sum(all_counts.values()))

referred_ids = list(live.values_list('referred_user_id', flat=True))
v = set(verified_user_ids(referred_ids))
print('\nreferred users verified (Didit):', len(v), 'of', len(set(referred_ids)))
rv = set(verified_user_ids(list(all_counts)))
print('referrers verified:', len(rv), 'of', len(all_counts))

print('\nTOP 15 referrers (live / qualified / verified referees / referrer verified)')
for uid, n in sorted(all_counts.items(), key=lambda kv: -kv[1])[:15]:
    mine = set(live.filter(referrer_user_id=uid).values_list('referred_user_id', flat=True))
    u = User.objects.filter(pk=uid).values_list('username', flat=True).first()
    print(f'  @{u}: {n} / {q_counts.get(uid, 0)} / {len(mine & v)} / {"yes" if uid in rv else "no"}')
