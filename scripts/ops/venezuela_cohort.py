"""Venezuela cohort read-out (read-only, aggregate counts only — no PII).

Run on prod:
    ssh confio-prod 'cd /opt/confio && myvenv/bin/python manage.py shell' < scripts/ops/venezuela_cohort.py

Questions it answers:
  1. Is VE signup volume organic (not Julian's creator cohort)?
  2. Do VE-phone users actually live in VE (last IP country)?
  3. KYC completion vs other countries.
  4. P2P network: share of VE users who sent/received; diaspora -> VE corridor.
  5. Recipient loop: did a P2P-acquired VE user later send or refer?
  6. Retention after first inflow (activity 30/90d) and balance kept, vs other countries.

Balances use stored rows; CUSD_PLUS is shares (~1 USD each), counted 1:1.
"""
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Max, Min
from django.utils import timezone

from achievements.models import UserReferral
from blockchain.models import Balance
from ramps.models import RampTransaction
from security.models import IdentityVerification, IPDeviceUser, UserSession
from send.models import SendTransaction
from users.analytics import get_real_users_queryset
from users.models import User

try:
    from usdc_transactions.models import USDCDeposit
except Exception:  # pragma: no cover
    USDCDeposit = None

NOW = timezone.now()
DOLLAR_TOKENS = ('CUSD', 'USDC', 'USDT', 'CUSD_PLUS')
DOLLAR_BAL = ('CUSD', 'USDC', 'CUSD_BSC', 'USDT_BSC', 'CUSD_PLUS')
COMPARE = ['VE', 'CO', 'PE', 'AR', 'MX', 'BO', 'CL', 'EC', 'US', 'ES']


def pct(a, b):
    return f"{(100.0 * float(a) / float(b)):5.1f}%" if b else "   n/a"


def hdr(t):
    print(f"\n=== {t} ===")


# Real users only: phone captured, Play pre-launch robots out (users/analytics.py).
all_signups = User.objects.filter(is_staff=False).count()
users = get_real_users_queryset().filter(is_staff=False).values('id', 'phone_country', 'date_joined')
country_of = {u['id']: (u['phone_country'] or '??').upper() for u in users}
joined = {u['id']: u['date_joined'] for u in users}
by_country = defaultdict(set)
for uid, c in country_of.items():
    by_country[c].add(uid)
ve = by_country['VE']
print(f"Signups (non-staff): {all_signups}   real users (phone verified): {len(country_of)}   VE real users: {len(ve)}")

# ── 1. Signups by week + attribution ────────────────────────────────
hdr("1. VE signups per week (last 16 weeks) vs all, with referral cohort")
cohort_of = dict(
    UserReferral.objects.filter(referred_user_id__in=country_of.keys())
    .values_list('referred_user_id', 'cohort')
)
weeks = defaultdict(lambda: Counter())
for uid in country_of:
    d = joined[uid]
    if not d or d < NOW - timedelta(weeks=16):
        continue
    wk = (d - timedelta(days=d.weekday())).date()
    weeks[wk]['all'] += 1
    if uid in ve:
        weeks[wk]['ve'] += 1
        weeks[wk]['ve_' + (cohort_of.get(uid) or 'no_referral_row')] += 1
print(f"{'week':<12}{'all':>6}{'VE':>6}{'VE%':>8}  VE by cohort")
for wk in sorted(weeks):
    w = weeks[wk]
    coh = {k[3:]: v for k, v in w.items() if k.startswith('ve_')}
    print(f"{str(wk):<12}{w['all']:>6}{w['ve']:>6}{pct(w['ve'], w['all']):>8}  {dict(coh)}")
all_ve_coh = Counter(cohort_of.get(u) or 'no_referral_row' for u in ve)
print("VE lifetime cohort mix:", dict(all_ve_coh))

# ── 0. Data-quality diagnostics ────────────────────────────────────
hdr("0a. IP geo enrichment health")
from security.models import IPAddress
ipq = IPAddress.objects
tot = ipq.count()
filled = ipq.exclude(country_code__isnull=True).exclude(country_code='').count()
print(f"  IPAddress rows: {tot}, with country_code: {filled} ({pct(filled, tot)})")
for days in (7, 30, 90):
    since = NOW - timedelta(days=days)
    q = ipq.filter(first_seen__gte=since)
    f = q.exclude(country_code__isnull=True).exclude(country_code='').count()
    print(f"  first_seen last {days}d: {q.count()}, with country: {f}")
loc_keys = Counter()
for li in IPDeviceUser.objects.filter(user_id__in=ve).values_list('location_info', flat=True)[:2000]:
    if isinstance(li, dict):
        loc_keys.update(k for k, v in li.items() if v)
print("  IPDeviceUser.location_info non-empty keys (VE sample):", dict(loc_keys.most_common(10)))

hdr("0b. SendTransaction shape (all rows)")
st = SendTransaction.objects
print("  by status:", dict(Counter(st.values_list('status', flat=True))))
print("  by token:", dict(Counter(st.values_list('token_type', flat=True))))
conf = st.filter(status='CONFIRMED')
print(f"  CONFIRMED: {conf.count()}  sender_user null: {conf.filter(sender_user__isnull=True).count()}"
      f"  recipient_user null: {conf.filter(recipient_user__isnull=True).count()}"
      f"  is_invitation: {conf.filter(is_invitation=True).count()}"
      f"  sender_business: {conf.filter(sender_business__isnull=False).count()}"
      f"  recipient_business: {conf.filter(recipient_business__isnull=False).count()}")
print(f"  CONFIRMED last 90d: {conf.filter(created_at__gte=NOW - timedelta(days=90)).count()}")
ve_phone_recv = conf.filter(recipient_phone__startswith='+58').count()
ve_phone_recv2 = conf.filter(recipient_phone__startswith='58').count()
print(f"  CONFIRMED with recipient_phone +58…: {ve_phone_recv}  58…: {ve_phone_recv2}")

# ── 2. Residence: majority IP country (mirrors security/geo.py) ────
hdr("2. VE-phone users by majority IP country (non-empty IPs only)")
w = defaultdict(Counter)
for row in (IPDeviceUser.objects.filter(user_id__in=ve)
            .exclude(ip_address__country_code__isnull=True).exclude(ip_address__country_code='')
            .exclude(ip_address__is_vpn=True).exclude(ip_address__is_datacenter=True)
            .values('user_id', 'total_sessions', 'ip_address__country_code')):
    w[row['user_id']][row['ip_address__country_code'].upper()] += max(row['total_sessions'] or 0, 1)
res = Counter()
for uid, c in w.items():
    top, n = c.most_common(1)[0]
    res[top if n * 2 > sum(c.values()) else 'mixed'] += 1
print(f"with usable IP country: {len(w)}/{len(ve)}")
for c, n in res.most_common(12):
    print(f"  {c}: {n} ({pct(n, len(w))})")
kyc_country = Counter(
    IdentityVerification.objects.filter(user_id__in=ve, status='verified')
    .values_list('document_issuing_country', flat=True))
print("  VE verified KYC by document country:", dict(kyc_country))

# ── 3. KYC completion ───────────────────────────────────────────────
hdr("3. KYC verified rate by phone country")
kyc_users = set(IdentityVerification.objects.filter(status='verified').values_list('user_id', flat=True))
for c in COMPARE:
    s = by_country[c]
    print(f"  {c}: {len(s & kyc_users):>6}/{len(s):<6} {pct(len(s & kyc_users), len(s))}")

# ── 4. P2P network ──────────────────────────────────────────────────
hdr("4. P2P sends (CONFIRMED, dollar tokens, user→user)")
p2p = list(
    SendTransaction.objects.filter(
        status='CONFIRMED', token_type__in=DOLLAR_TOKENS,
        sender_user__isnull=False, recipient_user__isnull=False,
    ).values('sender_user_id', 'recipient_user_id', 'amount', 'created_at', 'is_invitation')
)
p2p = [t for t in p2p if t['sender_user_id'] != t['recipient_user_id']]
senders, receivers = defaultdict(set), defaultdict(set)
for t in p2p:
    senders[country_of.get(t['sender_user_id'], '??')].add(t['sender_user_id'])
    receivers[country_of.get(t['recipient_user_id'], '??')].add(t['recipient_user_id'])
print(f"{'cc':<4}{'users':>7}{'sent≥1':>9}{'%':>8}{'recv≥1':>9}{'%':>8}")
for c in COMPARE:
    n = len(by_country[c])
    print(f"{c:<4}{n:>7}{len(senders[c]):>9}{pct(len(senders[c]), n):>8}"
          f"{len(receivers[c]):>9}{pct(len(receivers[c]), n):>8}")

hdr("4b. Corridors touching VE (sender cc → recipient cc): count, USD, distinct senders")
corr = defaultdict(lambda: [0, Decimal(0), set()])
for t in p2p:
    a, b = country_of.get(t['sender_user_id'], '??'), country_of.get(t['recipient_user_id'], '??')
    if 'VE' in (a, b):
        k = corr[(a, b)]
        k[0] += 1
        k[1] += t['amount'] or 0
        k[2].add(t['sender_user_id'])
for (a, b), (n, amt, s) in sorted(corr.items(), key=lambda kv: -kv[1][0]):
    print(f"  {a}→{b}: {n} txs, ${amt:,.0f}, {len(s)} senders")
recent = [t for t in p2p if t['created_at'] >= NOW - timedelta(days=90)
          and country_of.get(t['recipient_user_id']) == 'VE'
          and country_of.get(t['sender_user_id']) != 'VE']
print(f"  last 90d foreign→VE: {len(recent)} txs, "
      f"${sum((t['amount'] or 0) for t in recent):,.0f}")

hdr("4c. Same-country vs cross-border share of P2P, by sender country")
for c in COMPARE:
    mine = [t for t in p2p if country_of.get(t['sender_user_id']) == c]
    cross = [t for t in mine if country_of.get(t['recipient_user_id']) != c]
    print(f"  {c}: {len(mine)} sends, cross-border {pct(len(cross), len(mine))}")

# ── 5. Recipient loop ───────────────────────────────────────────────
hdr("5. Recipient loop: VE users whose FIRST inflow was a P2P receive")
first_recv = {}
for t in sorted(p2p, key=lambda t: t['created_at']):
    first_recv.setdefault(t['recipient_user_id'], t)
first_send = {}
for t in sorted(p2p, key=lambda t: t['created_at']):
    first_send.setdefault(t['sender_user_id'], t['created_at'])
referred_by = Counter(
    UserReferral.objects.filter(referrer_user_id__in=ve).values_list('referrer_user_id', flat=True)
)
# P2P-acquired = received a P2P within 7 days of signup
acq = [u for u, t in first_recv.items()
       if u in ve and joined.get(u) and t['created_at'] <= joined[u] + timedelta(days=7)]
later_sent = [u for u in acq if u in first_send and first_send[u] > first_recv[u]['created_at']]
later_ref = [u for u in acq if referred_by.get(u)]
print(f"  P2P-acquired VE users (recv within 7d of signup): {len(acq)}")
print(f"    of which sender was foreign: "
      f"{sum(1 for u in acq if country_of.get(first_recv[u]['sender_user_id']) != 'VE')}")
print(f"    later sent P2P themselves: {len(later_sent)} ({pct(len(later_sent), len(acq))})")
print(f"    later referred someone:    {len(later_ref)} ({pct(len(later_ref), len(acq))})")
print(f"  VE users who referred ≥1 (any): {len(referred_by)}  total referrals: {sum(referred_by.values())}")

# ── 6. Inflows, retention, balance kept ─────────────────────────────
hdr("6. First dollar inflow → activity retention and balance kept")
first_in = {}
inflow_total = defaultdict(Decimal)


def add_inflow(uid, when, amt):
    if uid is None or when is None:
        return
    if uid not in first_in or when < first_in[uid]:
        first_in[uid] = when
    inflow_total[uid] += Decimal(amt or 0)


for r in RampTransaction.objects.filter(direction='on_ramp', status='COMPLETED', actor_user__isnull=False) \
        .values('actor_user_id', 'created_at', 'final_amount'):
    add_inflow(r['actor_user_id'], r['created_at'], r['final_amount'])
for r in SendTransaction.objects.filter(status='CONFIRMED', token_type__in=DOLLAR_TOKENS,
                                        recipient_user__isnull=False) \
        .values('recipient_user_id', 'sender_user_id', 'created_at', 'amount'):
    if r['sender_user_id'] != r['recipient_user_id']:
        add_inflow(r['recipient_user_id'], r['created_at'], r['amount'])
if USDCDeposit is not None:
    try:
        for r in USDCDeposit.objects.filter(status='COMPLETED', actor_user__isnull=False) \
                .values('actor_user_id', 'created_at', 'amount'):
            add_inflow(r['actor_user_id'], r['created_at'], r['amount'])
    except Exception as e:
        print("  (USDCDeposit skipped:", e, ")")

bal = defaultdict(Decimal)
for r in Balance.objects.filter(token__in=DOLLAR_BAL, account__account_type='personal',
                                account__deleted_at__isnull=True) \
        .values('account__user_id', 'amount'):
    bal[r['account__user_id']] += r['amount'] or 0

sessions = defaultdict(list)
depositors = set(first_in)
for r in UserSession.objects.filter(user_id__in=depositors).values('user_id', 'started_at'):
    sessions[r['user_id']].append(r['started_at'])


def active_after(uid, start_days, end_days):
    t0 = first_in[uid]
    lo, hi = t0 + timedelta(days=start_days), t0 + timedelta(days=end_days)
    return any(lo <= s < hi for s in sessions.get(uid, ()))


print(f"{'cc':<4}{'deposit':>8}{'act30-60':>10}{'act90-120':>11}{'bal≥$1':>8}{'kept$/in$':>11}")
for c in COMPARE:
    d = [u for u in depositors if country_of.get(u) == c]
    e30 = [u for u in d if first_in[u] <= NOW - timedelta(days=60)]
    e90 = [u for u in d if first_in[u] <= NOW - timedelta(days=120)]
    r30 = sum(active_after(u, 30, 60) for u in e30)
    r90 = sum(active_after(u, 90, 120) for u in e90)
    holders = sum(1 for u in d if bal[u] >= 1)
    tin = sum(inflow_total[u] for u in d)
    kept = sum(bal[u] for u in d)
    print(f"{c:<4}{len(d):>8}{pct(r30, len(e30)):>10}{pct(r90, len(e90)):>11}"
          f"{pct(holders, len(d)):>8}{pct(kept, tin):>11}")
print("  act30-60 = any session days 30–60 after first inflow (eligible cohort only)")
print("  kept$/in$ = current dollar balance ÷ lifetime dollar inflows (higher = holds, not passes through)")

ve_recv_only = [u for u in ve if u in receivers['VE'] and u not in senders['VE']]
print(f"\n  VE receivers who never sent: {len(ve_recv_only)}; "
      f"holding ≥$1 now: {sum(1 for u in ve_recv_only if bal[u] >= 1)}")
print("\nDone.")
