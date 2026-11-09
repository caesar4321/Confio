# Read-only: where one invited member sits in a referrer's fee-referral list.
# Run: ssh confio-prod 'cd /opt/confio && CONFIO_ENV=mainnet REFERRER=julianmoonluna
# FRIEND=julianm ./myvenv/bin/python manage.py shell' < scripts/ops/referral_lookup.py
import os

from achievements.models import UserReferral
from cusd_plus import fee_referral as f
from users.models import User

referrer_name = os.environ.get('REFERRER', 'julianmoonluna')
friend_name = os.environ.get('FRIEND', 'julianm')
referrer = User.objects.filter(username__iexact=referrer_name).first()
friend = User.objects.filter(username__iexact=friend_name).first()
print(f'referrer @{referrer_name}: id={getattr(referrer, "pk", None)}')
print(f'friend @{friend_name}: id={getattr(friend, "pk", None)} active={getattr(friend, "is_active", None)}')

rows = UserReferral.all_objects.filter(referred_user=friend) if friend else []
for r in rows:
    print(f'  referral {r.pk}: referrer_user={r.referrer_user_id} identifier={r.referrer_identifier!r} '
          f'deleted={r.deleted_at} created={r.created_at:%Y-%m-%d} status={r.status}')
if not rows:
    print('  no referral row for this member (they never entered a code / used a link)')

if referrer:
    statuses = f.friend_statuses(referrer)
    ids = [s['referral_id'] for s in statuses]
    print(f'referrer has {len(statuses)} live invitations; the old dashboard listed the newest {f.FRIENDS_LIST_MAX}')
    for r in rows:
        if r.pk in ids:
            pos = ids.index(r.pk)
            print(f'  friend is #{pos + 1} newest, status={statuses[pos]["status"]}, '
                  f'{"VISIBLE" if pos < f.FRIENDS_LIST_MAX else "HIDDEN by the 200 cap"} in the old list')
        else:
            print('  friend is not among this referrer\'s live invitations')
