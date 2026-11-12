"""Who on Confío already trades like a trader? (read-only, aggregate rows, no identifiers)

Run on prod:
    ssh confio-prod 'cd /opt/confio && myvenv/bin/python manage.py shell' < scripts/ops/trader_profile.py

Per real user, lifetime (country = User.country, which already falls back to the
phone country):
  deposits  = COMPLETED perimeter-ENTRY Conversions (gross), withdrawals = EXIT (net)
  trades    = confirmed stock_buy/stock_sell SponsoredBatches (USD from the unified row)
              + CryptoTrade rows (BTCB, XAUt, ...)
Segments:
  active trader  = >= 10 trades
  capitalized    = >= $200 deposited
  core target    = both
  levered intent = signed the leveraged/inverse ETF disclosure (StockRiskAcknowledgement)
"""
import re
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal
from statistics import median

from django.db.models import Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from blockchain.models import CryptoTrade, SponsoredBatch, StockRiskAcknowledgement
from conversion.models import Conversion
from users.analytics import get_real_users_queryset
from users.models_unified import UnifiedTransactionTable

NOW = timezone.now()
D = Decimal
ENTRY = ('usdc_to_cusd', 'usdt_to_cusd', 'to_savings')
EXIT = ('cusd_to_usdc', 'cusd_to_usdt', 'from_savings')

cc_of = {u: (c or '??').upper() for u, c in get_real_users_queryset().filter(is_active=True)
         .values_list('id', 'country')}

live = Conversion.objects.filter(status='COMPLETED', is_deleted=False, actor_user_id__in=cc_of.keys()) \
    .exclude(perimeter_direction='internal')
dep, wd, max_dep = defaultdict(D), defaultdict(D), defaultdict(D)
for uid, amt in live.filter(Q(perimeter_direction='entry') | Q(perimeter_direction='', conversion_type__in=ENTRY)) \
        .values_list('actor_user_id', Coalesce('gross_amount_exact', 'from_amount')):
    dep[uid] += D(amt or 0)
    max_dep[uid] = max(max_dep[uid], D(amt or 0))
for uid, amt in live.filter(Q(perimeter_direction='exit') | Q(perimeter_direction='', conversion_type__in=EXIT)) \
        .values_list('actor_user_id', Coalesce('net_amount_exact', 'to_amount')):
    wd[uid] += D(amt or 0)

trades = defaultdict(list)  # uid -> [(t, usd, asset)]
tickers = Counter()
batches = SponsoredBatch.objects.filter(user_id__in=cc_of.keys(), status='confirmed', kind__in=('stock_buy', 'stock_sell'))
uni = {b: (a, d) for b, a, d in UnifiedTransactionTable.objects.filter(sponsored_batch__in=batches)
       .values_list('sponsored_batch_id', 'amount', 'description')}
for bid, uid, t in batches.values_list('id', 'user_id', 'created_at'):
    amt, desc = uni.get(bid, (0, ''))
    m = re.search(r'de\s+(\S+)\s*$', desc or '')
    tk = m.group(1).upper() if m else '?'
    tickers[tk] += 1
    trades[uid].append((t, D(amt or 0), tk))
for uid, t, usd, sym in CryptoTrade.objects.filter(batch__user_id__in=cc_of.keys()) \
        .values_list('batch__user_id', 'traded_at', 'usd', 'symbol'):
    tickers[sym.upper()] += 1
    trades[uid].append((t, D(usd or 0), sym.upper()))

levered = set(StockRiskAcknowledgement.objects.filter(user_id__in=cc_of.keys()).values_list('user_id', flat=True))

n_tr = {u: len(v) for u, v in trades.items()}
vol = {u: sum(r[1] for r in v) for u, v in trades.items()}
active = {u for u, n in n_tr.items() if n >= 10}
capital = {u for u, d in dep.items() if d >= 200}
core = active & capital


def med(xs):
    xs = [float(x) for x in xs]
    return f"{median(xs):,.0f}" if xs else "-"


print(f"Real users {len(cc_of)}   ever deposited {len(dep)}   ever traded {len(trades)}   "
      f"levered disclosure signed {len(levered)}")
print(f"active traders (>=10 trades) {len(active)}   capitalized (>=$200 dep) {len(capital)}   core (both) {len(core)}")

print("\n=== Distributions (users) ===")
print("  deposits:", dict(Counter('<$30' if d < 30 else '$30-200' if d < 200 else '$200-1k' if d < 1000
                                  else '$1k-5k' if d < 5000 else '$5k+' for d in dep.values())))
print("  trades:  ", dict(Counter('1' if n == 1 else '2-4' if n < 5 else '5-9' if n < 10 else '10-29' if n < 30
                                  else '30+' for n in n_tr.values())))

print("\n=== By phone country (countries with any trader or capitalized user) ===")
print(f"  {'cc':<4}{'traded':>7}{'active':>7}{'capital':>8}{'core':>6}{'levered':>8}"
      f"{'med dep$':>10}{'med trades':>11}{'vol $':>11}{'est fee $':>10}")
for cc in sorted({cc_of[u] for u in set(trades) | capital | levered}, key=lambda c: -sum(
        1 for u in active | capital if cc_of.get(u) == c)):
    tr = [u for u in trades if cc_of[u] == cc]
    a = [u for u in active if cc_of[u] == cc]
    c = [u for u in capital if cc_of[u] == cc]
    k = [u for u in core if cc_of[u] == cc]
    lv = [u for u in levered if cc_of[u] == cc]
    v = sum(vol[u] for u in tr)
    fee = v * D('0.009') + sum(dep[u] for u in dep if cc_of[u] == cc) * D('0.009')
    print(f"  {cc:<4}{len(tr):>7}{len(a):>7}{len(c):>8}{len(k):>6}{len(lv):>8}"
          f"{med([dep[u] for u in tr if dep.get(u)]):>10}{med([n_tr[u] for u in tr]):>11}{v:>11,.0f}{fee:>10,.0f}")

print("\n=== Top 25 users by traded volume (no identifiers) ===")
print(f"  {'#':>3} {'cc':<3}{'dep $':>9}{'max dep':>9}{'wd $':>9}{'trades':>7}{'vol $':>10}{'days':>5}"
      f"{'last':>6} {'lev':<4}top assets")
for i, u in enumerate(sorted(vol, key=lambda x: -vol[x])[:25], 1):
    v = trades[u]
    days = len({r[0].date() for r in v})
    last = (NOW - max(r[0] for r in v)).days
    top = ','.join(t for t, _ in Counter(r[2] for r in v).most_common(3))
    print(f"  {i:>3} {cc_of[u]:<3}{dep.get(u, 0):>9,.0f}{max_dep.get(u, 0):>9,.0f}{wd.get(u, 0):>9,.0f}"
          f"{n_tr[u]:>7}{vol[u]:>10,.0f}{days:>5}{last:>5}d {'yes' if u in levered else '':<4}{top}")

print("\n=== Most-traded assets (trade count) ===")
print("  ", tickers.most_common(25))

print("\n=== Concentration ===")
tot = sum(vol.values()) or 1
top10 = sum(sorted(vol.values(), reverse=True)[:10])
print(f"  top 10 users = {100 * float(top10 / tot):.0f}% of all traded volume (${tot:,.0f})")
recent = {u for u, v in trades.items() if max(r[0] for r in v) >= NOW - timedelta(days=30)}
print(f"  traded in last 30d: {len(recent)}   of which active traders: {len(recent & active)}   core: {len(recent & core)}")
print("Done.")
