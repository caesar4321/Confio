"""Is US stocks the product? (read-only, aggregate rows, no identifiers)

Run on prod:
    ssh confio-prod 'cd /opt/confio && myvenv/bin/python manage.py shell' < scripts/ops/invest_pmf.py

Sections
  A  weekly series (16w): signups, verified, on-ramp, stock / crypto / perps users and $
  B  stock concentration (30d, lifetime) and ticket sizes
  C  who trades stocks in the last 30d: new signups vs old-activated vs repeat vs dormant returners
  D  monthly signup cohorts: verified -> funded -> first stock buy (7d / 30d / ever)
  E  stock first-trade cohorts: still trading in later months
  F  country split (30d)
  G  revenue (3 x 30d): 0.9% perimeter fee split into stock / crypto / deposit / withdrawal
  H  social + referral: shares, impressions, referred users who trade
"""
import re
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q

from blockchain.models import CryptoTrade, PerpPosition, SponsoredBatch
from conversion.models import Conversion, CusdFeeEvent
from ramps.models import RampTransaction
from security.identity_status import PERSONAL
from security.models import IdentityVerification
from users.analytics import get_real_users_queryset
from users.models_unified import UnifiedTransactionTable

try:
    from inbox.models import ActivityShareImpression, CommunityActivityShare, CommunityFollow
except Exception:  # pragma: no cover
    ActivityShareImpression = CommunityActivityShare = CommunityFollow = None
from achievements.models import UserReferral

from django.utils import timezone

NOW = timezone.now()
D = Decimal
W = 16
ENTRY = ('usdc_to_cusd', 'usdt_to_cusd', 'to_savings')


def wk(t):
    """0 = the last 7 days, 1 = the 7 before, ..."""
    return (NOW - t).days // 7


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


users = {u['id']: u for u in get_real_users_queryset().filter(is_active=True, is_staff=False)
         .values('id', 'phone_country', 'date_joined', 'onboarded_at', 'last_activity_at')}
U = set(users)
cc = {u: (r['phone_country'] or '??').upper() for u, r in users.items()}
joined = {u: (r['onboarded_at'] or r['date_joined']) for u, r in users.items()}

verified_at = {}
for uid, t in IdentityVerification.all_documents.filter(PERSONAL, status='verified', user_id__in=U) \
        .values_list('user_id', 'verified_at'):
    if t and (uid not in verified_at or t < verified_at[uid]):
        verified_at[uid] = t

# --- money in: on-ramp + perimeter entry (covers USDT/USDC deposits converted to cUSD)
deposits = defaultdict(list)  # uid -> [(t, usd)]
for uid, t, amt in RampTransaction.objects.filter(direction='on_ramp', status='COMPLETED', actor_user_id__in=U) \
        .values_list('actor_user_id', 'created_at', 'crypto_amount_actual'):
    deposits[uid].append((t, D(amt or 0)))
onramp_users_wk = defaultdict(set)
onramp_usd_wk = defaultdict(D)
for uid, v in deposits.items():
    for t, a in v:
        if wk(t) < W:
            onramp_users_wk[wk(t)].add(uid)
            onramp_usd_wk[wk(t)] += a
for uid, t in Conversion.objects.filter(status='COMPLETED', is_deleted=False, actor_user_id__in=U) \
        .filter(Q(perimeter_direction='entry') | Q(perimeter_direction='', conversion_type__in=ENTRY)) \
        .values_list('actor_user_id', 'created_at'):
    deposits[uid].append((t, D(0)))  # timing only (amount already counted via ramp or is a wallet deposit)
first_dep = {u: min(t for t, _ in v) for u, v in deposits.items() if v}

# --- stocks
stock = defaultdict(list)  # uid -> [(t, usd, side, ticker)]
batches = SponsoredBatch.objects.filter(user_id__in=U, status='confirmed', kind__in=('stock_buy', 'stock_sell'))
uni = {b: (a, d) for b, a, d in UnifiedTransactionTable.objects.filter(sponsored_batch__in=batches)
       .values_list('sponsored_batch_id', 'amount', 'description')}
for bid, uid, t, kind in batches.values_list('id', 'user_id', 'created_at', 'kind'):
    amt, desc = uni.get(bid, (0, ''))
    m = re.search(r'de\s+(\S+)\s*$', desc or '')
    stock[uid].append((t, abs(D(amt or 0)), 'buy' if kind == 'stock_buy' else 'sell', (m.group(1) if m else '?').upper()))
crypto = defaultdict(list)
for uid, t, usd, sym, kind in CryptoTrade.objects.filter(batch__user_id__in=U) \
        .values_list('batch__user_id', 'traded_at', 'usd', 'symbol', 'kind'):
    crypto[uid].append((t, abs(D(usd or 0)), kind, sym.upper()))
perps = defaultdict(list)
for uid, t, m in PerpPosition.objects.filter(user_id__in=U).exclude(state__in=('quoted', 'failed', 'cancelled', 'refunded')) \
        .values_list('user_id', 'created_at', 'margin_usd'):
    perps[uid].append((t, D(m or 0)))

print(f"NOW {NOW:%Y-%m-%d %H:%M}  real users {len(U)}  verified {len(verified_at)}  ever deposited {len(first_dep)}")
print(f"ever traded: stocks {len(stock)}  gold/BTC {len(crypto)}  perps {len(perps)}  "
      f"any {len(set(stock) | set(crypto) | set(perps))}")

# ---------------- A
print("\n=== A. Weekly (w0 = last 7 days) ===")
print(f"  {'wk':>3}{'signup':>7}{'verif':>6}{'ramp u':>7}{'ramp $':>9}"
      f"{'stk u':>6}{'stk n':>6}{'stk buy$':>9}{'stk sel$':>9}{'1st stk':>8}"
      f"{'cr u':>5}{'cr $':>8}{'perp u':>7}{'perp $':>8}{'inv u':>6}")
for w in range(W - 1, -1, -1):
    su = sum(1 for u in U if joined[u] and wk(joined[u]) == w)
    ve = sum(1 for t in verified_at.values() if wk(t) == w)
    s_rows = [(u, r) for u, v in stock.items() for r in v if wk(r[0]) == w]
    su_set = {u for u, _ in s_rows}
    first_stk = sum(1 for u, v in stock.items() if wk(min(r[0] for r in v)) == w)
    c_rows = [(u, r) for u, v in crypto.items() for r in v if wk(r[0]) == w]
    p_rows = [(u, r) for u, v in perps.items() for r in v if wk(r[0]) == w]
    inv = su_set | {u for u, _ in c_rows} | {u for u, _ in p_rows}
    print(f"  {w:>3}{su:>7}{ve:>6}{len(onramp_users_wk[w]):>7}{onramp_usd_wk[w]:>9,.0f}"
          f"{len(su_set):>6}{len(s_rows):>6}{sum(r[1] for _, r in s_rows if r[2] == 'buy'):>9,.0f}"
          f"{sum(r[1] for _, r in s_rows if r[2] == 'sell'):>9,.0f}{first_stk:>8}"
          f"{len({u for u, _ in c_rows}):>5}{sum(r[1] for _, r in c_rows):>8,.0f}"
          f"{len({u for u, _ in p_rows}):>7}{sum(r[1] for _, r in p_rows):>8,.0f}{len(inv):>6}")

# ---------------- B
print("\n=== B. Stock concentration & tickets ===")
for label, since in (('30d', NOW - timedelta(days=30)), ('lifetime', None)):
    vol = {u: sum(r[1] for r in v if since is None or r[0] >= since) for u, v in stock.items()}
    vol = {u: x for u, x in vol.items() if x > 0}
    tot = sum(vol.values()) or D(1)
    s = sorted(vol.values(), reverse=True)
    print(f"  {label:<9} users {len(vol):>4}  vol ${tot:,.0f}  top1 {100 * s[0] / tot if s else 0:.0f}%  "
          f"top5 {100 * sum(s[:5]) / tot:.0f}%  top10 {100 * sum(s[:10]) / tot:.0f}%")
buys30 = [r[1] for v in stock.values() for r in v if r[2] == 'buy' and r[0] >= NOW - timedelta(days=30)]
print("  30d buy tickets:", dict(Counter('<$5' if a < 5 else '$5-20' if a < 20 else '$20-50' if a < 50
                                          else '$50-100' if a < 100 else '$100-250' if a < 250 else '$250+'
                                          for a in buys30)))
print("  30d tickers:", Counter(r[3] for v in stock.values() for r in v if r[0] >= NOW - timedelta(days=30)).most_common(15))
print("  30d per-user buy-days:", dict(Counter(min(n, 10) for n in (
    len({r[0].date() for r in v if r[2] == 'buy' and r[0] >= NOW - timedelta(days=30)}) for v in stock.values()) if n)))

# ---------------- C
print("\n=== C. Who traded stocks in the last 30d ===")
cut = NOW - timedelta(days=30)
seg = Counter()
seg_vol = defaultdict(D)
gaps = []
for u, v in stock.items():
    recent = [r for r in v if r[0] >= cut]
    if not recent:
        continue
    first_recent = min(r[0] for r in recent)
    prior_trades = [r[0] for r in v if r[0] < cut]
    prior_touch = [t for t in prior_trades] + [t for t, _ in deposits.get(u, []) if t < first_recent] \
        + [r[0] for r in crypto.get(u, []) if r[0] < first_recent]
    last_prior = max(prior_touch) if prior_touch else None
    if joined[u] and joined[u] >= cut:
        s = '1 new signup (<30d)'
    elif not prior_trades and (last_prior is None or (first_recent - last_prior).days >= 60):
        s = '2 dormant 60d+ -> first stock'
    elif not prior_trades:
        s = '3 old user, first stock (recently active)'
    elif (first_recent - max(prior_trades)).days >= 30:
        s = '4 lapsed stock trader returned'
    else:
        s = '5 continuing stock trader'
    seg[s] += 1
    seg_vol[s] += sum(r[1] for r in recent)
    if last_prior:
        gaps.append((first_recent - last_prior).days)
for s in sorted(seg):
    print(f"  {s:<44}{seg[s]:>5} users  ${seg_vol[s]:>9,.0f}")
age = Counter()
for u in (u for u, v in stock.items() if any(r[0] >= cut for r in v)):
    m = (NOW - joined[u]).days // 30 if joined[u] else -1
    age['<1m' if m < 1 else '1-3m' if m < 3 else '3-6m' if m < 6 else '6-12m' if m < 12 else '12m+'] += 1
print("  account age of 30d stock traders:", dict(age))

# ---------------- D
print("\n=== D. Monthly signup cohorts ===")
print(f"  {'month':<8}{'signup':>7}{'verif':>7}{'funded':>7}{'stk7d':>7}{'stk30d':>7}{'stk ever':>9}{'any inv':>8}")
by_m = defaultdict(list)
for u in U:
    if joined[u] and joined[u] >= NOW - timedelta(days=200):
        by_m[joined[u].strftime('%Y-%m')].append(u)
for m in sorted(by_m):
    us = by_m[m]
    f_stk = {u: min(r[0] for r in stock[u]) for u in us if u in stock}
    print(f"  {m:<8}{len(us):>7}{pct(sum(u in verified_at for u in us), len(us)):>7}"
          f"{pct(sum(u in first_dep for u in us), len(us)):>7}"
          f"{pct(sum((t - joined[u]).days <= 7 for u, t in f_stk.items()), len(us)):>7}"
          f"{pct(sum((t - joined[u]).days <= 30 for u, t in f_stk.items()), len(us)):>7}"
          f"{len(f_stk):>9}{sum(1 for u in us if u in stock or u in crypto or u in perps):>8}")

# ---------------- E
print("\n=== E. Stock cohorts by first-trade month: % trading again in month +1, +2, +3 ===")
fc = defaultdict(list)
for u, v in stock.items():
    fc[min(r[0] for r in v).strftime('%Y-%m')].append(u)
months = sorted(fc)
for m in months:
    us = fc[m]
    row = []
    for k in (1, 2, 3):
        idx = months.index(m) + k
        if idx >= len(months):
            row.append('  -')
            continue
        tm = months[idx]
        row.append(pct(sum(any(r[0].strftime('%Y-%m') == tm for r in stock[u]) for u in us), len(us)).rjust(4))
    print(f"  {m:<8} n={len(us):>4}   +1 {row[0]}  +2 {row[1]}  +3 {row[2]}")

# ---------------- F
print("\n=== F. Country split, last 30d ===")
ctry = defaultdict(lambda: [0, 0, 0, D(0), 0, 0])  # signups, verified, stk users, stk vol, perps u, crypto u
for u in U:
    if joined[u] and joined[u] >= cut:
        ctry[cc[u]][0] += 1
for u, t in verified_at.items():
    if t >= cut:
        ctry[cc[u]][1] += 1
for u, v in stock.items():
    r = [x for x in v if x[0] >= cut]
    if r:
        ctry[cc[u]][2] += 1
        ctry[cc[u]][3] += sum(x[1] for x in r)
for u, v in perps.items():
    if any(x[0] >= cut for x in v):
        ctry[cc[u]][4] += 1
for u, v in crypto.items():
    if any(x[0] >= cut for x in v):
        ctry[cc[u]][5] += 1
print(f"  {'cc':<4}{'signup':>7}{'verif':>6}{'stk u':>6}{'stk $':>9}{'perp u':>7}{'cr u':>5}")
for c, r in sorted(ctry.items(), key=lambda kv: -(kv[1][3] * 1000 + kv[1][0]))[:15]:
    print(f"  {c:<4}{r[0]:>7}{r[1]:>6}{r[2]:>6}{r[3]:>9,.0f}{r[4]:>7}{r[5]:>5}")

# ---------------- G
print("\n=== G. Revenue (0.9% perimeter fee, exact from CusdFeeEvent) ===")
print("  since router v2 (10-19) a stock buy = perimeter exit, a sale = entry; split by tx_hash")
trade_tx = {}
for h, k in SponsoredBatch.objects.filter(status='confirmed', kind__in=('stock_buy', 'stock_sell', 'crypto_buy',
                                                                         'crypto_sell', 'perps_open', 'perps_return')) \
        .exclude(tx_hash='').values_list('tx_hash', 'kind'):
    trade_tx[h.lower()] = k.split('_')[0]
for label, days in (('last 30d', 30), ('prev 30d', 60), ('30-60d ago', 90)):
    lo, hi = NOW - timedelta(days=days), NOW - timedelta(days=days - 30)
    fee = defaultdict(D)
    gross = defaultdict(D)
    for h, d, f, g in CusdFeeEvent.objects.filter(block_time__gte=lo, block_time__lt=hi) \
            .values_list('tx_hash', 'direction', 'fee_wei', 'gross_wei'):
        src = trade_tx.get(h.lower(), 'deposit' if d == 'entry' else 'withdrawal')
        fee[src] += D(f) / D(10 ** 18)
        gross[src] += D(g) / D(10 ** 18)
    tot = sum(fee.values())
    print(f"  {label:<11} total ${tot:,.2f}  " + "  ".join(
        f"{k} ${fee[k]:,.2f} (gross ${gross[k]:,.0f})" for k in sorted(fee, key=lambda x: -fee[x])))
    print(f"  {'':<11} perp margin opened ${sum(r[1] for v in perps.values() for r in v if lo <= r[0] < hi):,.0f}")

# ---------------- H
print("\n=== H. Social & referral ===")
if CommunityActivityShare is not None:
    sh = CommunityActivityShare.objects.filter(user_id__in=U)
    print("  shares by kind (all):", dict(Counter(sh.values_list('kind', flat=True))))
    print(f"  shares 30d {sh.filter(created_at__gte=cut).count()}  sharers 30d "
          f"{sh.filter(created_at__gte=cut).values('user_id').distinct().count()}  sharers ever "
          f"{sh.values('user_id').distinct().count()}")
    im = ActivityShareImpression.objects.filter(first_seen_at__gte=cut)
    print(f"  share prompt impressions 30d {im.count()}  offered {im.filter(offered=True).count()}  outcomes "
          f"{dict(Counter(im.values_list('outcome', flat=True)))}")
    print(f"  follows 30d {CommunityFollow.objects.filter(created_at__gte=cut).count()}  ever {CommunityFollow.objects.count()}")
    sharers = set(sh.values_list('user_id', flat=True))
    st30 = {u for u, v in stock.items() if any(r[0] >= cut for r in v)}
    print(f"  30d stock traders who ever shared: {len(st30 & sharers)}/{len(st30)}")
ref = UserReferral.objects.filter(referred_user_id__in=U)
ref60 = ref.filter(created_at__gte=NOW - timedelta(days=60))
rus = set(ref60.values_list('referred_user_id', flat=True))
print(f"  referrals created 60d {ref60.count()}  referred users that verified {sum(u in verified_at for u in rus)}  "
      f"funded {sum(u in first_dep for u in rus)}  traded stocks {sum(u in stock for u in rus)}")
new30 = {u for u in U if joined[u] and joined[u] >= cut}
print(f"  30d signups {len(new30)}: via referral {len(new30 & set(ref.values_list('referred_user_id', flat=True)))}")
print("Done.")
