"""Confío IA+ and Cuenta inteligente probe funnel (read-only, aggregate counts only).

Run on prod:
    ssh confio-prod 'cd /opt/confio && myvenv/bin/python manage.py shell' < scripts/ops/paid_offer_funnel.py

Distinct users per stage of the paid_offer_interest funnel (users/paid_offers.py),
split by door, then the waitlists: would-pay and volume answers, funded share and
country. Preview users (PAID_OFFER_PREVIEW_USER_IDS, the founder's test account)
are excluded. "Saw it" only counts builds at PAID_OFFER_MIN_APP_VERSION or later,
so compare runs over time, not against total users.
"""
from collections import Counter, defaultdict

from django.conf import settings

from users.models import FunnelEvent
from users.models_product_waitlist import ProductWaitlistEntry

PREVIEW = {int(p) for p in str(getattr(settings, 'PAID_OFFER_PREVIEW_USER_IDS', '') or '').split(',') if p.strip()}
STAGES = ('door_shown', 'detail_opened', 'avisame_tapped', 'solo_miraba', 'would_pay_answered', 'volume_answered')
PRODUCTS = {'ia_plus': 'Confío IA+', 'smart_account': 'Cuenta inteligente'}

events = FunnelEvent.objects.filter(event_name='paid_offer_interest').exclude(user_id__in=PREVIEW)
first = events.order_by('created_at').values_list('created_at', flat=True).first()
print(f"Probe events since {first:%Y-%m-%d %H:%M} UTC" if first else 'No probe events yet')

stage_users = defaultdict(set)
door_users = defaultdict(set)
for uid, product, props in events.values_list('user_id', 'source_type', 'properties'):
    props = props or {}
    stage_users[(product, props.get('stage'))].add(uid)
    door_users[(product, props.get('stage'), props.get('door') or '?')].add(uid)


def pct(a, b):
    return f"{100.0 * a / b:5.1f}%" if b else "   n/a"


for product, name in PRODUCTS.items():
    seen = len(stage_users[(product, 'door_shown')])
    print(f"\n=== {name} ===")
    print(f"  {'stage':<22}{'users':>7}{'of saw':>9}")
    for stage in STAGES:
        n = len(stage_users[(product, stage)])
        if n or stage in ('door_shown', 'detail_opened', 'avisame_tapped'):
            print(f"  {stage:<22}{n:>7}{pct(n, seen):>9}")
    doors = sorted({d for (p, s, d) in door_users if p == product})
    for door in doors:
        cells = [len(door_users[(product, s, door)]) for s in ('door_shown', 'detail_opened', 'avisame_tapped')]
        print(f"  door {door:<17} shown {cells[0]:>4}  opened {cells[1]:>4}  joined {cells[2]:>4}")

    waitlist = ProductWaitlistEntry.objects.filter(product=product).exclude(user_id__in=PREVIEW)
    n = waitlist.count()
    print(f"  waitlist: {n}")
    if n:
        print(f"    would pay:   {dict(Counter(waitlist.values_list('would_pay', flat=True)))}  ('' = unanswered)")
        if product == 'smart_account':
            print(f"    volume/mes:  {dict(Counter(waitlist.values_list('volume_range', flat=True)))}")
        print(f"    funded:      {dict(Counter(waitlist.values_list('funded', flat=True)))}")
        print(f"    country:     {Counter(waitlist.values_list('country', flat=True)).most_common(8)}")
        print(f"    door:        {dict(Counter(waitlist.values_list('door', flat=True)))}"
              f"  trigger: {dict(Counter(t or '-' for t in waitlist.values_list('trigger', flat=True)))}")

both = (set(ProductWaitlistEntry.objects.filter(product='ia_plus').values_list('user_id', flat=True))
        & set(ProductWaitlistEntry.objects.filter(product='smart_account').values_list('user_id', flat=True))) - PREVIEW
print(f"\nOn both waitlists: {len(both)}")
print("Done.")
