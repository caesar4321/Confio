# Read-only: did the fee-sharing commission (launched FEE_REFERRAL_LAUNCH_AT)
# make members invite more, and their invited friends verify and top up more?
#
# Compares per-day rates in a pre-launch baseline window with the period
# since launch, and splits invite shares by the sharer's app version (the
# Android build that shows the new "Tu red de confianza ahora te paga" card).
#
# Run: ssh confio-prod 'cd /opt/confio && CONFIO_ENV=mainnet BASE_DAYS=14 NEW_BUILD=5.3.6
#      ./myvenv/bin/python manage.py shell' < scripts/ops/referral_impact.py
import os
from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from achievements.models import UserReferral
from conversion.models import FeeReferralPayout
from cusd_plus import fee_referral
from ramps.models import RampTransaction
from security.models import IdentityVerification
from users.models import User
from users.models_analytics import FunnelEvent

BASE_DAYS = int(os.environ.get('BASE_DAYS', '14'))
NEW_BUILD = os.environ.get('NEW_BUILD', '5.3.6')
now = timezone.now()
launch = fee_referral.launch_at()
if launch is None:
    raise SystemExit('FEE_REFERRAL_LAUNCH_AT is not set')
windows = {
    'baseline': (launch - timedelta(days=BASE_DAYS), launch),
    'since launch': (launch, now),
}
WAD = Decimal(10) ** 18
referred_ids = set(UserReferral.objects.filter(deleted_at__isnull=True, referrer_user__isnull=False)
                   .values_list('referred_user_id', flat=True))


def days(start, end):
    return max((end - start).total_seconds() / 86400, 1e-9)


def events(name, start, end):
    return FunnelEvent.objects.filter(event_name=name, created_at__gte=start, created_at__lt=end)


rows = []
for label, (start, end) in windows.items():
    d = days(start, end)
    shares = events('referral_whatsapp_share_tapped', start, end)
    referrals = UserReferral.objects.filter(deleted_at__isnull=True, referrer_user__isnull=False,
                                            created_at__gte=start, created_at__lt=end)
    verified = (IdentityVerification.all_objects
                .filter(user_id__in=referred_ids, verified_at__gte=start, verified_at__lt=end)
                .values('user_id').distinct())
    topups = RampTransaction.objects.filter(actor_user_id__in=referred_ids, direction='on_ramp',
                                            status='COMPLETED', created_at__gte=start, created_at__lt=end)
    payouts = FeeReferralPayout.objects.filter(created_at__gte=start, created_at__lt=end)
    rows.append((label, d, {
        'invite shares (WhatsApp)': shares.count(),
        'members sharing': shares.values('user_id').distinct().count(),
        'invite link clicks': events('referral_link_clicked', start, end).count(),
        'new referrals': referrals.count(),
        'members who referred': referrals.values('referrer_user_id').distinct().count(),
        'invited friends verified': verified.count(),
        'invited friends topping up': topups.values('actor_user_id').distinct().count(),
        'invited top-ups (count)': topups.count(),
        'invited top-ups (USD)': float(topups.aggregate(t=Sum('crypto_amount_actual'))['t'] or 0),
        'commission payouts': payouts.count(),
        'commissions paid (USD)': float(Decimal(payouts.aggregate(t=Sum('share_wei'))['t'] or 0) / WAD),
    }))

print(f'launch {launch:%Y-%m-%d %H:%M} UTC · now {now:%Y-%m-%d %H:%M} UTC · baseline {BASE_DAYS}d')
print(f'{"metric":32} {"baseline/day":>13} {"since/day":>11} {"since total":>12} {"change":>8}')
base, post = rows[0][2], rows[1][2]
for key in base:
    b, p = base[key] / rows[0][1], post[key] / rows[1][1]
    change = f'{(p / b - 1) * 100:+.0f}%' if b else ('new' if p else '—')
    print(f'{key:32} {b:13.2f} {p:11.2f} {post[key]:12.2f} {change:>8}')
print(f'(since-launch window = {rows[1][1] * 24:.1f} h; per-day rates over short windows are noisy, '
      'and verification / top-ups trail an invite by days)')

# Who is sharing since launch, by app version (NEW_BUILD shows the new card).
start, end = windows['since launch']
sharers = events('referral_whatsapp_share_tapped', start, end).values_list('user_id', flat=True)
versions = Counter(User.objects.filter(pk__in=set(sharers)).values_list('last_app_version', flat=True))
platforms = Counter(events('referral_whatsapp_share_tapped', start, end).values_list('platform', flat=True))
print(f'sharers since launch by app version: {dict(versions)}')
print(f'shares since launch by platform: {dict(platforms)}')
on_new = User.objects.filter(last_app_version=NEW_BUILD).count()
print(f'members whose last app version is {NEW_BUILD}: {on_new}')
