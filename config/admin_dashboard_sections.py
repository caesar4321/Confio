"""Section builders for the Confío admin dashboard pages.

Each builder takes a `Window` (and the request when it reads filters) and
returns the context keys its template partial renders. Pages call only the
builders they show, so a page pays for its own numbers and nothing else.
The chain reads (vault/contract RPC) sit behind short admin-side caches,
because the main cost of the old single page was sequential BSC RPC calls,
not SQL.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from conversion.models import Conversion
from p2p_exchange.models import P2PDispute
from ramps.models import RampTransaction
from achievements.models import ReferralRewardEvent, ReferralWithdrawalLog, UserReferral
from achievements.referral_security import get_referral_reward_policy_stats, get_referral_reward_summary
from blockchain.constants import REFERRAL_ACHIEVEMENT_SLUGS
from inbox.models import ContentPlatformClick
from security.models import DeviceFingerprint, IdentityVerification
from users.analytics import ARG_TZ, get_argentina_day_bounds, get_real_users_queryset
from users.models import Business, User
from users.models_analytics import CountryMetrics, DailyMetrics, FunnelDailyRollup, FunnelEvent
from users.rail_interest_metrics import build_rail_interest_metrics, merge_waitlist_counts

# Chain reads are cached by their own helpers for 30s; the admin keeps a
# longer copy so moving between pages never waits on RPC twice.
CHAIN_CACHE_SECONDS = 300


@dataclass(frozen=True)
class Window:
    """Time bounds shared by every section. Calendar days are Argentina days,
    matching the nightly analytics snapshots and operational reporting."""
    now: datetime
    today_arg: date
    today_start: datetime
    last_24h: datetime
    last_7_start: datetime
    rolling_30_start: datetime
    # Chain reads made while building this request's page: every section
    # that shows a vault sees the same read, so alerts match the tiles.
    reads: dict = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def current(cls):
        now = timezone.now()
        today_arg = now.astimezone(ARG_TZ).date()
        today_start, _ = get_argentina_day_bounds(today_arg)
        return cls(
            now=now,
            today_arg=today_arg,
            today_start=today_start,
            last_24h=now - timedelta(hours=24),
            last_7_start=now - timedelta(days=7),
            rolling_30_start=now - timedelta(days=30),
        )


def get_fcm_reachability_metrics(now=None):
    """Return token-level and user-level FCM reachability without signup filters."""
    from notifications.models import FCMDeviceToken

    now = now or timezone.now()
    active_tokens = FCMDeviceToken.objects.filter(is_active=True)
    return {
        'active_users': active_tokens.values('user_id').distinct().count(),
        'recent_users': active_tokens.filter(
            last_used__gte=now - timedelta(days=30)
        ).values('user_id').distinct().count(),
        'active_tokens': active_tokens.values('token').distinct().count(),
    }


def _admin_cached(key, build, w, *, refresh=False):
    """Admin-only cache in front of a chain read. `refresh` (the page's
    ?refresh=1) rebuilds it; a failed build is never cached. Every rebuild
    reads the chain live (the helper's own 30s cache is skipped), so a value
    older than a failed read can never come back through either layer."""
    if key in w.reads:
        return w.reads[key]
    w.reads[key] = value = _admin_cached_read(key, build, refresh)
    return value


def _admin_cached_read(key, build, refresh):
    key = f'admin_dash:{key}'
    if not refresh:
        hit = cache.get(key)
        if hit is not None:
            return hit
    value = build(use_cache=False)
    source = value.get('source') if isinstance(value, dict) else getattr(value, 'source', None)
    if source == 'unavailable':
        # Never let an older healthy read outlive a failed refresh.
        cache.delete(key)
    else:
        cache.set(key, value, CHAIN_CACHE_SECONDS)
    return value


def _url(name, query=''):
    try:
        return reverse(f'confio_admin:{name}') + (f'?{query}' if query else '')
    except NoReverseMatch:
        return None


def users_core(w):
    """Users, activity, verification, push reach, 30-day trend and top countries."""
    now = w.now
    last_24h = w.last_24h
    last_7_start = w.last_7_start
    context = {}
    fcm_reachability = get_fcm_reachability_metrics(now)
    # User metrics
    # DAU/MAU now uses centralized last_activity_at field (single source of truth)
    # See users/activity_tracking.py for activity tracking implementation
    from users.analytics import get_real_users_queryset
    real_users = get_real_users_queryset()
    context['total_users'] = real_users.count()
    context['active_users_today'] = real_users.filter(last_activity_at__gte=last_24h).count()
    context['active_users_week'] = real_users.filter(last_activity_at__gte=last_7_start).count()
    context['active_users_month'] = real_users.filter(last_activity_at__gte=now - timedelta(days=30)).count()
    context['new_users_last_7_days'] = real_users.filter(created_at__gte=last_7_start).count()
    context['all_signups_last_7_days'] = User.objects.exclude(is_platform_test_account=True).filter(created_at__gte=last_7_start).count()
    context['phone_completion_last_7_days'] = (
        context['new_users_last_7_days'] / context['all_signups_last_7_days'] * 100
        if context['all_signups_last_7_days'] else 0
    )
    fcm_reachability = get_fcm_reachability_metrics(now)
    context['fcm_active_users'] = fcm_reachability['active_users']
    context['fcm_recent_users'] = fcm_reachability['recent_users']
    from security.identity_status import PERSONAL, verified_user_ids
    context['users_with_verification'] = IdentityVerification.all_documents.filter(PERSONAL).values('user').distinct().count()
    context['verified_users'] = verified_user_ids().count()
    context['verification_completion_rate'] = (
        context['verified_users'] / context['users_with_verification'] * 100
        if context['users_with_verification'] else 0
    )


    # Get latest snapshot for growth indicators
    latest_snapshot = DailyMetrics.objects.order_by('-date').first()
    if latest_snapshot:
        context['latest_snapshot_date'] = latest_snapshot.date
        context['snapshot_dau'] = latest_snapshot.dau
        context['snapshot_wau'] = latest_snapshot.wau
        context['snapshot_mau'] = latest_snapshot.mau
        context['snapshot_dau_mau_ratio'] = latest_snapshot.dau_mau_ratio

        # Growth rates
        context['mau_growth_7d'] = latest_snapshot.get_growth_rate(days_back=7)
        context['mau_growth_30d'] = latest_snapshot.get_growth_rate(days_back=30)

    # Last 30 days trend for charts
    thirty_days_ago = now.date() - timedelta(days=30)
    context['metrics_trend'] = list(
        DailyMetrics.objects.filter(date__gte=thirty_days_ago)
        .order_by('date')
        .values('date', 'dau', 'wau', 'mau', 'new_users_today')
    )

    # Country breakdown (top 5 by MAU from latest snapshot)
    if latest_snapshot:
        context['top_countries_metrics'] = list(
            CountryMetrics.objects.filter(date=latest_snapshot.date)
            .order_by('-mau')[:10]
            .values('country_code', 'dau', 'wau', 'mau', 'total_users')
        )
    return context


def v2_security(w):
    """Legacy V2 keyless migration + Drive backup coverage."""
    context = {}
    context['total_users'] = get_real_users_queryset().count()
    real_users = get_real_users_queryset()
    # V2 Migration & Backup Security Metrics
    # Keep this user-level over the phone-completed user base. Migration is
    # tracked per account, so collapse to distinct users for dashboard KPIs.
    drive_users = real_users.filter(backup_provider='google_drive').count()
    migrated_users = real_users.filter(accounts__is_keyless_migrated=True).distinct().count()
    # For safe V2 users, count users with both backup verified AND at least one migrated account
    safe_v2_users = real_users.filter(
        backup_verified_at__isnull=False,
        accounts__is_keyless_migrated=True
    ).distinct().count()

    context['security_stats'] = {
        'drive_count': drive_users,
        'drive_pct': (drive_users / context['total_users'] * 100) if context['total_users'] else 0,
        'migrated_count': migrated_users,
        'migrated_pct': (migrated_users / context['total_users'] * 100) if context['total_users'] else 0,
        'safe_v2_count': safe_v2_users,
        'safe_v2_pct': (safe_v2_users / context['total_users'] * 100) if context['total_users'] else 0,
    }
    return context


def os_stats(w):
    """Platform split from the last login."""
    context = {}
    context['total_users'] = get_real_users_queryset().count()
    # OS Stats (Explicit from Login)
    ios_users = User.objects.exclude(is_platform_test_account=True).filter(platform_os='ios').count()
    android_users = User.objects.exclude(is_platform_test_account=True).filter(platform_os='android').count()

    context['os_stats'] = {
        'ios_count': ios_users,
        'ios_pct': (ios_users / context['total_users'] * 100) if context['total_users'] else 0,
        'android_count': android_users,
        'android_pct': (android_users / context['total_users'] * 100) if context['total_users'] else 0,
    }
    return context


def funnels(w):
    """Send-and-invite + referral-link funnels, cohorts and rail-interest probes."""
    today_arg = w.today_arg
    context = {}
    # Invite/referral funnel metrics
    today = today_arg
    funnel_last_90_date = today - timedelta(days=89)
    funnel_last_7_date = today - timedelta(days=6)
    funnel_last_90_start, _ = get_argentina_day_bounds(funnel_last_90_date)
    creator_referral_code = 'JULIANMOONLUNA'
    creator_cohort = 'creator_julianmoonluna'
    paid_ads_cohort = 'paid_ads'
    other_referral_cohorts = ['user_driven', 'unknown']

    def _pct(numerator, denominator):
        return (numerator / denominator * 100) if denominator else 0

    def _date_rows(start_date, end_date):
        days = (end_date - start_date).days + 1
        return [start_date + timedelta(days=offset) for offset in range(days)]

    def _cohort_filter(queryset, cohort):
        if cohort is None:
            return queryset
        if isinstance(cohort, (list, tuple, set)):
            return queryset.filter(cohort__in=list(cohort))
        return queryset.filter(cohort=cohort)

    def _raw_cohort_filter(queryset, cohort):
        if cohort is None:
            return queryset
        paid_event_filter = (
            Q(properties__utm_medium__iexact='paid')
            | Q(properties__utm_medium__iexact='cpc')
            | Q(properties__utm_medium__iexact='ppc')
            | Q(properties__utm_medium__iexact='paid_social')
            | Q(properties__utm_source__iexact='tiktok_ads')
            | Q(properties__utm_source__iexact='instagram_ads')
            | Q(properties__utm_source__iexact='facebook_ads')
            | Q(properties__utm_source__iexact='meta_ads')
            | Q(channel__in=['tiktok_ads', 'instagram_ads', 'facebook_ads', 'meta_ads'])
            | Q(
                event_name='first_deposit',
                user__referrals_as_referred__attribution_data__utm_medium__iexact='paid',
            )
            | Q(
                event_name='first_deposit',
                user__referrals_as_referred__attribution_data__utm_source__in=[
                    'tiktok_ads',
                    'instagram_ads',
                    'facebook_ads',
                    'meta_ads',
                ],
            )
        )
        paid_event_pks = queryset.filter(paid_event_filter).values('pk')
        if cohort == creator_cohort:
            creator_event_filter = (
                Q(properties__referral_code__iexact=creator_referral_code)
                | Q(
                    event_name='first_deposit',
                    user__referrals_as_referred__referrer_identifier__iexact=creator_referral_code,
                )
            )
            return queryset.filter(creator_event_filter).exclude(pk__in=paid_event_pks)
        if cohort == paid_ads_cohort:
            return queryset.filter(paid_event_filter)
        if cohort == other_referral_cohorts:
            return queryset.exclude(
                Q(properties__referral_code__iexact=creator_referral_code)
                | Q(
                    event_name='first_deposit',
                    user__referrals_as_referred__referrer_identifier__iexact=creator_referral_code,
                )
            ).exclude(pk__in=paid_event_pks)
        if cohort == 'send_invite':
            return queryset
        return queryset

    def _rollup_event_counts(source_type, event_names, start_date, cohort=None):
        rollup_base = FunnelDailyRollup.objects.filter(
            source_type=source_type,
            event_name__in=event_names,
            date__gte=start_date,
            date__lt=today,
        )
        rolled_dates = set(rollup_base.values_list('date', flat=True).distinct())
        rollups = rollup_base
        rollups = _cohort_filter(rollups, cohort)
        counts = {
            row['event_name']: row['count'] or 0
            for row in rollups.values('event_name').annotate(count=Sum('count'))
        }
        # Celery rolls up yesterday asynchronously. Include raw rows for
        # dates that do not have rollups yet, plus today's raw rows.
        raw_dates = [
            day for day in _date_rows(start_date, today)
            if day == today or day not in rolled_dates
        ]
        raw_unrolled = FunnelEvent.objects.annotate(
            day=TruncDate('created_at', tzinfo=ARG_TZ)
        ).filter(
            source_type=source_type,
            event_name__in=event_names,
            day__in=raw_dates,
            created_at__gte=funnel_last_90_start,
        )
        raw_unrolled = _raw_cohort_filter(raw_unrolled, cohort)
        for row in raw_unrolled.values('event_name').annotate(count=Count('id')):
            counts[row['event_name']] = counts.get(row['event_name'], 0) + (row['count'] or 0)
        return counts

    def _rollup_trend_rows(source_type, event_names, start_date, cohort=None):
        rows = {
            day: {'date': day, **{event_name: 0 for event_name in event_names}}
            for day in _date_rows(start_date, today)
        }
        rollup_base = FunnelDailyRollup.objects.filter(
            source_type=source_type,
            event_name__in=event_names,
            date__gte=start_date,
            date__lt=today,
        )
        rolled_dates = set(rollup_base.values_list('date', flat=True).distinct())
        rollups = rollup_base
        rollups = _cohort_filter(rollups, cohort)
        for row in rollups.values('date', 'event_name').annotate(count=Sum('count')):
            rows[row['date']][row['event_name']] = row['count'] or 0
        raw_dates = [
            day for day in _date_rows(start_date, today)
            if day == today or day not in rolled_dates
        ]
        raw_unrolled = FunnelEvent.objects.annotate(
            day=TruncDate('created_at', tzinfo=ARG_TZ)
        ).filter(
            source_type=source_type,
            event_name__in=event_names,
            day__in=raw_dates,
            created_at__gte=funnel_last_90_start,
        )
        raw_unrolled = _raw_cohort_filter(raw_unrolled, cohort)
        for row in (
            raw_unrolled
            .values('day', 'event_name')
            .annotate(count=Count('id'))
        ):
            day = row['day']
            if day in rows:
                rows[day][row['event_name']] = rows[day].get(row['event_name'], 0) + (row['count'] or 0)
        return [rows[day] for day in sorted(rows.keys(), reverse=True)]

    send_invite_event_names = [
        'invite_submitted',
        'whatsapp_share_tapped',
        'invite_link_clicked',
        'signup_completed',
        'referral_attached',
        'invite_claimed',
        'first_deposit',
    ]
    send_invite_90d = _rollup_event_counts(
        source_type='send_invite',
        event_names=send_invite_event_names,
        start_date=funnel_last_90_date,
        cohort='send_invite',
    )
    send_invite_7d = _rollup_event_counts(
        source_type='send_invite',
        event_names=send_invite_event_names,
        start_date=funnel_last_7_date,
        cohort='send_invite',
    )

    invite_submitted_total = send_invite_90d.get('invite_submitted', 0)
    share_tapped_total = send_invite_90d.get('whatsapp_share_tapped', 0)
    link_clicked_total = send_invite_90d.get('invite_link_clicked', 0)
    signup_completed_total = send_invite_90d.get('signup_completed', 0)
    referral_attached_total = send_invite_90d.get('referral_attached', 0)
    invite_claimed_total = send_invite_90d.get('invite_claimed', 0)
    first_deposit_total = send_invite_90d.get('first_deposit', 0)

    context['send_invite_funnel_stats'] = {
        'invite_submitted_total': invite_submitted_total,
        'share_tapped_total': share_tapped_total,
        'link_clicked_total': link_clicked_total,
        'signup_completed_total': signup_completed_total,
        'referral_attached_total': referral_attached_total,
        'invite_claimed_total': invite_claimed_total,
        'first_deposit_total': first_deposit_total,
        'raw_events_90d': FunnelEvent.objects.filter(
            source_type='send_invite',
            created_at__gte=funnel_last_90_start,
        ).count(),
        'rollup_rows_90d': FunnelDailyRollup.objects.filter(
            source_type='send_invite',
            date__gte=funnel_last_90_date,
        ).count(),
        'invite_to_share_pct': _pct(share_tapped_total, invite_submitted_total),
        'share_to_click_pct': _pct(link_clicked_total, share_tapped_total),
        'click_to_signup_pct': _pct(signup_completed_total, link_clicked_total),
        'signup_to_claim_pct': _pct(invite_claimed_total, signup_completed_total),
        'claim_to_deposit_pct': _pct(first_deposit_total, invite_claimed_total),
        'invite_submitted_7d': send_invite_7d.get('invite_submitted', 0),
        'share_tapped_7d': send_invite_7d.get('whatsapp_share_tapped', 0),
        'link_clicked_7d': send_invite_7d.get('invite_link_clicked', 0),
        'signup_completed_7d': send_invite_7d.get('signup_completed', 0),
        'referral_attached_7d': send_invite_7d.get('referral_attached', 0),
        'invite_claimed_7d': send_invite_7d.get('invite_claimed', 0),
        'first_deposit_7d': send_invite_7d.get('first_deposit', 0),
    }
    context['send_invite_recent'] = list(
        FunnelEvent.objects.filter(
            source_type='send_invite',
            event_name__in=send_invite_event_names,
            created_at__gte=funnel_last_90_start,
        )
        .order_by('-created_at')
        .values('created_at', 'event_name', 'country', 'platform', 'channel', 'session_id', 'user__username')[:10]
    )
    send_invite_trend = _rollup_trend_rows(
        source_type='send_invite',
        event_names=send_invite_event_names,
        start_date=funnel_last_90_date,
        cohort='send_invite',
    )
    for row in send_invite_trend:
        row['invite_to_share_pct'] = _pct(row['whatsapp_share_tapped'], row['invite_submitted'])
        row['click_to_signup_pct'] = _pct(row['signup_completed'], row['invite_link_clicked'])
        row['signup_to_claim_pct'] = _pct(row['invite_claimed'], row['signup_completed'])
        row['claim_to_deposit_pct'] = _pct(row['first_deposit'], row['invite_claimed'])
    context['send_invite_daily_trend'] = send_invite_trend

    referral_90d = FunnelEvent.objects.filter(
        source_type='referral_link',
        created_at__gte=funnel_last_90_start,
    )
    # --- Rail interest (demand probes) ---------------------------------
    # Rails we do NOT support yet stay visible in the receive/send sheets;
    # a tap is curiosity and the follow-up confirmation is real demand.
    # These never showed up anywhere in this dashboard because every panel
    # above filters on source_type ('send_invite' / 'referral_link') and
    # the probes were emitted with none — so the only way to read them was
    # the raw FunnelEvent changelist. They decide which corridor we build
    # next and which virtual accounts are worth paying to open, so they get
    # their own panel. Aggregated in Python: the rail and stage live inside
    # the JSON `properties`, not in indexed columns.
    rail_interest_rows = FunnelEvent.objects.filter(
        event_name__in=['receive_rail_interest', 'local_rail_interest'],
        created_at__gte=funnel_last_90_start,
    ).values(
        'event_name',
        'properties',
        'country',
        'created_at',
        'user_id',
        'session_id',
    )

    rail_interest, rail_interest_totals = build_rail_interest_metrics(rail_interest_rows)
    # The durable waitlist (LocalRailWaitlistEntry) outlives the 90-day raw
    # events, so its size is all-time; a rail whose taps aged out still
    # keeps the people to notify.
    from users.models_rail_waitlist import LocalRailWaitlistEntry
    waitlist_by_rail = {
        row['rail_id']: row
        for row in LocalRailWaitlistEntry.objects.values('rail_id', 'direction', 'kind')
        .annotate(count=Count('id'))
    }
    rail_interest = merge_waitlist_counts(rail_interest, waitlist_by_rail)
    rail_interest_totals['rails'] = len(rail_interest)
    rail_interest_totals['waitlist'] = LocalRailWaitlistEntry.objects.values('user_id').distinct().count()
    context['rail_interest'] = rail_interest
    context['rail_interest_totals'] = rail_interest_totals

    referral_event_names = [
        'referral_whatsapp_share_tapped',
        'referral_link_clicked',
        'signup_completed',
        'referral_attached',
        'first_deposit',
    ]
    referral_90d_counts = _rollup_event_counts(
        source_type='referral_link',
        event_names=referral_event_names,
        start_date=funnel_last_90_date,
    )
    referral_7d_counts = _rollup_event_counts(
        source_type='referral_link',
        event_names=referral_event_names,
        start_date=funnel_last_7_date,
    )
    referral_share_tapped_total = referral_90d_counts.get('referral_whatsapp_share_tapped', 0)
    referral_link_clicked_total = referral_90d_counts.get('referral_link_clicked', 0)
    referral_signup_completed_total = referral_90d_counts.get('signup_completed', 0)
    referral_attached_total = referral_90d_counts.get('referral_attached', 0)
    referral_first_deposit_total = referral_90d_counts.get('first_deposit', 0)
    context['referral_funnel_stats'] = {
        'share_tapped_total': referral_share_tapped_total,
        'share_tapped_7d': referral_7d_counts.get('referral_whatsapp_share_tapped', 0),
        'link_clicked_total': referral_link_clicked_total,
        'link_clicked_7d': referral_7d_counts.get('referral_link_clicked', 0),
        'signup_completed_total': referral_signup_completed_total,
        'signup_completed_7d': referral_7d_counts.get('signup_completed', 0),
        'referral_attached_total': referral_attached_total,
        'referral_attached_7d': referral_7d_counts.get('referral_attached', 0),
        'first_deposit_total': referral_first_deposit_total,
        'first_deposit_7d': referral_7d_counts.get('first_deposit', 0),
        'share_to_click_pct': _pct(referral_link_clicked_total, referral_share_tapped_total),
        'click_to_signup_pct': _pct(referral_signup_completed_total, referral_link_clicked_total),
        'signup_to_attach_pct': _pct(referral_attached_total, referral_signup_completed_total),
        'attach_to_deposit_pct': _pct(referral_first_deposit_total, referral_attached_total),
        'raw_events_90d': referral_90d.count(),
        'rollup_rows_90d': FunnelDailyRollup.objects.filter(
            source_type='referral_link',
            date__gte=funnel_last_90_date,
        ).count(),
    }
    context['referral_recent'] = list(
        referral_90d.order_by('-created_at')
        .values('created_at', 'event_name', 'country', 'platform', 'channel', 'session_id')[:10]
    )
    referral_acquisition_90d = referral_90d.filter(
        event_name__in=['referral_whatsapp_share_tapped', 'referral_link_clicked', 'signup_completed', 'referral_attached'],
    )
    referral_conversion_90d = referral_90d.filter(
        event_name='first_deposit',
    )
    creator_event_filter = Q(properties__referral_code__iexact=creator_referral_code)
    creator_deposit_filter = Q(user__referrals_as_referred__referrer_identifier__iexact=creator_referral_code)
    paid_event_filter = (
        Q(properties__utm_medium__iexact='paid')
        | Q(properties__utm_medium__iexact='cpc')
        | Q(properties__utm_medium__iexact='ppc')
        | Q(properties__utm_medium__iexact='paid_social')
        | Q(properties__utm_source__iexact='tiktok_ads')
        | Q(properties__utm_source__iexact='instagram_ads')
        | Q(properties__utm_source__iexact='facebook_ads')
        | Q(properties__utm_source__iexact='meta_ads')
        | Q(channel__in=['tiktok_ads', 'instagram_ads', 'facebook_ads', 'meta_ads'])
    )
    paid_deposit_filter = (
        Q(user__referrals_as_referred__attribution_data__utm_medium__iexact='paid')
        | Q(user__referrals_as_referred__attribution_data__utm_medium__iexact='cpc')
        | Q(user__referrals_as_referred__attribution_data__utm_medium__iexact='ppc')
        | Q(user__referrals_as_referred__attribution_data__utm_medium__iexact='paid_social')
        | Q(user__referrals_as_referred__attribution_data__utm_source__in=[
            'tiktok_ads',
            'instagram_ads',
            'facebook_ads',
            'meta_ads',
        ])
    )

    def _referral_cohort_row(label, cohort, acquisition_filter, deposit_filter):
        cohort_counts = _rollup_event_counts(
            source_type='referral_link',
            event_names=referral_event_names,
            start_date=funnel_last_90_date,
            cohort=cohort,
        )
        cohort_shares = cohort_counts.get('referral_whatsapp_share_tapped', 0)
        cohort_clicks = cohort_counts.get('referral_link_clicked', 0)
        cohort_signups = cohort_counts.get('signup_completed', 0)
        cohort_attached = cohort_counts.get('referral_attached', 0)
        cohort_deposits = cohort_counts.get('first_deposit', 0)
        if not cohort_deposits:
            cohort_deposits = referral_conversion_90d.filter(deposit_filter).distinct().count()
        return {
            'label': label,
            'share_taps': cohort_shares,
            'link_clicks': cohort_clicks,
            'signup_completed': cohort_signups,
            'referral_attached': cohort_attached,
            'first_deposits': cohort_deposits,
            'share_to_click_pct': _pct(cohort_clicks, cohort_shares),
            'click_to_signup_pct': _pct(cohort_signups, cohort_clicks),
            'signup_to_attach_pct': _pct(cohort_attached, cohort_signups),
            'attach_to_deposit_pct': _pct(cohort_deposits, cohort_attached),
        }

    context['referral_cohort_breakdown'] = [
        _referral_cohort_row(
            'Paid ads',
            paid_ads_cohort,
            paid_event_filter,
            paid_deposit_filter,
        ),
        _referral_cohort_row(
            f'Creator @{creator_referral_code} organic',
            creator_cohort,
            creator_event_filter & ~paid_event_filter,
            creator_deposit_filter & ~paid_deposit_filter,
        ),
        _referral_cohort_row(
            'User-driven / other referrals',
            other_referral_cohorts,
            ~creator_event_filter & ~paid_event_filter,
            ~creator_deposit_filter & ~paid_deposit_filter,
        ),
    ]
    paid_ads_trend = _rollup_trend_rows(
        source_type='referral_link',
        event_names=referral_event_names,
        start_date=funnel_last_90_date,
        cohort=paid_ads_cohort,
    )
    creator_trend = _rollup_trend_rows(
        source_type='referral_link',
        event_names=referral_event_names,
        start_date=funnel_last_90_date,
        cohort=creator_cohort,
    )
    other_trend = _rollup_trend_rows(
        source_type='referral_link',
        event_names=referral_event_names,
        start_date=funnel_last_90_date,
        cohort=other_referral_cohorts,
    )
    context['referral_daily_trend'] = []
    for paid_row, creator_row, other_row in zip(paid_ads_trend, creator_trend, other_trend):
        paid_clicks = paid_row['referral_link_clicked']
        paid_signups = paid_row['signup_completed']
        paid_attached = paid_row['referral_attached']
        paid_deposits = paid_row['first_deposit']
        user_shares = other_row['referral_whatsapp_share_tapped']
        user_clicks = other_row['referral_link_clicked']
        user_signups = other_row['signup_completed']
        user_attached = other_row['referral_attached']
        user_deposits = other_row['first_deposit']
        context['referral_daily_trend'].append({
            'date': creator_row['date'],
            'paid_clicks': paid_clicks,
            'paid_signups': paid_signups,
            'paid_attached': paid_attached,
            'paid_deposits': paid_deposits,
            'paid_click_to_signup_pct': _pct(paid_signups, paid_clicks),
            'paid_attach_to_deposit_pct': _pct(paid_deposits, paid_attached),
            'creator_clicks': creator_row['referral_link_clicked'],
            'creator_signups': creator_row['signup_completed'],
            'creator_attached': creator_row['referral_attached'],
            'creator_deposits': creator_row['first_deposit'],
            'user_shares': user_shares,
            'user_clicks': user_clicks,
            'user_signups': user_signups,
            'user_attached': user_attached,
            'user_deposits': user_deposits,
            'user_share_to_click_pct': _pct(user_clicks, user_shares),
            'user_click_to_signup_pct': _pct(user_signups, user_clicks),
            'user_signup_to_attach_pct': _pct(user_attached, user_signups),
            'user_attach_to_deposit_pct': _pct(user_deposits, user_attached),
        })
    context['referral_acquisition_breakdown'] = list(
        referral_acquisition_90d
        .values('event_name', 'channel')
        .annotate(count=Count('id'))
        .order_by('event_name', '-count', 'channel')
    )
    context['referral_conversion_breakdown'] = list(
        referral_conversion_90d
        .values('channel')
        .annotate(count=Count('id'))
        .order_by('-count', 'channel')
    )
    context['invite_funnel_raw_url'] = reverse('confio_admin:users_funnelevent_changelist')
    context['invite_funnel_rollup_url'] = reverse('confio_admin:users_funneldailyrollup_changelist')
    return context


def disputes(w):
    """Legacy P2P disputes (P2P is deprecated; only open ones still matter)."""
    context = {}
    # Dispute metrics
    context['open_disputes'] = P2PDispute.objects.filter(
        status__in=['OPEN', 'UNDER_REVIEW']
    ).count()
    context['escalated_disputes'] = P2PDispute.objects.filter(status='ESCALATED').count()
    return context


def reward_security(w):
    """$CONFIO referral reward security."""
    now = w.now
    context = {}
    # Referral reward security statistics
    referral_logs = ReferralWithdrawalLog.objects.all()
    total_withdrawn = referral_logs.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    daily_withdrawn = referral_logs.filter(created_at__gte=now - timedelta(days=1)).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0')
    weekly_withdrawn = referral_logs.filter(created_at__gte=now - timedelta(days=7)).aggregate(
        total=Sum('amount')
    )['total'] or Decimal('0')
    pending_review = referral_logs.filter(requires_review=True).count()
    high_value = referral_logs.filter(amount__gte=Decimal('500')).count()
    unique_referral_users = referral_logs.values('user').distinct().count()

    referral_reward_summary = get_referral_reward_summary()
    referral_policy_stats = get_referral_reward_policy_stats()

    multi_user_devices = DeviceFingerprint.objects.annotate(
        user_count=Count(
            'users',
            filter=Q(users__achievements__achievement_type__slug__in=REFERRAL_ACHIEVEMENT_SLUGS),
            distinct=True,
        )
    ).filter(user_count__gt=1).count()

    context['fraud_stats'] = {
        'earned_total': referral_reward_summary['earned'],
        'available_total': referral_reward_summary['available'],
        'total_withdrawn': total_withdrawn,
        'daily_withdrawn': daily_withdrawn,
        'weekly_withdrawn': weekly_withdrawn,
        'pending_review': pending_review,
        'high_value': high_value,
        'unique_users': unique_referral_users,
        'multi_user_devices': multi_user_devices,
        'rewarded_users': referral_policy_stats['rewarded_users'],
        'verified_reward_users': referral_policy_stats['verified_reward_users'],
        'unverified_reward_users': referral_policy_stats['unverified_reward_users'],
        'verified_available_total': referral_policy_stats['verified_available_total'],
        'kyc_hold_total': referral_policy_stats['kyc_hold_total'],
        'duplicate_identity_review_users': referral_policy_stats['duplicate_identity_review_users'],
    }
    return context


def referral_program(w):
    """UserReferral totals."""
    last_7_start = w.last_7_start
    context = {}
    referral_records = UserReferral.objects.filter(deleted_at__isnull=True)
    total_referrals = referral_records.count()
    converted_referrals = referral_records.filter(status='converted').count()
    new_referrals_week = referral_records.filter(created_at__gte=last_7_start).count()
    converted_week = referral_records.filter(
        status='converted',
        reward_claimed_at__gte=last_7_start
    ).count()
    engaged_referrals = referral_records.filter(total_transaction_volume__gt=0).count()
    total_awarded = referral_records.aggregate(
        total=Sum('referrer_confio_awarded')
    )['total'] or Decimal('0')
    eligible_events = ReferralRewardEvent.objects.filter(
        reward_status='eligible'
    ).count()
    conversion_rate = (converted_referrals / total_referrals * 100) if total_referrals else 0
    avg_rewards_per_converted = (eligible_events / converted_referrals) if converted_referrals else 0

    context['referral_stats'] = {
        'total': total_referrals,
        'converted': converted_referrals,
        'conversion_rate': conversion_rate,
        'new_week': new_referrals_week,
        'converted_week': converted_week,
        'engaged': engaged_referrals,
        'avg_rewards_per_converted': avg_rewards_per_converted,
        'total_awarded': total_awarded,
        'eligible_events': eligible_events,
    }
    return context


def legacy_conversions(w):
    """Conversion counts, all rails, plus the savings subset."""
    today_start = w.today_start
    last_7_start = w.last_7_start
    context = {}
    # Conversion metrics. `Conversion` carries multiple rails since the
    # savings sagas merged into it (2026-08-01), so an unfiltered count
    # blurs an Algorand USDC swap with a BSC savings saga. Report the
    # total and the savings subset separately.
    conversions_today_qs = Conversion.objects.filter(created_at__gte=today_start)
    conversions_7d_qs = Conversion.objects.filter(created_at__gte=last_7_start)
    context['conversions_today'] = conversions_today_qs.count()
    context['conversions_last_7_days'] = conversions_7d_qs.count()
    context['savings_conversions_today'] = conversions_today_qs.filter(
        conversion_type__in=Conversion.SAVINGS_TYPES
    ).count()
    context['savings_conversions_last_7_days'] = conversions_7d_qs.filter(
        conversion_type__in=Conversion.SAVINGS_TYPES
    ).count()
    return context


def messaging(w):
    """Notifications and push reach."""
    now = w.now
    today_start = w.today_start
    context = {}
    fcm_reachability = get_fcm_reachability_metrics(now)
    # Notification metrics
    from notifications.models import Notification
    context['notifications_sent_today'] = Notification.objects.filter(
        created_at__gte=today_start
    ).count()
    context['push_notifications_today'] = Notification.objects.filter(
        created_at__gte=today_start,
        push_sent=True
    ).count()
    context['active_fcm_tokens'] = fcm_reachability['active_tokens']
    context['reachable_push_users'] = fcm_reachability['active_users']
    return context


def content(w):
    """Content platform clicks."""
    now = w.now
    last_24h = w.last_24h
    last_7_start = w.last_7_start
    context = {}
    # Content engagement metrics
    content_clicks_last_24h = ContentPlatformClick.objects.filter(created_at__gte=last_24h)
    content_clicks_last_7d = ContentPlatformClick.objects.filter(created_at__gte=last_7_start)
    content_clicks_last_30d = ContentPlatformClick.objects.filter(created_at__gte=now - timedelta(days=30))

    context['content_click_stats'] = {
        'total': ContentPlatformClick.objects.count(),
        'last_24h': content_clicks_last_24h.count(),
        'last_7d': content_clicks_last_7d.count(),
        'unique_users_7d': content_clicks_last_7d.values('user_id').distinct().count(),
        'tiktok_7d': content_clicks_last_7d.filter(platform='TIKTOK').count(),
        'instagram_7d': content_clicks_last_7d.filter(platform='INSTAGRAM').count(),
        'youtube_7d': content_clicks_last_7d.filter(platform='YOUTUBE').count(),
        'channel_7d': content_clicks_last_7d.filter(surface='CHANNEL').count(),
        'discover_7d': content_clicks_last_7d.filter(surface='DISCOVER').count(),
    }

    context['platform_breakdown_7d'] = list(
        content_clicks_last_7d.values('platform').annotate(
            click_count=Count('id'),
            unique_users=Count('user_id', distinct=True),
        ).order_by('-click_count')
    )

    context['top_clicked_content'] = list(
        content_clicks_last_30d.values(
            'content_item_id',
            'content_item__title',
            'content_item__channel__title',
            'surface',
        ).annotate(
            click_count=Count('id'),
            unique_users=Count('user_id', distinct=True),
        ).order_by('-click_count', '-unique_users')[:8]
    )
    return context


def legacy_cusd(w):
    """a-cUSD on Algorand (legacy rail)."""
    rolling_30_start = w.rolling_30_start
    context = {}
    # Rolling 30-day conversion volumes. Use completed_at when present so the
    # operational dashboard reflects when value actually settled.
    rolling_completed_conversions = Conversion.objects.filter(
        status='COMPLETED'
    ).filter(
        Q(completed_at__gte=rolling_30_start)
        | Q(completed_at__isnull=True, created_at__gte=rolling_30_start)
    )
    conversions_volume = rolling_completed_conversions.aggregate(
        usdc_to_cusd=Sum('from_amount', filter=Q(conversion_type='usdc_to_cusd')),
        cusd_to_usdc=Sum('from_amount', filter=Q(conversion_type='cusd_to_usdc'))
    )
    context['usdc_to_cusd_volume'] = conversions_volume['usdc_to_cusd'] or Decimal('0')
    context['cusd_to_usdc_volume'] = conversions_volume['cusd_to_usdc'] or Decimal('0')

    # Calculate net legacy-rail inflow (positive means more USDC → a-cUSD)
    context['net_usdc_inflow'] = context['usdc_to_cusd_volume'] - context['cusd_to_usdc_volume']

    # Live legacy a-cUSD supply and collateral come from the Algorand
    # contract, with a database fallback if algod is unavailable.
    from blockchain.cusd_metrics import get_cusd_platform_metrics
    cusd_metrics = get_cusd_platform_metrics()
    context['circulating_cusd'] = cusd_metrics.circulating_cusd
    context['cusd_tvl'] = cusd_metrics.tvl_cusd
    context['cusd_metrics_source'] = cusd_metrics.source
    context['cusd_metrics_as_of'] = cusd_metrics.as_of
    return context


def balance_cache(w):
    """Balance cache health."""
    context = {}
    # Blockchain metrics (events removed; keep balance cache health only)
    from blockchain.models import Balance
    context['cached_balances'] = Balance.objects.count()
    context['stale_balances'] = Balance.objects.filter(is_stale=True).count()

    # Add time-based staleness (older than 24h) since background task is disabled
    stale_threshold_time = timezone.now() - timedelta(hours=24)
    context['stale_balances'] = Balance.objects.filter(
        Q(is_stale=True) | Q(last_synced__lt=stale_threshold_time)
    ).count()

    context['balance_cache_health'] = {
        'total': context['cached_balances'],
        'stale': context['stale_balances'],
        'fresh': context['cached_balances'] - context['stale_balances'],
        'stale_percentage': (context['stale_balances'] / context['cached_balances'] * 100) if context['cached_balances'] > 0 else 0
    }

    # Recent blockchain sync status
    last_sync = Balance.objects.filter(
        last_blockchain_check__isnull=False
    ).order_by('-last_blockchain_check').first()
    context['last_blockchain_sync'] = last_sync.last_blockchain_check if last_sync else None
    return context


def verifications(w):
    """Latest identity documents."""
    context = {}
    # ID verifications (differentiate personal vs business)
    context['pending_verifications_count'] = IdentityVerification.all_documents.filter(status='pending').count()
    recent_verifs_qs = IdentityVerification.all_documents.select_related('user').order_by('-created_at')[:10]
    recent_verifs = []
    for v in recent_verifs_qs:
        rf = v.risk_factors or {}
        acct_type = rf.get('account_type') or 'personal'
        biz = None
        if acct_type == 'business':
            try:
                biz_id = rf.get('business_id')
                if biz_id:
                    biz = Business.objects.filter(id=biz_id).first()
            except Exception:
                biz = None
        recent_verifs.append({
            'obj': v,
            'context': acct_type,
            'business': biz,
        })
    context['recent_verifications'] = recent_verifs
    return context


def presale(w):
    """CONFIO presale phases and waitlist."""
    context = {}
    # Presale metrics
    from presale.models import PresalePhase, PresalePurchase, PresaleSettings, PresaleWaitlist
    presale_settings = PresaleSettings.get_settings()

    # Waitlist metrics (always show, even when presale is inactive)
    context['presale_waitlist_total'] = PresaleWaitlist.objects.count()
    context['presale_waitlist_unnotified'] = PresaleWaitlist.objects.filter(notified=False).count()
    context['presale_waitlist_notified'] = PresaleWaitlist.objects.filter(notified=True).count()

    # Get all presale phases to show their status
    context['presale_global_enabled'] = presale_settings.is_presale_active
    context['all_presale_phases'] = PresalePhase.objects.all().order_by('-phase_number')

    # Active presale (only when global switch is on AND phase is active)
    active_presale = PresalePhase.objects.filter(status='active').first() if presale_settings.is_presale_active else None

    if active_presale:
        context['presale_active'] = True
        context['presale_phase'] = active_presale.phase_number
        context['presale_name'] = active_presale.name
        context['presale_raised'] = active_presale.total_raised
        context['presale_goal'] = active_presale.goal_amount
        context['presale_progress'] = active_presale.progress_percentage
        context['presale_participants'] = active_presale.total_participants
        context['presale_price'] = active_presale.price_per_token

        # Recent purchases
        context['recent_presale_purchases'] = PresalePurchase.objects.filter(
            phase=active_presale,
            status='completed'
        ).select_related('user').order_by('-created_at')[:5]
    else:
        context['presale_active'] = False
    return context


def guardarian(w):
    """Guardarian on-ramp sessions."""
    context = {}
    # Guardarian Metrics
    from usdc_transactions.models import GuardarianTransaction

    # Volume (Successful only - USDC)
    guardarian_volume = GuardarianTransaction.objects.filter(
        onchain_deposit__isnull=False
    ).aggregate(total=Sum('to_amount_actual'))['total'] or Decimal('0')

    # Transaction Counts
    guardarian_total = GuardarianTransaction.objects.count()

    # KPI 2: Provider Completion (Guardarian says finished)
    provider_completed_count = GuardarianTransaction.objects.filter(status='finished').count()

    # KPI 1: On-chain Completion (We received USDC)
    onchain_completed_count = GuardarianTransaction.objects.filter(onchain_deposit__isnull=False).count()

    # Abandoned/Idle Logic (Grey Box)
    # "Active" but older than 1 hour = Abandoned (Window Shopping)
    one_hour_ago = timezone.now() - timedelta(hours=1)
    active_states = ['new', 'waiting', 'pending', 'sending', 'exchanging']

    abandoned_count = GuardarianTransaction.objects.filter(
        status__in=active_states,
        created_at__lt=one_hour_ago
    ).count()

    # Real Active (In Progress < 1h)
    real_active_count = GuardarianTransaction.objects.filter(
        status__in=active_states,
        created_at__gte=one_hour_ago
    ).count()

    # Breakdown buckets
    failed_count = GuardarianTransaction.objects.filter(status='failed').count()
    expired_count = GuardarianTransaction.objects.filter(status='expired').count()
    refunded_count = GuardarianTransaction.objects.filter(status='refunded').count()
    hold_count = GuardarianTransaction.objects.filter(status='hold').count()

    # Rates
    # KPI 1: On-chain Rate = How many "Finished" transactions actually arrived?
    # Target: 100%
    onchain_rate = (onchain_completed_count / provider_completed_count * 100) if provider_completed_count > 0 else 0

    # KPI 2: Provider Rate = How many sessions finished?
    provider_rate = (provider_completed_count / guardarian_total * 100) if guardarian_total > 0 else 0

    context['guardarian_stats'] = {
        'volume': guardarian_volume,
        'total_sessions': guardarian_total,
        'onchain_completed': onchain_completed_count,
        'provider_completed': provider_completed_count,
        'onchain_rate': onchain_rate,
        'provider_rate': provider_rate,
        'abandoned_count': abandoned_count,
        'real_active_count': real_active_count,
        'failed_count': failed_count,
        'expired_count': expired_count,
        'refunded_count': refunded_count,
        'hold_count': hold_count,
    }

    # Top Currencies (Successful only)
    context['guardarian_currencies'] = GuardarianTransaction.objects.filter(
        status='finished'
    ).values('from_currency').annotate(
        usdc_volume=Sum('to_amount_actual'),
        local_volume=Sum('from_amount'),
        count=Count('id')
    ).order_by('-usdc_volume')[:5]

    # Top Countries by attempted sessions/users
    context['guardarian_attempt_countries'] = GuardarianTransaction.objects.values(
        'user__phone_country'
    ).annotate(
        count=Count('user', distinct=True)
    ).order_by('-count')[:5]

    # Top Countries by verified completed volume/users
    context['guardarian_completed_countries'] = GuardarianTransaction.objects.filter(
        onchain_deposit__isnull=False
    ).values(
        'user__phone_country'
    ).annotate(
        usdc_volume=Sum('to_amount_actual'),
        count=Count('user', distinct=True),
        tx_count=Count('id'),
    ).order_by('-usdc_volume')[:5]

    # Recent Transactions
    context['guardarian_recent'] = GuardarianTransaction.objects.select_related(
        'user'
    ).order_by('-created_at')[:10]
    return context


def koywe(w, request):
    """Koywe on/off-ramp sections with the country/direction filters."""
    one_hour_ago = w.now - timedelta(hours=1)
    context = {}
    # Koywe Metrics (Grey Box Analysis)
    koywe_country_filter = (request.GET.get('koywe_country') or '').strip().upper()
    koywe_direction_filter = (request.GET.get('koywe_direction') or 'all').strip().lower()
    if koywe_direction_filter not in {'all', 'on_ramp', 'off_ramp'}:
        koywe_direction_filter = 'all'

    koywe_provider_completed_statuses = ['DELIVERED', 'CRYPTO_DELIVERED', 'FIAT_DELIVERED']
    koywe_provider_refunded_statuses = ['REFUNDED', 'REFUND_DELIVERED']
    koywe_provider_expired_statuses = ['CANCELLED']
    koywe_provider_failed_statuses = ['REJECTED', 'FAILED', 'INVALID_WITHDRAWALS_DETAILS']

    def build_koywe_section(*, direction: str, title: str, icon: str, volume_label: str, volume_change: str):
        qs = RampTransaction.objects.filter(
            provider='koywe',
            direction=direction,
        ).select_related('actor_user')
        if koywe_country_filter:
            qs = qs.filter(country_code=koywe_country_filter)

        refunded_q = (
            Q(metadata__koywe_status__in=koywe_provider_refunded_statuses)
            | Q(status_detail__icontains='refund')
            | Q(status_detail__icontains='refunded')
        )
        expired_q = (
            Q(metadata__koywe_status__in=koywe_provider_expired_statuses)
            | Q(status_detail__icontains='expired')
            | Q(status_detail__icontains='cancelled')
            | Q(status_detail__icontains='canceled')
        )
        failed_q = (
            Q(metadata__koywe_status__in=koywe_provider_failed_statuses)
            | Q(status='FAILED')
        )

        volume = qs.filter(
            status='COMPLETED',
        ).aggregate(total=Sum('final_amount'))['total'] or Decimal('0')

        total_sessions = qs.count()
        provider_completed_count = qs.filter(
            metadata__koywe_status__in=koywe_provider_completed_statuses,
        ).count()
        onchain_completed_count = qs.filter(status='COMPLETED').count()

        abandoned_count = qs.filter(
            status__in=['PENDING', 'PROCESSING'],
            created_at__lt=one_hour_ago,
        ).count()
        real_active_count = qs.filter(
            status__in=['PENDING', 'PROCESSING'],
            created_at__gte=one_hour_ago,
        ).count()

        refunded_count = qs.filter(refunded_q).count()
        expired_count = qs.filter(expired_q).exclude(refunded_q).count()
        failed_count = qs.filter(failed_q).exclude(refunded_q | expired_q).count()

        onchain_rate = (
            onchain_completed_count / provider_completed_count * 100
        ) if provider_completed_count > 0 else 0
        provider_rate = (
            provider_completed_count / total_sessions * 100
        ) if total_sessions > 0 else 0

        currencies = qs.filter(
            status='COMPLETED'
        ).values('fiat_currency').annotate(
            usdc_volume=Sum('final_amount'),
            local_volume=Sum('fiat_amount'),
            count=Count('id')
        ).order_by('-usdc_volume')[:5]

        attempt_countries = qs.values(
            'actor_user__phone_country'
        ).annotate(
            count=Count('actor_user', distinct=True)
        ).order_by('-count')[:5]

        completed_countries = qs.filter(
            status='COMPLETED'
        ).values(
            'actor_user__phone_country'
        ).annotate(
            usdc_volume=Sum('final_amount'),
            count=Count('actor_user', distinct=True),
            tx_count=Count('id'),
        ).order_by('-usdc_volume')[:5]

        recent = qs.order_by('-created_at')[:10]

        # Which rail the fiat actually landed on / left from. A ramp row
        # is pinned to a destination at creation (RampTransaction.
        # destination), so a single "cUSD delivered" label has been wrong
        # for every cusd_plus row since the BSC rail opened.
        destinations = list(
            qs.filter(status='COMPLETED')
            .values('destination')
            .annotate(volume=Sum('final_amount'), count=Count('id'))
            .order_by('-volume')
        )
        destination_labels = dict(
            RampTransaction._meta.get_field('destination').choices or []
        )
        for row in destinations:
            row['label'] = destination_labels.get(
                row['destination'], row['destination'] or 'unset'
            )

        return {
            'title': title,
            'icon': icon,
            'volume_label': volume_label,
            'volume_change': volume_change,
            'destinations': destinations,
            'stats': {
                'volume': volume,
                'total_sessions': total_sessions,
                'onchain_completed': onchain_completed_count,
                'provider_completed': provider_completed_count,
                'onchain_rate': onchain_rate,
                'provider_rate': provider_rate,
                'abandoned_count': abandoned_count,
                'real_active_count': real_active_count,
                'failed_count': failed_count,
                'expired_count': expired_count,
                'refunded_count': refunded_count,
            },
            'currencies': currencies,
            'attempt_countries': attempt_countries,
            'completed_countries': completed_countries,
            'recent': recent,
        }

    base_koywe_qs = RampTransaction.objects.filter(provider='koywe')
    available_koywe_countries = [
        code for code in base_koywe_qs.order_by().values_list('country_code', flat=True).distinct() if code
    ]

    context['koywe_country_filter'] = koywe_country_filter
    context['koywe_direction_filter'] = koywe_direction_filter
    context['koywe_country_options'] = available_koywe_countries
    context['show_koywe_onramp'] = koywe_direction_filter in {'all', 'on_ramp'}
    context['show_koywe_offramp'] = koywe_direction_filter in {'all', 'off_ramp'}

    context['koywe_onramp'] = build_koywe_section(
        direction='on_ramp',
        title='Koywe On-Ramp',
        icon='💸',
        volume_label='On-chain Deposited Volume',
        volume_change='Verified delivery (cUSD + cUSD+)',
    )
    context['koywe_offramp'] = build_koywe_section(
        direction='off_ramp',
        title='Koywe Off-Ramp',
        icon='🏦',
        volume_label='On-chain Sent Volume',
        volume_change='Verified send (cUSD + cUSD+)',
    )
    return context


def cusd_bsc(w, *, refresh=False):
    """cUSD on BSC (USDT-backed payment rail) and every Confío fee by source.

    Kept apart from cUSD+ (USDY-backed): one blended number would hide a
    collateral or fee-accounting failure in either contract.
    """
    from cusd_plus.metrics import (
        get_cusd_bsc_platform_metrics,
        get_fee_ledger_summary,
        get_stock_router_metrics,
    )

    return {
        'cusd_bsc_metrics': _admin_cached('cusd_bsc', get_cusd_bsc_platform_metrics, w, refresh=refresh),
        'fee_ledger': get_fee_ledger_summary(),
        # The fee table lists the legacy router fee still uncollected there.
        'stock_router_metrics': _admin_cached('stock_router', get_stock_router_metrics, w, refresh=refresh),
    }


def infinia(request):
    """Infinia journeys, provider deposit volumes and the website's Movido."""
    from payment_accounts.monitoring import dashboard_context

    return dashboard_context(request)


def cusd_plus(w, *, refresh=False):
    """cUSD+ vault state and the savings sagas that feed it."""
    from cusd_plus.metrics import (
        get_cusd_bsc_platform_metrics,
        get_cusd_plus_platform_metrics,
        get_savings_saga_stats,
    )

    metrics = _admin_cached('cusd_plus', get_cusd_plus_platform_metrics, w, refresh=refresh)
    return {
        'cusd_plus_metrics': metrics,
        # cUSD+ conversions pay the shared cUSD perimeter fee.
        'cusd_bsc_metrics': _admin_cached('cusd_bsc', get_cusd_bsc_platform_metrics, w, refresh=refresh),
        'cusd_plus_circulating': metrics.circulating_cusd_plus,
        'cusd_plus_reserve': metrics.usdy_reserve_usd,
        'cusd_plus_source': metrics.source,
        'savings_stats': get_savings_saga_stats(since=w.rolling_30_start),
    }


def stocks(w, *, refresh=False):
    """Ondo Stocks: settlement, router fee accounting and current holdings.

    Executed through the sponsorship rail, but sponsorship health alone cannot
    say whether a batch was a buy or a sell, how much settled, or how much fee
    remains withdrawable in the router.
    """
    from cusd_plus import gm_tvl
    from cusd_plus.metrics import get_stock_router_metrics, get_stock_trade_stats
    from django.utils.dateparse import parse_datetime

    # Same chain-derived, marked-to-market snapshot served to the app. Never
    # substitute settlement volume: volume is a flow, this is current value.
    stock_portfolio = gm_tvl.snapshot()
    if stock_portfolio is not None:
        stock_portfolio = dict(stock_portfolio)
        stock_portfolio['assets'] = list(stock_portfolio.get('assets', []))
        stock_portfolio['updated_at_dt'] = parse_datetime(stock_portfolio.get('updated_at', ''))
    return {
        'stock_stats_24h': get_stock_trade_stats(since=w.last_24h),
        'stock_stats_30d': get_stock_trade_stats(since=w.rolling_30_start),
        'stock_router_metrics': _admin_cached('stock_router', get_stock_router_metrics, w, refresh=refresh),
        'stock_portfolio': stock_portfolio,
    }


def sponsorship(w):
    """7702 sponsorship + BNB rescue health. Every user-facing BSC action
    rides the sponsor, so its failure counters are the BSC rail's health."""
    from cusd_plus.metrics import get_bnb_autoconvert_stats, get_sponsorship_stats

    return {
        'sponsorship_stats': get_sponsorship_stats(since=w.last_24h),
        'sponsorship_stats_7d': get_sponsorship_stats(since=w.last_7_start),
        'bnb_autoconvert_stats': get_bnb_autoconvert_stats(),
    }


# ── Today ────────────────────────────────────────────────────────────────

CRITICAL, WARNING = 'critical', 'warning'


def _item(level, title, detail='', url=None, count=None):
    return {'level': level, 'title': title, 'detail': detail, 'url': url, 'count': count}


def needs_attention(w, request, *, refresh=False):
    """Only what is wrong right now, each with the list that fixes it.

    Every check states "don't know" as its own item: a chain read that fails
    shows up as unavailable, never as a silent pass.
    """
    from cusd_plus.metrics import (
        get_bnb_autoconvert_stats,
        get_cusd_bsc_platform_metrics,
        get_cusd_plus_platform_metrics,
        get_sponsorship_stats,
        get_stock_trade_stats,
    )
    from usdc_transactions.models import GuardarianTransaction

    items = []

    # Collateral and contract state.
    for label, key, build, page in (
        ('cUSD (BSC)', 'cusd_bsc', get_cusd_bsc_platform_metrics, 'dash_money'),
        ('cUSD+', 'cusd_plus', get_cusd_plus_platform_metrics, 'dash_savings'),
    ):
        metrics = _admin_cached(key, build, w, refresh=refresh)
        if metrics.source == 'unavailable':
            items.append(_item(WARNING, f'{label}: chain read unavailable',
                               'Supply and reserve could not be read; collateral is unknown.', _url(page)))
        elif metrics.source != 'unconfigured' and metrics.is_undercollateralised:
            items.append(_item(CRITICAL, f'{label} is undercollateralised',
                               f'Backing ratio {metrics.backing_ratio_bps / 100:.2f}%.', _url(page)))
        paused = getattr(metrics, 'paused', False)
        if paused:
            items.append(_item(CRITICAL, f'{label} contract is paused', '', _url(page)))
        elif paused is None and metrics.source not in ('unavailable', 'unconfigured'):
            items.append(_item(WARNING, f'{label}: pause state unreadable',
                               'Supply was read but the pause flag was not; the exit may be closed.', _url(page)))
        if getattr(metrics, 'redeem_blocked_reason', None):
            items.append(_item(WARNING, f'{label} redemptions blocked', metrics.redeem_blocked_reason, _url(page)))

    # Savings sagas: not windowed, a saga stuck since last month matters most.
    sagas = Conversion.objects.filter(conversion_type__in=Conversion.SAVINGS_TYPES, is_deleted=False)
    saga_counts = sagas.aggregate(
        stuck=Count('id', filter=Q(status='STUCK')),
        stale_in_flight=Count('id', filter=Q(status__in=Conversion.IN_FLIGHT_STATUSES,
                                             updated_at__lt=w.now - timedelta(hours=1)) & ~Q(status='STUCK')),
    )
    if saga_counts['stuck']:
        items.append(_item(CRITICAL, 'Savings sagas stuck', 'Value sits at a user-owned address until resolved.',
                           _url('conversion_conversion_changelist', 'status__exact=STUCK'), saga_counts['stuck']))
    if saga_counts['stale_in_flight']:
        items.append(_item(WARNING, 'Savings sagas in flight for over an hour', '',
                           _url('conversion_conversion_changelist'), saga_counts['stale_in_flight']))

    # Sponsorship (7702) and BNB rescue.
    sponsor = get_sponsorship_stats(since=w.last_24h)
    if sponsor['failed']:
        items.append(_item(WARNING, 'Sponsored transactions failed (24h)', 'Reverted, dropped, reorged or no-op.',
                           _url('blockchain_sponsoredbatch_changelist'), sponsor['failed']))
    if sponsor['unresolved_all_time']:
        items.append(_item(WARNING, 'Sponsored transactions never resolved', 'Signed or sent, no receipt.',
                           _url('blockchain_sponsoredbatch_changelist', 'status__in=signed,sent'),
                           sponsor['unresolved_all_time']))
    autoconvert = get_bnb_autoconvert_stats()
    if autoconvert.get('pending'):
        items.append(_item(WARNING, 'BNB auto-converts pending', '',
                           _url('blockchain_pendingautoswap_changelist'), autoconvert['pending']))
    stock_trades = get_stock_trade_stats(since=w.rolling_30_start)
    if stock_trades['history_missing']:
        items.append(_item(WARNING, 'Stock trades confirmed without settlement history (30d)', '',
                           _url('dash_savings'), stock_trades['history_missing']))

    # Ramps.
    ramp_failed = RampTransaction.objects.filter(status='FAILED', updated_at__gte=w.last_24h).count()
    if ramp_failed:
        items.append(_item(WARNING, 'Ramp transactions failed (24h)', 'Koywe and other ramp providers.',
                           _url('ramps_ramptransaction_changelist', 'status__exact=FAILED'), ramp_failed))
    guardarian_hold = GuardarianTransaction.objects.filter(status='hold').count()
    if guardarian_hold:
        items.append(_item(WARNING, 'Guardarian sessions on hold', '',
                           _url('usdc_transactions_guardariantransaction_changelist', 'status__exact=hold'),
                           guardarian_hold))
    # Same permission the Money page's Infinia section requires.
    if request.user.has_perm('payment_accounts.view_infiniajourney'):
        from payment_accounts.monitoring import needs_review_count, stalled_count

        infinia_stalled = stalled_count()
        if infinia_stalled:
            items.append(_item(WARNING, 'Infinia transfers not moving for over an hour', '',
                               _url('payment_accounts_infiniajourney_changelist'), infinia_stalled))
        infinia_review = needs_review_count()
        if infinia_review:
            items.append(_item(WARNING, 'Infinia transfers halted for review', '',
                               _url('payment_accounts_infiniajourney_changelist', 'stage__exact=needs_review'),
                               infinia_review))

    # Identity.
    pending_ids = IdentityVerification.all_documents.filter(status='pending').count()
    if pending_ids:
        items.append(_item(WARNING, 'ID documents waiting for review', '',
                           _url('security_identityverification_changelist', 'status__exact=pending'), pending_ids))

    # Legacy P2P: deprecated, but an escalated dispute is still someone's money.
    escalated = P2PDispute.objects.filter(status='ESCALATED').count()
    if escalated:
        items.append(_item(CRITICAL, 'Escalated P2P disputes', '',
                           _url('p2p_exchange_p2pdispute_changelist', 'status__exact=ESCALATED'), escalated))

    # Our own reporting pipeline: a missing nightly job makes every number stale.
    yesterday = w.today_arg - timedelta(days=1)
    latest_snapshot = DailyMetrics.objects.order_by('-date').values_list('date', flat=True).first()
    if latest_snapshot is None or latest_snapshot < yesterday:
        items.append(_item(WARNING, 'Nightly analytics snapshot missing',
                           f'Latest DailyMetrics: {latest_snapshot or "none"}.', _url('users_dailymetrics_changelist')))
    if not FunnelDailyRollup.objects.filter(date=yesterday).exists() and \
            FunnelEvent.objects.filter(created_at__gte=w.now - timedelta(days=2),
                                       created_at__lt=w.today_start).exists():
        items.append(_item(WARNING, "Yesterday's funnel rollup missing", 'Funnels fall back to raw events.',
                           _url('users_funneldailyrollup_changelist')))

    items.sort(key=lambda item: item['level'] != CRITICAL)
    return items


def today_money(w, *, refresh=False):
    """Headline money figures. Movido is the exact snapshot the website shows."""
    from cusd_plus import gm_tvl
    from cusd_plus.metrics import get_fee_ledger_summary, get_stock_trade_stats
    from cusd_plus.metrics import get_cusd_bsc_platform_metrics, get_cusd_plus_platform_metrics
    from ramps.metrics import public_fund_flow_snapshot

    try:
        movido = public_fund_flow_snapshot()
    except Exception:  # noqa: BLE001 — shown as unavailable, never as zero
        movido = None
    portfolio = gm_tvl.snapshot()
    cusd_bsc_metrics = _admin_cached('cusd_bsc', get_cusd_bsc_platform_metrics, w, refresh=refresh)
    return {
        'movido': movido,
        'fee_ledger': get_fee_ledger_summary(),
        'cusd_bsc_metrics': cusd_bsc_metrics,
        'cusd_bsc_backing_pct': (
            cusd_bsc_metrics.backing_ratio_bps / 100 if cusd_bsc_metrics.backing_ratio_bps is not None else None
        ),
        'cusd_plus_metrics': _admin_cached('cusd_plus', get_cusd_plus_platform_metrics, w, refresh=refresh),
        'stock_portfolio_value': (portfolio or {}).get('value_usd'),
        'stock_stats_24h': get_stock_trade_stats(since=w.last_24h),
    }


def today_growth(w):
    """Headline growth figures, one query each."""
    from security.identity_status import verified_user_ids

    real_users = get_real_users_queryset()

    thirty_days_ago = w.now.date() - timedelta(days=30)
    latest_snapshot = DailyMetrics.objects.order_by('-date').first()
    return {
        'total_users': real_users.count(),
        'new_users_last_7_days': real_users.filter(created_at__gte=w.last_7_start).count(),
        'new_users_today': real_users.filter(created_at__gte=w.today_start).count(),
        'active_users_today': real_users.filter(last_activity_at__gte=w.last_24h).count(),
        'active_users_week': real_users.filter(last_activity_at__gte=w.last_7_start).count(),
        'active_users_month': real_users.filter(last_activity_at__gte=w.rolling_30_start).count(),
        'verified_users': verified_user_ids().count(),
        'metrics_trend': list(
            DailyMetrics.objects.filter(date__gte=thirty_days_ago)
            .order_by('date').values('date', 'dau', 'wau', 'mau', 'new_users_today')
        ),
        'top_countries_metrics': list(
            CountryMetrics.objects.filter(date=latest_snapshot.date)
            .order_by('-mau')[:8].values('country_code', 'dau', 'mau', 'total_users')
        ) if latest_snapshot else [],
    }


def trend_chart(rows):
    """DailyMetrics rows as JSON-safe points for the growth chart."""
    return [
        {'label': row['date'].strftime('%b %-d'), 'dau': row['dau'], 'wau': row['wau'], 'mau': row['mau']}
        for row in rows
    ]
