"""Confío IA economics: what the assistant costs vs. the boundary fees users pay.

Two modes, both read-only:

  --simulate   Monte Carlo of monthly AI cost per user from measured unit
               costs and usage assumptions (every assumption is a flag), and
               the extra boundary volume each user must move for the fee to
               pay for their AI: break-even volume = AI cost / fee rate.

  (default)    Real numbers for one month ("shadow billing"): per user, the AI
               cost actually metered (AssistantTurn, VoiceSession, CustomPet)
               against the Confío boundary fee actually collected
               (conversion.Conversion.fee_amount_exact, COMPLETED, by actor),
               grouped into cohorts: no IA use, light, heavy (top 10% by
               cost), realtime users. Answers "do heavy IA users move more
               money, and does their fee cover their AI?" with data.

Boundary fee only (vault entry/exit). Merchant-payment and payroll fees are
not included yet, so real-mode revenue is a floor.
"""
import math
import random
import statistics
from collections import defaultdict
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from django.core.management.base import BaseCommand


def pct(values, p):
    if not values:
        return 0.0
    ordered = sorted(values)
    k = min(len(ordered) - 1, max(0, int(math.ceil(p / 100 * len(ordered))) - 1))
    return ordered[k]


def money(value):
    return f'${value:,.4f}' if abs(value) < 1 else f'${value:,.2f}'


class Command(BaseCommand):
    help = 'Confío IA cost vs. boundary-fee revenue (simulation or real shadow billing).'

    def add_arguments(self, parser):
        parser.add_argument('--simulate', action='store_true')
        parser.add_argument('--month', help='YYYY-MM for real mode (default: last full month)')
        parser.add_argument('--runs', type=int, default=20000, help='simulated IA users')
        parser.add_argument('--seed', type=int, default=7)
        # Unit costs (USD). Measured 2026-10-04 except realtime (estimate until metered).
        parser.add_argument('--fee-rate', type=float, default=0.009)
        parser.add_argument('--turn-cost', type=float, default=0.0002, help='Luna text turn (measured)')
        parser.add_argument('--transcribe-per-min', type=float, default=0.0045)
        parser.add_argument('--analysis-cost', type=float, default=0.0122, help='Sol analysis, measured with 50 movements')
        parser.add_argument('--realtime-per-min', type=float, default=0.04, help='gpt-realtime-2.1-mini, estimate')
        parser.add_argument('--pet-cost', type=float, default=0.008, help='gpt-image-2 low (measured)')
        # Usage assumptions per IA user per month.
        parser.add_argument('--turns-median', type=float, default=10)
        parser.add_argument('--turns-sigma', type=float, default=1.0)
        parser.add_argument('--voice-note-share', type=float, default=0.3)
        parser.add_argument('--voice-note-seconds', type=float, default=20)
        parser.add_argument('--analyses-mean', type=float, default=1.5)
        parser.add_argument('--pets-mean', type=float, default=0.6)
        parser.add_argument('--verified-share', type=float, default=0.05)
        parser.add_argument('--trial-take', type=float, default=0.2, help='unverified IA users who try the voice trial')
        parser.add_argument('--trial-minutes', type=float, default=5)
        parser.add_argument('--verified-voice-take', type=float, default=0.5)
        parser.add_argument('--verified-minutes-median', type=float, default=8)
        parser.add_argument('--verified-minutes-cap', type=float, default=30)
        # Caps (fair use) — mirror assistant/conf.py.
        parser.add_argument('--daily-turns', type=int, default=40)
        parser.add_argument('--daily-analyses', type=int, default=3)
        parser.add_argument('--pets-per-week', type=int, default=3)

    def handle(self, *args, **opts):
        if opts['simulate']:
            self.simulate(opts)
        else:
            self.real(opts)

    # ------------------------------------------------------------------ #
    def user_cost(self, rng, o, verified):
        turns = min(rng.lognormvariate(math.log(o['turns_median']), o['turns_sigma']), o['daily_turns'] * 30)
        voice_minutes = turns * o['voice_note_share'] * o['voice_note_seconds'] / 60
        analyses = min(self.poisson(rng, o['analyses_mean']), o['daily_analyses'] * 30)
        pets = min(self.poisson(rng, o['pets_mean']), o['pets_per_week'] * 4)
        realtime = 0.0
        if verified:
            if rng.random() < o['verified_voice_take']:
                realtime = min(rng.lognormvariate(math.log(o['verified_minutes_median']), 0.8),
                               o['verified_minutes_cap'])
        elif rng.random() < o['trial_take']:
            realtime = rng.uniform(1, o['trial_minutes'])
        cost = (turns * o['turn_cost'] + voice_minutes * o['transcribe_per_min']
                + analyses * o['analysis_cost'] + pets * o['pet_cost'] + realtime * o['realtime_per_min'])
        return cost, realtime

    @staticmethod
    def poisson(rng, lam):
        limit, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= limit:
                return k
            k += 1

    def worst_case(self, o, verified):
        turns = o['daily_turns'] * 30
        return (turns * o['turn_cost'] + turns * o['voice_note_share'] * o['voice_note_seconds'] / 60 * o['transcribe_per_min']
                + o['daily_analyses'] * 30 * o['analysis_cost'] + o['pets_per_week'] * 4 * o['pet_cost']
                + (o['verified_minutes_cap'] if verified else o['trial_minutes']) * o['realtime_per_min'])

    def simulate(self, o):
        rng = random.Random(o['seed'])
        costs, verified_costs, realtime_costs = [], [], []
        for _ in range(o['runs']):
            verified = rng.random() < o['verified_share']
            cost, minutes = self.user_cost(rng, o, verified)
            costs.append(cost)
            if verified:
                verified_costs.append(cost)
            realtime_costs.append(minutes * o['realtime_per_min'])
        fee = o['fee_rate']
        w = self.stdout.write
        w('Confío IA — simulated monthly cost per IA user\n')
        w(f"  users simulated: {o['runs']:,}  verified share: {o['verified_share']:.0%}  realtime ${o['realtime_per_min']}/min\n")
        for label, p in (('mean', None), ('median', 50), ('p90', 90), ('p99', 99), ('max seen', 100)):
            value = statistics.fmean(costs) if p is None else pct(costs, p)
            w(f'  {label:>9}: {money(value):>9}/month  → break-even boundary volume {money(value / fee):>10}/month\n')
        w(f"  realtime share of cost: {sum(realtime_costs) / sum(costs):.0%}\n")
        if verified_costs:
            w(f'  verified users mean: {money(statistics.fmean(verified_costs))}  p90: {money(pct(verified_costs, 90))}\n')
        for verified in (False, True):
            worst = self.worst_case(o, verified)
            w(f"  worst case at every cap ({'verified' if verified else 'unverified'}): {money(worst)}/month"
              f" → needs {money(worst / fee)}/month through the boundary\n")
        mean = statistics.fmean(costs)
        w('\n  Total monthly AI bill (mean cost × IA users):\n')
        for mau in (600, 2000, 10000, 50000):
            for adoption in (0.15, 0.3, 0.5):
                w(f'    MAU {mau:>6,} × {adoption:.0%} use IA → {money(mau * adoption * mean):>10}/month'
                  f'  = fees on {money(mau * adoption * mean / fee):>12} of boundary volume\n')

    # ------------------------------------------------------------------ #
    def real(self, o):
        from django.contrib.auth import get_user_model
        from django.db.models import Sum

        from assistant.models import AssistantTurn, CustomPet, VoiceSession
        from conversion.models import Conversion
        from security.models import IdentityVerification

        now = datetime.now(dt_timezone.utc)
        if o.get('month'):
            year, month = (int(x) for x in o['month'].split('-'))
        else:
            year, month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
        start = datetime(year, month, 1, tzinfo=dt_timezone.utc)
        end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=dt_timezone.utc)

        ai = defaultdict(lambda: {'cost': Decimal('0'), 'turns': 0, 'analyses': 0, 'minutes': 0.0})
        for user_id, cost, tools in AssistantTurn.objects.filter(created_at__gte=start, created_at__lt=end) \
                .values_list('user_id', 'cost_usd', 'tools'):
            row = ai[user_id]
            row['cost'] += cost or 0
            row['turns'] += 1
            row['analyses'] += sum(1 for t in tools or [] if t.get('name') == 'analyze_finances')
        for session in VoiceSession.objects.filter(started_at__gte=start, started_at__lt=end):
            row = ai[session.user_id]
            row['cost'] += session.cost_usd or 0
            row['minutes'] += session.seconds / 60
        for user_id, cost in CustomPet.objects.filter(created_at__gte=start, created_at__lt=end) \
                .values_list('user_id', 'cost_usd'):
            ai[user_id]['cost'] += cost or 0

        fees = {
            r['actor_user_id']: r['fee'] or Decimal('0')
            for r in Conversion.objects.filter(status='COMPLETED', actor_user__isnull=False,
                                               created_at__gte=start, created_at__lt=end)
            .values('actor_user_id').annotate(fee=Sum('fee_amount_exact'))
        }
        verified = set(IdentityVerification.objects.filter(status='verified').values_list('user_id', flat=True))
        payers = set(fees)
        ia_users = set(ai)
        active = ia_users | payers

        costs = sorted((float(v['cost']) for v in ai.values()), reverse=True)
        heavy_cut = costs[max(len(costs) // 10 - 1, 0)] if costs else 0
        cohorts = {
            'no IA use': [u for u in active if u not in ia_users],
            'IA light': [u for u in ia_users if float(ai[u]['cost']) < heavy_cut],
            'IA heavy (top 10%)': [u for u in ia_users if float(ai[u]['cost']) >= heavy_cut and costs],
            'realtime users': [u for u in ia_users if ai[u]['minutes'] > 0],
        }
        w = self.stdout.write
        w(f'Confío IA shadow billing — {year}-{month:02d} (boundary fee only; payments/payroll fees excluded)\n')
        w(f'  active users (IA or fee-paying): {len(active):,}   IA users: {len(ia_users):,}\n')
        w(f'  total AI cost: {money(sum(float(v["cost"]) for v in ai.values()))}   '
          f'total boundary fees: {money(float(sum(fees.values())))}\n\n')
        w(f'  {"cohort":<20}{"users":>7}{"KYC":>7}{"AI cost/u":>12}{"fee/u":>11}{"net/u":>11}{"pay fee":>9}\n')
        for name, members in cohorts.items():
            if not members:
                continue
            n = len(members)
            cost = sum(float(ai[u]['cost']) for u in members if u in ai) / n
            fee = sum(float(fees.get(u, 0)) for u in members) / n
            kyc = sum(1 for u in members if u in verified) / n
            paying = sum(1 for u in members if u in payers) / n
            w(f'  {name:<20}{n:>7,}{kyc:>7.0%}{money(cost):>12}{money(fee):>11}{money(fee - cost):>11}{paying:>9.0%}\n')
        w('\n  Read: correlation only. People ask "¿cómo recargo?" right before they deposit, so IA use\n'
          '  follows money as much as it causes it; treat differences as hypotheses, not proof.\n')
