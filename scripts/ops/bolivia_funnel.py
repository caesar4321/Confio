"""Bolivia investing funnel since 2026-10-01 (read-only, aggregate counts only).

Run on prod:
    ssh confio-prod 'cd /opt/confio && myvenv/bin/python manage.py shell' < scripts/ops/bolivia_funnel.py

Cohort: real users whose country is BO (User.country, which already falls
back to the phone country) who joined on/after START,
split by signup week (Monday). Definitions:
  deposit      = COMPLETED perimeter-ENTRY Conversion (ramps/metrics.py: money
                 crossing into Confío dollars, any rail), amount = gross
  stock buy    = confirmed SponsoredBatch kind=stock_buy, USD (fee incl.) from
                 its UnifiedTransactionTable row
  crypto buy   = CryptoTrade kind=crypto_buy (BTCB, XAUt, ...)
  league       = >=1 ledger-trusted PortfolioDailySnapshot day with
                 value_start_usd >= teams.league.MIN_SLEEVE_USD since START
                 (public-profile / verified filters not applied)
  fees (item 9, ALL Bolivian users, any signup date, activity since START):
                 entry/exit = exact Conversion fee; stock/crypto = ESTIMATE at
                 FEE_BPS on the trade amount (legacy 0.30% builds overstate).
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from statistics import mean, median

from django.db.models import Q
from django.db.models.functions import Coalesce

from blockchain.models import CryptoTrade, SponsoredBatch
from conversion.models import Conversion
from inbox.models import PortfolioDailySnapshot
from security.models import IdentityVerification
from teams.league import MIN_SLEEVE_USD
from users.analytics import get_real_users_queryset
from users.models_unified import UnifiedTransactionTable

START = datetime(2026, 10, 1, tzinfo=dt_tz.utc)
FEE_BPS = Decimal(90)
ENTRY = ('usdc_to_cusd', 'usdt_to_cusd', 'to_savings')
EXIT = ('cusd_to_usdc', 'cusd_to_usdt', 'from_savings')
D = Decimal


def pct(a, b):
    return f"{100.0 * float(a) / float(b):5.1f}%" if b else "   n/a"


def money(xs):
    xs = [float(x) for x in xs]
    return f"med ${median(xs):,.2f} / avg ${mean(xs):,.2f}" if xs else "n/a"


def week(d):
    return (d - timedelta(days=d.weekday())).date()


bo_all = dict(get_real_users_queryset().filter(country='BO', is_active=True)
              .values_list('id', 'date_joined'))
cohort = {u: j for u, j in bo_all.items() if j and j >= START}
print(f"Bolivian real users: {len(bo_all)}   joined since {START.date()}: {len(cohort)}")

# ── Ledgers ──────────────────────────────────────────────────────────
live = Conversion.objects.filter(status='COMPLETED', is_deleted=False, actor_user_id__in=bo_all.keys()) \
    .exclude(perimeter_direction='internal')
entries = live.filter(Q(perimeter_direction='entry') | Q(perimeter_direction='', conversion_type__in=ENTRY))
exits = live.filter(Q(perimeter_direction='exit') | Q(perimeter_direction='', conversion_type__in=EXIT))
dep = defaultdict(list)  # uid -> [(t, amount, source)]
for uid, t, amt, src, ctype in entries.values_list(
        'actor_user_id', 'created_at', Coalesce('gross_amount_exact', 'from_amount'), 'source', 'conversion_type'):
    dep[uid].append((t, D(amt or 0), f"{src}/{ctype}"))

trades = defaultdict(list)  # uid -> [(t, kind, usd, symbol)]
batches = SponsoredBatch.objects.filter(user_id__in=bo_all.keys(), status='confirmed',
                                        kind__in=('stock_buy', 'stock_sell'))
usd_by_batch = dict(UnifiedTransactionTable.objects.filter(sponsored_batch__in=batches)
                    .values_list('sponsored_batch_id', 'amount'))
for bid, uid, t, kind in batches.values_list('id', 'user_id', 'created_at', 'kind'):
    trades[uid].append((t, kind, D(usd_by_batch.get(bid) or 0), 'STOCK'))
for uid, t, kind, usd, sym in CryptoTrade.objects.filter(batch__user_id__in=bo_all.keys()) \
        .values_list('batch__user_id', 'traded_at', 'kind', 'usd', 'symbol'):
    trades[uid].append((t, kind, D(usd or 0), sym.upper()))
for v in list(dep.values()) + list(trades.values()):
    v.sort(key=lambda r: r[0])

kyc = set(IdentityVerification.all_objects.filter(user_id__in=cohort.keys(), status='verified')
          .values_list('user_id', flat=True))
league = set(PortfolioDailySnapshot.objects.filter(
    user_id__in=cohort.keys(), day__gte=START.date(), ledger_trusted=True,
    value_start_usd__gte=MIN_SLEEVE_USD).values_list('user_id', flat=True))


def first(rows, pred):
    return next((r for r in rows if pred(r)), None)


def stock_buys(uid):
    return [r for r in trades.get(uid, []) if r[1] == 'stock_buy']


# ── 1–5 by signup week ───────────────────────────────────────────────
print("\n=== 1-5. Funnel by signup week (cohort = joined since 10-01) ===")
print(f"{'week':<12}{'signup':>7}{'KYC':>6}{'%':>7}{'dep':>6}{'%':>7}{'stock':>7}{'%':>7}{'rebuy7d':>9}{'%buyers':>9}")
weeks = sorted({week(j) for j in cohort.values()})
tot = Counter()
for wk in weeks + ['ALL']:
    us = [u for u, j in cohort.items() if wk == 'ALL' or week(j) == wk]
    k = sum(u in kyc for u in us)
    d = sum(bool(dep.get(u)) for u in us)
    b = [u for u in us if stock_buys(u)]
    r7 = sum(1 for u in b if any(t <= stock_buys(u)[0][0] + timedelta(days=7) for t, *_ in stock_buys(u)[1:]))
    print(f"{str(wk):<12}{len(us):>7}{k:>6}{pct(k, len(us)):>7}{d:>6}{pct(d, len(us)):>7}"
          f"{len(b):>7}{pct(len(b), len(us)):>7}{r7:>9}{pct(r7, len(b)):>9}")

buyers = [u for u in cohort if stock_buys(u)]
print("\n=== 3. First deposit (cohort) ===")
fd = [dep[u][0] for u in cohort if dep.get(u)]
print(f"  depositors: {len(fd)}   first deposit {money([r[1] for r in fd])}")
print("  route (source/conversion_type):", dict(Counter(r[2] for r in fd).most_common(8)))
print(f"  deposit → first stock buy: {sum(1 for u in cohort if dep.get(u) and stock_buys(u))} of {len(fd)} depositors")
print(f"  bought stock with no recorded deposit: {sum(1 for u in buyers if not dep.get(u))}")

print("\n=== 3b. On-ramp attempts (cohort, RampTransaction on_ramp, any status) ===")
from ramps.models import RampTransaction
att = list(RampTransaction.objects.filter(direction='on_ramp', actor_user_id__in=cohort.keys())
           .values_list('actor_user_id', 'provider', 'status', 'fiat_currency', 'fiat_amount', 'final_amount'))
print(f"  attempts: {len(att)} by {len({a[0] for a in att})} users   by provider/status:",
      dict(Counter((a[1], a[2]) for a in att).most_common(10)))
bob = [float(a[4]) for a in att if (a[3] or '').upper() == 'BOB' and a[4]]
if bob:
    print(f"  BOB amounts: med Bs {median(bob):,.0f}, min Bs {min(bob):,.0f}, max Bs {max(bob):,.0f};",
          f"exactly 350: {sum(1 for x in bob if abs(x - 350) < 0.5)}, under 350: {sum(1 for x in bob if x < 349.5)}")
done = [float(a[5]) for a in att if a[2] == 'COMPLETED' and a[5]]
print(f"  completed: {len(done)}   USD credited {money(done)}")
started_not_done = {a[0] for a in att} - {a[0] for a in att if a[2] == 'COMPLETED'}
print(f"  users who started but never completed an on-ramp: {len(started_not_done)}")

print("\n=== 4-5. First stock buy & repeat (cohort) ===")
print(f"  stock buyers: {len(buyers)}   first buy {money([stock_buys(u)[0][2] for u in buyers])}")
any_re = sum(1 for u in buyers if len(stock_buys(u)) > 1)
el30 = [u for u in buyers if stock_buys(u)[0][0] <= datetime.now(dt_tz.utc) - timedelta(days=30)]
print(f"  bought again (any time so far): {any_re} ({pct(any_re, len(buyers))})")
print(f"  30-day rebuy: only {len(el30)} buyers are 30+ days past first buy — not measurable yet")
print(f"  stock buys per buyer: {money([len(stock_buys(u)) for u in buyers]).replace('$', '')}")

# ── 6 BTCB / XAUt ────────────────────────────────────────────────────
print("\n=== 6. BTCB / XAUt (cohort) ===")
for sym in ('BTCB', 'XAUT'):
    rows = [r for u in cohort for r in trades.get(u, []) if r[1] == 'crypto_buy' and r[3] == sym]
    users = {u for u in cohort for r in trades.get(u, []) if r[1] == 'crypto_buy' and r[3] == sym}
    print(f"  {sym}: {len(users)} users ({pct(len(users & set(buyers)), len(buyers))} of stock buyers), "
          f"{len(rows)} buys, per buy {money([r[2] for r in rows])}")
crypto_only = [u for u in cohort if not stock_buys(u) and any(r[1] == 'crypto_buy' for r in trades.get(u, []))]
print(f"  bought crypto/metal but never a stock: {len(crypto_only)}")

# ── 7 cumulative invested ────────────────────────────────────────────
print("\n=== 7. Cumulative invested per investor (stock + crypto buys, cohort) ===")
inv = {u: sum(r[2] for r in trades.get(u, []) if r[1] in ('stock_buy', 'crypto_buy')) for u in cohort}
inv = {u: v for u, v in inv.items() if v > 0}
bands = Counter()
for v in inv.values():
    bands['<$10' if v < 10 else '$10-50' if v < 50 else '$50-200' if v < 200 else '$200+'] += 1
print(f"  investors: {len(inv)}   ", {k: bands.get(k, 0) for k in ('<$10', '$10-50', '$50-200', '$200+')},
      f"   total ${sum(inv.values()):,.2f}, {money(inv.values())}")

# ── 8 league vs not ──────────────────────────────────────────────────
print("\n=== 8. League-qualifying (>= $10 invested on a trusted day) vs not, among investors ===")
for label, grp in (('league', [u for u in inv if u in league]), ('not league', [u for u in inv if u not in league])):
    n_tr = [len(trades.get(u, [])) for u in grp]
    print(f"  {label:<11} users {len(grp):>4}   trades/user {money(n_tr).replace('$', '')}   "
          f"invested {money([inv[u] for u in grp])}")

# ── 9 fees from ALL Bolivian users since START ───────────────────────
print(f"\n=== 9. 0.9% fees from ALL Bolivian users, activity since {START.date()} ===")
fee_in = sum(D(f or 0) for f in entries.filter(created_at__gte=START).values_list(Coalesce('fee_amount_exact', 'fee_amount'), flat=True))
fee_out = sum(D(f or 0) for f in exits.filter(created_at__gte=START).values_list(Coalesce('fee_amount_exact', 'fee_amount'), flat=True))
vol_in = sum(r[1] for v in dep.values() for r in v if r[0] >= START)
stock_fee = crypto_fee = D(0)
stock_vol = crypto_vol = D(0)
for v in trades.values():
    for t, kind, usd, sym in v:
        if t < START:
            continue
        f = usd * FEE_BPS / (D(10000) + FEE_BPS) if kind.endswith('buy') else usd * FEE_BPS / (D(10000) - FEE_BPS)
        if sym == 'STOCK':
            stock_fee += f; stock_vol += usd
        else:
            crypto_fee += f; crypto_vol += usd
total = fee_in + fee_out + stock_fee + crypto_fee
payers = {u for u, v in dep.items() if any(r[0] >= START for r in v)} | \
         {u for u, v in trades.items() if any(r[0] >= START for r in v)}
print(f"  deposits (entry, exact):   ${fee_in:,.2f}   on ${vol_in:,.2f} deposited")
print(f"  withdrawals (exit, exact): ${fee_out:,.2f}")
print(f"  stock trades (est.):       ${stock_fee:,.2f}   on ${stock_vol:,.2f} traded")
print(f"  crypto/metal (est.):       ${crypto_fee:,.2f}   on ${crypto_vol:,.2f} traded")
print(f"  TOTAL:                     ${total:,.2f}   from {len(payers)} paying users → ${total / max(len(payers), 1):,.2f}/payer")
print("\nDone.")
