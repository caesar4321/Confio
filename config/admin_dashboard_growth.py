"""Activation, retention, demand, community and futures sections.

The question these answer is not "what happened" but "are signups becoming
funded, returning members": the funnel Today leads with, the signals of what
to build next, and the products with no ledger of their own.
"""
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.utils import timezone

from users.analytics import get_real_users_queryset

COHORT_WEEKS = 6
HEADLINE_WEEKS = 4
# Bolivia is most signups, and where the product bets are placed.
FOCUS_COUNTRY = 'BO'
# users.activity_tracking fixed DAU and began UserActivityDay on this day.
ACTIVITY_RELIABLE_SINCE = date(2026, 10, 29)
INVEST_KINDS = ('stock_buy', 'stock_sell', 'crypto_buy', 'crypto_sell', 'perps_open')


def _pct(part, whole):
    return part / whole * 100 if whole else None


def _member_sets(w):
    """(deposit events, verified ids, investor ids). Deposits cover every
    source, so a provider deposit that never converted still counts as funded."""
    from blockchain.models import SponsoredBatch
    from ramps.metrics import deposit_events
    from security.identity_status import verified_user_ids

    invested = SponsoredBatch.objects.filter(status='confirmed', kind__in=INVEST_KINDS).order_by()
    return deposit_events(), set(verified_user_ids()), invested


def activation(w):
    """Weekly signup cohorts through KYC, first deposit and first investment,
    split into Bolivia and everywhere else, plus the headline figures."""
    events, verified, invested = _member_sets(w)
    funded = {user for user, _at in events}
    investors = set(invested.values_list('user_id', flat=True))
    first_deposit = {}
    for user, at in events:
        if user not in first_deposit or at < first_deposit[user]:
            first_deposit[user] = at

    def scope_row(ids):
        signups = len(ids)
        kyc, money, invest = len(ids & verified), len(ids & funded), len(ids & investors)
        return {'signups': signups, 'kyc': kyc, 'funded': money, 'invested': invest,
                'kyc_pct': _pct(kyc, signups), 'funded_pct': _pct(money, signups)}

    members = list(get_real_users_queryset().filter(
        onboarded_at__gte=w.now - timedelta(days=7 * COHORT_WEEKS)).values_list('id', 'onboarded_at', 'country'))
    cohorts = []
    for week in range(COHORT_WEEKS):
        end = w.now - timedelta(days=7 * week)
        start = end - timedelta(days=7)
        ids = [(pk, country) for pk, at, country in members if start <= at < end]
        focus = {pk for pk, country in ids if country == FOCUS_COUNTRY}
        everyone = {pk for pk, _country in ids}
        cohorts.append({'start': start, 'end': end, 'all': scope_row(everyone),
                        'focus': scope_row(focus), 'rest': scope_row(everyone - focus)})

    recent = cohorts[:HEADLINE_WEEKS]
    totals = {key: sum(c['all'][key] for c in recent) for key in ('signups', 'kyc', 'funded', 'invested')}
    return {'activation': {
        'funded_30d': len({u for u, at in events if at >= w.rolling_30_start}),
        'funded_7d': len({u for u, at in events if at >= w.last_7_start}),
        'funded_ever': len(funded),
        'new_funded_7d': sum(1 for at in first_deposit.values() if at >= w.last_7_start),
        'new_funded_30d': sum(1 for at in first_deposit.values() if at >= w.rolling_30_start),
        'investors_30d': invested.filter(created_at__gte=w.rolling_30_start).values('user_id').distinct().count(),
        'investors_7d': invested.filter(created_at__gte=w.last_7_start).values('user_id').distinct().count(),
        'cohorts': cohorts,
        'totals': totals,
        'kyc_pct': _pct(totals['kyc'], totals['signups']),
        'funded_pct': _pct(totals['funded'], totals['signups']),
        'focus_country': FOCUS_COUNTRY,
        'headline_weeks': HEADLINE_WEEKS,
    }}


def retention(w):
    """D1 and D7 from UserActivityDay (La Paz days), only for signups the
    table can measure, and members older than 30 days who came back."""
    from users.activity_tracking import ACTIVITY_DAY_TZ
    from users.models_analytics import UserActivityDay

    days = set(UserActivityDay.objects.filter(day__gte=ACTIVITY_RELIABLE_SINCE).values_list('user_id', 'day'))
    today = timezone.localtime(w.now, ACTIVITY_DAY_TZ).date()
    joined = [(pk, timezone.localtime(at, ACTIVITY_DAY_TZ).date()) for pk, at in get_real_users_queryset().filter(
        onboarded_at__gte=w.now - timedelta(days=45)).values_list('id', 'onboarded_at')]

    def returned(offset):
        eligible = [(pk, day) for pk, day in joined
                    if day >= ACTIVITY_RELIABLE_SINCE and day + timedelta(days=offset) < today]
        back = sum(1 for pk, day in eligible if (pk, day + timedelta(days=offset)) in days)
        return {'back': back, 'eligible': len(eligible), 'pct': _pct(back, len(eligible))}

    recent_days = UserActivityDay.objects.filter(
        day__gte=today - timedelta(days=6), user__in=get_real_users_queryset())
    return {'retention': {
        'd1': returned(1),
        'd7': returned(7),
        'd7_first_measurable': ACTIVITY_RELIABLE_SINCE + timedelta(days=8),
        'active_7d': recent_days.values('user_id').distinct().count(),
        'returning_7d': recent_days.filter(user__onboarded_at__lt=w.rolling_30_start)
        .values('user_id').distinct().count(),
        'reliable_since': ACTIVITY_RELIABLE_SINCE,
    }}


def deposit_health(w, request):
    """Local-money deposit attempts in 30 days per provider: the point where
    an intending member can fall out without anyone seeing it."""
    from payment_accounts.models import CobreJourney, InfiniaJourney
    from ramps.metrics import _journey_mirrors
    from ramps.models import RampTransaction

    attempts = RampTransaction.objects.filter(direction='on_ramp', created_at__gte=w.rolling_30_start).exclude(
        pk__in=_journey_mirrors()).order_by()
    labels = dict(RampTransaction._meta.get_field('provider').choices or [])
    rows = []
    for row in attempts.values('provider').annotate(
            total=Count('id'), completed=Count('id', filter=Q(status='COMPLETED')),
            failed=Count('id', filter=Q(status='FAILED'))).order_by('-total'):
        reasons = Counter(
            (detail or 'no reason recorded')[:70] for detail in attempts.filter(
                provider=row['provider'], status='FAILED').values_list('status_detail', flat=True))
        ended = row['completed'] + row['failed']
        rows.append({'label': labels.get(row['provider'], row['provider'].title()), **row,
                     'pending': row['total'] - ended, 'success_pct': _pct(row['completed'], ended),
                     'reasons': reasons.most_common(2)})
    # Local-account rails have journeys, not ramp rows; "completed" is the
    # same end-to-end delivery the provider table counts. Same permission as
    # every other view of these journeys.
    journey_rails = () if not request.user.has_perm('payment_accounts.view_infiniajourney') else (
        ('Infinia', InfiniaJourney, Q(stage='completed', wallet_conversion__status='COMPLETED',
                                      wallet_conversion__is_deleted=False)),
        ('Cobre', CobreJourney, Q(stage='completed', bridge__status='delivered')),
    )
    for label, journeys, delivered in journey_rails:
        incoming = journeys.objects.filter(direction='to_wallet', created_at__gte=w.rolling_30_start).order_by()
        row = incoming.aggregate(total=Count('pk'), completed=Count('pk', filter=delivered),
                                 failed=Count('pk', filter=Q(stage__in=('failed', 'refunded'))))
        if not row['total']:
            continue
        reasons = Counter((code or 'no reason recorded')[:70] for code in incoming.filter(
            stage__in=('failed', 'refunded')).values_list('failure_code', flat=True))
        ended = row['completed'] + row['failed']
        rows.append({'label': label, **row, 'pending': row['total'] - ended,
                     'success_pct': _pct(row['completed'], ended), 'reasons': reasons.most_common(2)})
    rows.sort(key=lambda r: -r['total'])
    completed, failed = sum(r['completed'] for r in rows), sum(r['failed'] for r in rows)
    return {'deposit_health': {'rows': rows, 'completed': completed, 'failed': failed,
                               'success_pct': _pct(completed, completed + failed)}}


def _count_row(label, queryset, date_field, w, user_field=None):
    """24h / 7d / 30d / all-time counts of one activity, with distinct people
    over 30 days when the model has an actor."""
    cells = [queryset.filter(**{f'{date_field}__gte': since}).count()
             for _label, since in w.periods()]
    people = None
    if user_field:
        people = queryset.filter(**{f'{date_field}__gte': w.rolling_30_start}).values(user_field).distinct().count()
    return {'label': label, 'cells': cells, 'people': people}


def community(w):
    """The social product and the assistant: is anyone using them, and what
    the assistant costs per person."""
    from assistant.models import AssistantTurn, CustomPet, VoiceSession
    from inbox.models import CommunityActivityShare, CommunityComment, CommunityFollow, DirectMessage, Tip
    from teams.models import Team, TeamMembership

    tips = Tip.objects.filter(status='confirmed').order_by()
    # Same three cost sources the assistant's own economics report uses.
    since = w.rolling_30_start
    metered = (AssistantTurn.objects.filter(created_at__gte=since), VoiceSession.objects.filter(started_at__gte=since),
               CustomPet.objects.filter(created_at__gte=since))
    spend = sum((q.order_by().aggregate(cost=Sum('cost_usd'))['cost'] or Decimal('0') for q in metered), Decimal('0'))
    talkers = len({user for q in metered for user in q.order_by().values_list('user_id', flat=True).distinct()})
    return {'community_table': {
        'labels': [label for label, _since in w.periods()],
        'rows': [
            _count_row('Assistant turns', AssistantTurn.objects.order_by(), 'created_at', w, 'user_id'),
            _count_row('Activity shares', CommunityActivityShare.objects.order_by(), 'created_at', w, 'user_id'),
            _count_row('Comments', CommunityComment.objects.order_by(), 'created_at', w),
            _count_row('Follows', CommunityFollow.objects.order_by(), 'created_at', w),
            _count_row('Direct messages', DirectMessage.objects.order_by(), 'created_at', w, 'sender_id'),
            _count_row('Tips confirmed', tips, 'created_at', w, 'sender_id'),
            _count_row('Team joins', TeamMembership.objects.order_by(), 'joined_at', w, 'user_id'),
        ],
        'assistant_cost_30d': spend,
        'assistant_cost_per_person': spend / talkers if talkers else None,
        'tips_usd_30d': tips.filter(created_at__gte=w.rolling_30_start).aggregate(s=Sum('amount'))['s'] or Decimal('0'),
        'teams': Team.objects.count(),
    }}


def demand(w):
    """What members ask for before it exists: paid-offer doors, local rails,
    waitlists and assistant probes. Decides what gets built next."""
    from assistant.models import ProbeAnswer
    from users.models_analytics import FunnelEvent
    from users.models_product_waitlist import ProductWaitlistEntry
    from users.models_rail_waitlist import LocalRailWaitlistEntry
    from users.rail_interest_metrics import build_rail_interest_metrics, merge_waitlist_counts

    preview = {int(p) for p in str(getattr(settings, 'PAID_OFFER_PREVIEW_USER_IDS', '') or '').split(',')
               if p.strip().isdigit()}
    stages = ('door_shown', 'detail_opened', 'avisame_tapped')
    reached = defaultdict(set)
    for user, product, props in FunnelEvent.objects.filter(
            event_name='paid_offer_interest', user__isnull=False,
            created_at__gte=w.rolling_30_start).exclude(user_id__in=preview).values_list(
                'user_id', 'source_type', 'properties'):
        reached[(product, (props or {}).get('stage'))].add(user)
    labels = dict(ProductWaitlistEntry._meta.get_field('product').choices or [])
    waitlisted = {row['product']: row for row in ProductWaitlistEntry.objects.exclude(
        user_id__in=preview).order_by().values('product').annotate(
        n=Count('id'), funded_n=Count('id', filter=Q(funded=True)),
        yes_n=Count('id', filter=Q(would_pay='yes')))}
    offers = []
    for product in sorted({key[0] for key in reached} | set(waitlisted)):
        counts = [len(reached.get((product, stage), ())) for stage in stages]
        row = waitlisted.get(product, {})
        offers.append({'label': labels.get(product, product), 'stages': counts,
                       'waitlist': row.get('n', 0), 'would_pay': row.get('yes_n', 0),
                       'waitlist_funded': row.get('funded_n', 0)})

    rail_rows = FunnelEvent.objects.filter(
        event_name__in=['receive_rail_interest', 'local_rail_interest'],
        created_at__gte=w.now - timedelta(days=90),
    ).values('event_name', 'properties', 'country', 'created_at', 'user_id', 'session_id')
    rail_interest, totals = build_rail_interest_metrics(rail_rows)
    # The durable waitlist outlives the 90-day raw events, so its size is
    # all-time; a rail whose taps aged out still keeps the people to notify.
    waitlist_by_rail = {
        row['rail_id']: row for row in LocalRailWaitlistEntry.objects.values(
            'rail_id', 'direction', 'kind').annotate(count=Count('id'))
    }
    rail_interest = merge_waitlist_counts(rail_interest, waitlist_by_rail)
    totals['rails'] = len(rail_interest)
    totals['waitlist'] = LocalRailWaitlistEntry.objects.values('user_id').distinct().count()

    probes = list(ProbeAnswer.objects.order_by().values('probe_id', 'answer').annotate(
        n=Count('id'), funded_n=Count('id', filter=Q(funded=True))).order_by('-n')[:12])
    return {'demand_offers': offers, 'demand_stages': ('Saw it', 'Opened', 'Avísame'),
            'demand_probes': probes, 'rail_interest': rail_interest, 'rail_interest_totals': totals}


# Money sitting on the way to or from Hyperliquid, by state.
PERP_LIVE_STATES = ('bridging', 'funded', 'open', 'closed', 'liquidated', 'returning', 'return_failed', 'landed')


def futures(w):
    """Futures (Hyperliquid): what is live, what came back, what members made."""
    from blockchain.models import PerpMarginChange, PerpPosition

    positions = PerpPosition.objects.order_by()
    # margin_usd is only the opening amount: top-ups live in their own rows,
    # and returned_usd includes them.
    added = PerpMarginChange.objects.order_by().filter(direction='add', batch__status='confirmed').exclude(
        state__in=('refunded', 'failed', 'cancelled'))

    def top_ups(queryset):
        return added.filter(position__in=queryset).aggregate(s=Sum('amount_usd'))['s'] or Decimal('0')

    live = positions.filter(state__in=PERP_LIVE_STATES)
    settled = positions.filter(done_at__isnull=False)
    margin = (live.aggregate(s=Sum('margin_usd'))['s'] or Decimal('0')) + top_ups(live)
    done = settled.aggregate(margin=Sum('margin_usd'), back=Sum('returned_usd'))
    # Results land when a position closes, before (or without) its return.
    results = positions.aggregate(pnl=Sum('realized_pnl'), funding=Sum('funding'), fees=Sum('venue_fees'))
    return {'futures': {
        'live': live.count(),
        'open': positions.filter(state='open').count(),
        'margin_live': margin,
        'traders': positions.filter(opened_at__isnull=False).values('user_id').distinct().count(),
        'settled': settled.count(),
        'margin_settled': (done['margin'] or Decimal('0')) + top_ups(settled),
        'returned': done['back'] or Decimal('0'),
        'realized_pnl': results['pnl'] or Decimal('0'),
        'funding': results['funding'] or Decimal('0'),
        'venue_fees': results['fees'] or Decimal('0'),
        'liquidated': positions.exclude(liquidation='').count(),
        'return_failed': positions.filter(state='return_failed').count(),
        'by_state': list(live.values('state').annotate(n=Count('id')).order_by('-n')),
    }}
