"""
Custom Admin Dashboard for Confío
Provides a comprehensive overview of platform metrics and quick actions
"""
from django.contrib import admin
from two_factor.admin import AdminSiteOTPRequired
from django.urls import path
from django.shortcuts import render, redirect
from django.utils import timezone
from django.db.models import Count, Sum, Q, F, Avg
from django.db.models.functions import Cast
from django.db.models import DecimalField
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.html import format_html
from django.contrib import messages
from datetime import datetime, timedelta
from decimal import Decimal

from users.models import User, Account, Business, Country, Bank, BankInfo, WalletPepper, WalletDerivationPepper
from security.models import IdentityVerification, DeviceFingerprint
from achievements.admin_views import achievement_dashboard
from achievements.models import (
    UserAchievement,
    ReferralWithdrawalLog,
    ConfioRewardTransaction,
    UserReferral,
    ReferralRewardEvent,
)
from p2p_exchange.models import P2POffer, P2PTrade, P2PUserStats, P2PDispute
from send.models import SendTransaction
from payments.models import PaymentTransaction
from blockchain.constants import REFERRAL_ACHIEVEMENT_SLUGS


class ConfioAdminSite(AdminSiteOTPRequired):
    """Custom admin site with enhanced dashboard"""
    site_header = 'Confío Admin Panel'
    site_title = 'Confío Admin'
    index_title = 'Welcome to Confío Administration'
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('', self.admin_view(self.dashboard_view), name='index'),
            path('dashboard/', self.admin_view(self.dashboard_view), name='dashboard'),
            path('p2p-analytics/', self.admin_view(self.p2p_analytics_view), name='p2p_analytics'),
            path('user-analytics/', self.admin_view(self.user_analytics_view), name='user_analytics'),
            path('transaction-analytics/', self.admin_view(self.transaction_analytics_view), name='transaction_analytics'),
            path('blockchain-analytics/', self.admin_view(self.blockchain_analytics_view), name='blockchain_analytics'),
            path('blockchain-analytics/scan-now/', self.admin_view(self.blockchain_scan_now_view), name='blockchain_scan_now'),
            path('achievements/', self.admin_view(self.achievement_dashboard_view), name='achievement_dashboard'),
        ]
        return custom_urls + urls
    
    def dashboard_view(self, request):
        """Main dashboard with key metrics"""
        context = dict(
            self.each_context(request),
            title="Dashboard Overview",
        )
        
        # Time ranges
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        last_24h = now - timedelta(hours=24)
        week_start = today_start - timedelta(days=today_start.weekday())
        last_7_start = now - timedelta(days=7)
        month_start = today_start.replace(day=1)
        
        # User metrics
        # DAU/MAU now uses centralized last_activity_at field (single source of truth)
        # See users/activity_tracking.py for activity tracking implementation
        context['total_users'] = User.objects.filter(phone_number__isnull=False).count()
        context['active_users_today'] = User.objects.filter(phone_number__isnull=False, last_activity_at__gte=last_24h).count()
        context['new_users_last_7_days'] = User.objects.filter(phone_number__isnull=False, created_at__gte=last_7_start).count()
        context['verified_users'] = IdentityVerification.objects.filter(status='verified').count()
        
        # V2 Migration & Backup Security Metrics
        # Uses Account model for migration status (per-account tracking)
        from users.models import Account
        total_active_for_stats = context['active_users_today'] if context['active_users_today'] > 0 else 1
        drive_users = User.objects.filter(phone_number__isnull=False, backup_provider='google_drive').count()
        migrated_accounts = Account.objects.filter(is_keyless_migrated=True).count()
        # For safe V2 users, count users with both backup verified AND at least one migrated account
        safe_v2_users = User.objects.filter(
            phone_number__isnull=False, 
            backup_verified_at__isnull=False,
            accounts__is_keyless_migrated=True
        ).distinct().count()
        
        context['security_stats'] = {
            'drive_count': drive_users,
            'drive_pct': (drive_users / context['total_users'] * 100) if context['total_users'] else 0,
            'migrated_count': migrated_accounts,
            'migrated_pct': (migrated_accounts / context['total_users'] * 100) if context['total_users'] else 0,
            'safe_v2_count': safe_v2_users,
            'safe_v2_pct': (safe_v2_users / context['total_users'] * 100) if context['total_users'] else 0,
        }
        
        # OS Stats (Explicit from Login)
        ios_users = User.objects.filter(platform_os='ios').count()
        android_users = User.objects.filter(platform_os='android').count()
        
        context['os_stats'] = {
            'ios_count': ios_users,
            'ios_pct': (ios_users / context['total_users'] * 100) if context['total_users'] else 0,
            'android_count': android_users,
            'android_pct': (android_users / context['total_users'] * 100) if context['total_users'] else 0,
        }
        
        # Historical metrics from snapshots
        from users.models_analytics import DailyMetrics, CountryMetrics
        
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
        
        # Account metrics
        context['total_accounts'] = Account.objects.count()
        context['business_accounts'] = Account.objects.filter(account_type='business').count()
        context['personal_accounts'] = Account.objects.filter(account_type='personal').count()
        
        # P2P Trading metrics
        context['active_offers'] = P2POffer.objects.filter(status='ACTIVE').count()
        context['trades_today'] = P2PTrade.objects.filter(created_at__gte=today_start).count()
        context['trades_this_week'] = P2PTrade.objects.filter(created_at__gte=week_start).count()
        context['trades_this_month'] = P2PTrade.objects.filter(created_at__gte=month_start).count()
        
        # Trade volume
        trades_this_month = P2PTrade.objects.filter(
            created_at__gte=month_start,
            status__in=['COMPLETED', 'CRYPTO_RELEASED']
        )
        
        cusd_volume = trades_this_month.filter(
            offer__token_type='cUSD'
        ).aggregate(
            total=Sum('crypto_amount')
        )['total'] or Decimal('0')
        
        confio_volume = trades_this_month.filter(
            offer__token_type='CONFIO'
        ).aggregate(
            total=Sum('crypto_amount')
        )['total'] or Decimal('0')
        
        context['monthly_cusd_volume'] = cusd_volume
        context['monthly_confio_volume'] = confio_volume
        
        # Dispute metrics
        context['open_disputes'] = P2PDispute.objects.filter(
            status__in=['OPEN', 'UNDER_REVIEW']
        ).count()
        context['escalated_disputes'] = P2PDispute.objects.filter(status='ESCALATED').count()
        # Ongoing/new disputes
        context['ongoing_disputes'] = P2PDispute.objects.select_related('trade', 'initiator_user', 'initiator_business').filter(
            status__in=['OPEN', 'UNDER_REVIEW']
        ).annotate(
            evidence_count=Count('evidences')
        ).order_by('-opened_at')[:10]
        
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

        referral_achievement_ids = list(
            UserAchievement.objects.filter(
                achievement_type__slug__in=REFERRAL_ACHIEVEMENT_SLUGS
            ).values_list('id', flat=True)
        )
        referral_earned_total = ConfioRewardTransaction.objects.filter(
            transaction_type='earned',
            reference_type='achievement',
            reference_id__in=[str(pk) for pk in referral_achievement_ids],
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        referral_available = referral_earned_total - total_withdrawn
        if referral_available < Decimal('0'):
            referral_available = Decimal('0')

        multi_user_devices = DeviceFingerprint.objects.annotate(
            user_count=Count(
                'users',
                filter=Q(users__achievements__achievement_type__slug__in=REFERRAL_ACHIEVEMENT_SLUGS),
                distinct=True,
            )
        ).filter(user_count__gt=1).count()

        context['fraud_stats'] = {
            'earned_total': referral_earned_total,
            'available_total': referral_available,
            'total_withdrawn': total_withdrawn,
            'daily_withdrawn': daily_withdrawn,
            'weekly_withdrawn': weekly_withdrawn,
            'pending_review': pending_review,
            'high_value': high_value,
            'unique_users': unique_referral_users,
            'multi_user_devices': multi_user_devices,
        }

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
        
        # Transaction metrics
        context['send_transactions_today'] = SendTransaction.objects.filter(
            created_at__gte=today_start
        ).exclude(status='FAILED').count()
        
        context['payment_transactions_today'] = PaymentTransaction.objects.filter(
            created_at__gte=today_start
        ).exclude(status='FAILED').count()
        
        # Conversion metrics
        from conversion.models import Conversion
        context['conversions_today'] = Conversion.objects.filter(
            created_at__gte=today_start
        ).count()
        context['conversions_last_7_days'] = Conversion.objects.filter(
            created_at__gte=last_7_start
        ).count()
        
        # Notification metrics
        from notifications.models import Notification, FCMDeviceToken
        context['notifications_sent_today'] = Notification.objects.filter(
            created_at__gte=today_start
        ).count()
        context['push_notifications_today'] = Notification.objects.filter(
            created_at__gte=today_start,
            push_sent=True
        ).count()
        context['active_fcm_tokens'] = FCMDeviceToken.objects.filter(
            is_active=True
        ).count()
        context['last_broadcast'] = Notification.objects.filter(
            is_broadcast=True
        ).order_by('-created_at').first()
        
        # Monthly volumes
        conversions_volume = Conversion.objects.filter(
            created_at__gte=month_start,
            status='COMPLETED'
        ).aggregate(
            usdc_to_cusd=Sum('from_amount', filter=Q(conversion_type='usdc_to_cusd')),
            cusd_to_usdc=Sum('from_amount', filter=Q(conversion_type='cusd_to_usdc'))
        )
        context['usdc_to_cusd_volume'] = conversions_volume['usdc_to_cusd'] or Decimal('0')
        context['cusd_to_usdc_volume'] = conversions_volume['cusd_to_usdc'] or Decimal('0')
        
        # Calculate net USDC inflow (positive means more USDC → cUSD)
        context['net_usdc_inflow'] = context['usdc_to_cusd_volume'] - context['cusd_to_usdc_volume']
        
        # Calculate circulating cUSD (cumulative net conversions)
        all_conversions = Conversion.objects.filter(
            status='COMPLETED'
        ).aggregate(
            total_usdc_to_cusd=Sum('to_amount', filter=Q(conversion_type='usdc_to_cusd')),
            total_cusd_to_usdc=Sum('from_amount', filter=Q(conversion_type='cusd_to_usdc'))
        )
        total_minted = all_conversions['total_usdc_to_cusd'] or Decimal('0')
        total_burned = all_conversions['total_cusd_to_usdc'] or Decimal('0')
        context['circulating_cusd'] = total_minted - total_burned
        
        # Country breakdown for P2P
        country_stats = P2POffer.objects.filter(
            status='ACTIVE'
        ).values('country_code').annotate(
            count=Count('id')
        ).order_by('-count')[:5]
        
        context['top_countries'] = country_stats
        
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
        
        # Processing success rate removed (no separate event processing logs)
        
        # Recent activities
        context['recent_trades'] = P2PTrade.objects.select_related(
            'buyer_user', 'seller_user', 'offer'
        ).order_by('-created_at')[:10]
        
        context['recent_disputes'] = P2PDispute.objects.select_related(
            'trade', 'initiator_user'
        ).order_by('-opened_at')[:5]

        # ID verifications (differentiate personal vs business)
        context['pending_verifications_count'] = IdentityVerification.objects.filter(status='pending').count()
        recent_verifs_qs = IdentityVerification.objects.select_related('user').order_by('-created_at')[:10]
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
            volume=Sum('from_amount'),
            count=Count('id')
        ).order_by('-volume')[:5]
        
        # Top Countries (by User count)
        context['guardarian_countries'] = GuardarianTransaction.objects.values(
            'user__phone_country'
        ).annotate(
            count=Count('user', distinct=True)
        ).order_by('-count')[:5]

        # Recent Transactions
        context['guardarian_recent'] = GuardarianTransaction.objects.select_related(
            'user'
        ).order_by('-created_at')[:10]

        return render(request, 'admin/dashboard.html', context)
    
    def p2p_analytics_view(self, request):
        """Detailed P2P trading analytics"""
        context = dict(
            self.each_context(request),
            title="P2P Trading Analytics",
        )
        
        # Get date range from request
        days = int(request.GET.get('days', 30))
        start_date = timezone.now() - timedelta(days=days)
        
        # Trading volume by day
        daily_trades = P2PTrade.objects.filter(
            created_at__gte=start_date
        ).extra(
            select={'day': 'date(p2p_exchange_p2ptrade.created_at)'}
        ).values('day').annotate(
            count=Count('id'),
            cusd_volume=Sum('crypto_amount', filter=Q(offer__token_type='cUSD')),
            confio_volume=Sum('crypto_amount', filter=Q(offer__token_type='CONFIO'))
        ).order_by('day')
        
        context['daily_trades'] = list(daily_trades)
        
        # Top traders
        top_traders = P2PUserStats.objects.select_related(
            'stats_user', 'stats_business'
        ).annotate(
            success_ratio=F('success_rate')
        ).order_by('-total_trades')[:20]
        
        context['top_traders'] = top_traders
        
        # Payment method popularity
        payment_methods = P2PTrade.objects.filter(
            created_at__gte=start_date
        ).values(
            'payment_method__display_name'
        ).annotate(
            count=Count('id')
        ).order_by('-count')[:10]
        
        context['payment_methods'] = payment_methods
        
        # Country performance
        country_performance = P2PTrade.objects.filter(
            created_at__gte=start_date
        ).values('country_code').annotate(
            trade_count=Count('id'),
            avg_completion_time=Avg(
                F('completed_at') - F('created_at'),
                filter=Q(status='COMPLETED')
            ),
            dispute_rate=Count('id', filter=Q(status='DISPUTED')) * 100.0 / Count('id')
        ).order_by('-trade_count')
        
        context['country_performance'] = country_performance
        
        return render(request, 'admin/p2p_analytics.html', context)
    
    def user_analytics_view(self, request):
        """User growth and engagement analytics"""
        context = dict(
            self.each_context(request),
            title="User Analytics",
        )
        
        # User growth by day
        from django.db.models.functions import TruncDate
        import pytz

        # User growth by day (Argentina Time)
        tz = pytz.timezone('America/Argentina/Buenos_Aires')
        days = int(request.GET.get('days', 30))
        
        # Calculate start date in Argentina time (midnight 30 days ago)
        now_arg = timezone.now().astimezone(tz)
        start_date_arg = (now_arg - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
        start_date_utc = start_date_arg.astimezone(pytz.UTC)
        
        daily_signups = User.objects.filter(
            phone_number__isnull=False,
            created_at__gte=start_date_utc
        ).annotate(
            day=TruncDate('created_at', tzinfo=tz)
        ).values('day').annotate(
            count=Count('id')
        ).order_by('day')
        
        context['daily_signups'] = list(daily_signups)
        
        # Verification funnel
        context['users_total'] = User.objects.filter(phone_number__isnull=False).count()
        context['users_with_verification'] = IdentityVerification.objects.values(
            'user'
        ).distinct().count()
        context['users_verified'] = IdentityVerification.objects.filter(
            status='verified'
        ).values('user').distinct().count()
        
        # Account type distribution
        account_types = Account.objects.values(
            'account_type'
        ).annotate(
            count=Count('id')
        ).order_by('account_type')
        
        context['account_types'] = account_types
        
        # User activity metrics (using centralized last_activity_at)
        # All activity periods now use the same consistent method
        active_ranges = [
            ('Last 24h', 1),
            ('Last 7 days', 7),
            ('Last 30 days', 30),
            ('Last 90 days', 90),
        ]

        activity_metrics = []
        for label, days in active_ranges:
            cutoff = timezone.now() - timedelta(days=days)
            count = User.objects.filter(phone_number__isnull=False, last_activity_at__gte=cutoff).count()
            activity_metrics.append({
                'label': label,
                'count': count,
                'percentage': (count / context['users_total'] * 100) if context['users_total'] > 0 else 0
            })

        context['activity_metrics'] = activity_metrics
        
        return render(request, 'admin/user_analytics.html', context)
    
    def transaction_analytics_view(self, request):
        """Transaction flow analytics"""
        context = dict(
            self.each_context(request),
            title="Transaction Analytics",
        )
        
        days = int(request.GET.get('days', 30))
        start_date = timezone.now() - timedelta(days=days)
        
        # Send transactions by day
        daily_sends = SendTransaction.objects.filter(
            created_at__gte=start_date
        ).extra(
            select={'day': 'date(send_sendtransaction.created_at)'}
        ).values('day').annotate(
            count=Count('id'),
            cusd_count=Count('id', filter=Q(token_type='cUSD')),
            confio_count=Count('id', filter=Q(token_type='CONFIO')),
            failed_count=Count('id', filter=Q(status='FAILED'))
        ).order_by('day')
        
        context['daily_sends'] = list(daily_sends)
        
        # Payment transactions by day
        daily_payments = PaymentTransaction.objects.filter(
            created_at__gte=start_date
        ).extra(
            select={'day': 'date(payments_paymenttransaction.created_at)'}
        ).values('day').annotate(
            count=Count('id'),
            cusd_count=Count('id', filter=Q(token_type='CUSD')),
            confio_count=Count('id', filter=Q(token_type='CONFIO'))
        ).order_by('day')
        
        context['daily_payments'] = list(daily_payments)
        
        # Transaction types breakdown
        transaction_types = {
            'P2P Trades': P2PTrade.objects.filter(
                created_at__gte=start_date,
                status__in=['COMPLETED', 'CRYPTO_RELEASED']
            ).count(),
            'Direct Sends': SendTransaction.objects.filter(
                created_at__gte=start_date
            ).exclude(status='FAILED').count(),
            'Merchant Payments': PaymentTransaction.objects.filter(
                created_at__gte=start_date
            ).exclude(status='FAILED').count(),
        }
        
        context['transaction_types'] = transaction_types
        
        # Success rates
        send_total = SendTransaction.objects.filter(created_at__gte=start_date).count()
        send_success = SendTransaction.objects.filter(
            created_at__gte=start_date,
            status='CONFIRMED'
        ).count()
        
        payment_total = PaymentTransaction.objects.filter(created_at__gte=start_date).count()
        payment_success = PaymentTransaction.objects.filter(
            created_at__gte=start_date,
            status='CONFIRMED'
        ).count()
        
        context['send_success_rate'] = (send_success / send_total * 100) if send_total > 0 else 0
        context['payment_success_rate'] = (payment_success / payment_total * 100) if payment_total > 0 else 0
        
        return render(request, 'admin/transaction_analytics.html', context)
    
    def achievement_dashboard_view(self, request):
        """Achievement system dashboard - delegate to the dedicated view"""
        from achievements.admin_views import achievement_dashboard as dashboard_func
        return dashboard_func(request)
    
    def blockchain_analytics_view(self, request):
        """Blockchain integration analytics (event/log tracking removed)"""
        from blockchain.models import Balance, IndexerAssetCursor, ProcessedIndexerTransaction
        
        context = dict(
            self.each_context(request),
            title="Blockchain Analytics",
        )
        
        # Get date range from request
        days = int(request.GET.get('days', 30))
        start_date = timezone.now() - timedelta(days=days)
        
        # Balance cache metrics
        context['total_cached_balances'] = Balance.objects.count()
        context['stale_balances'] = Balance.objects.filter(is_stale=True).count()
        context['recently_synced'] = Balance.objects.filter(
            last_synced__gte=timezone.now() - timedelta(hours=1)
        ).count()
        
        # Token distribution
        token_balances = Balance.objects.values('token').annotate(
            count=Count('id'),
            total_amount=Sum('amount'),
            avg_amount=Avg('amount')
        ).order_by('token')
        
        context['token_balances'] = token_balances

        # Processing performance removed — no TransactionProcessingLog

        # Balance freshness distribution
        now = timezone.now()
        freshness_ranges = [
            ('< 5 min', timedelta(minutes=5)),
            ('< 30 min', timedelta(minutes=30)),
            ('< 1 hour', timedelta(hours=1)),
            ('< 6 hours', timedelta(hours=6)),
            ('< 24 hours', timedelta(hours=24)),
            ('> 24 hours', None),
        ]
        
        freshness_stats = []
        for label, delta in freshness_ranges:
            if delta:
                count = Balance.objects.filter(
                    last_synced__gte=now - delta
                ).count()
            else:
                count = Balance.objects.filter(
                    last_synced__lt=now - timedelta(hours=24)
                ).count()
            
            freshness_stats.append({
                'label': label,
                'count': count,
                'percentage': (count / context['total_cached_balances'] * 100) if context['total_cached_balances'] > 0 else 0
            })
        
        context['freshness_stats'] = freshness_stats
        
        # Network health check
        from django.conf import settings
        context['network'] = getattr(settings, 'ALGORAND_NETWORK', 'Unknown')
        context['algod_url'] = getattr(settings, 'ALGORAND_ALGOD_ADDRESS', 'Not configured')
        context['indexer_url'] = getattr(settings, 'ALGORAND_INDEXER_ADDRESS', 'Not configured')
        # Try to fetch live health from Algod and Indexer
        algod_health = {'ok': False}
        indexer_health = {'ok': False}
        try:
            from algosdk.v2client import indexer as _indexer
            from blockchain.algorand_client import get_algod_client
            algod_client = get_algod_client()
            status = algod_client.status()
            algod_health = {
                'ok': True,
                'last_round': status.get('last-round'),
                'catchup_time': status.get('catchup-time')
            }
        except Exception:
            pass
        try:
            from blockchain.algorand_client import get_indexer_client
            idx_client = get_indexer_client()
            h = idx_client.health()
            indexer_health = {'ok': True, 'round': h.get('round')}
        except Exception:
            pass
        context['algod_health'] = algod_health
        context['indexer_health'] = indexer_health
        current_round = (indexer_health.get('round') if isinstance(indexer_health, dict) else None) or (
            algod_health.get('last_round') if isinstance(algod_health, dict) else None
        ) or 0
        context['current_round'] = current_round
        
        # Recent blockchain events removed — no RawBlockchainEvent model

        # Indexer cursor status (per asset)
        from django.conf import settings as _settings
        assets = []
        asset_map = [
            ('USDC', getattr(_settings, 'ALGORAND_USDC_ASSET_ID', None)),
            ('cUSD', getattr(_settings, 'ALGORAND_CUSD_ASSET_ID', None)),
            ('CONFIO', getattr(_settings, 'ALGORAND_CONFIO_ASSET_ID', None)),
        ]
        for name, asset_id in asset_map:
            if not asset_id:
                continue
            cursor = IndexerAssetCursor.objects.filter(asset_id=asset_id).first()
            assets.append({
                'token': name,
                'asset_id': asset_id,
                'last_scanned_round': getattr(cursor, 'last_scanned_round', 0),
                'lag': max(0, current_round - (getattr(cursor, 'last_scanned_round', 0) or 0)),
                'updated_at': getattr(cursor, 'updated_at', None),
            })
        context['indexer_cursors'] = assets

        # Recent processed inbound markers count
        context['processed_markers_recent'] = ProcessedIndexerTransaction.objects.filter(
            created_at__gte=start_date
        ).count()
        context['recent_processed'] = ProcessedIndexerTransaction.objects.order_by('-created_at')[:20]
        
        return render(request, 'admin/blockchain_analytics.html', context)

    def blockchain_scan_now_view(self, request):
        """Trigger an immediate indexer scan via Celery (and update address cache)."""
        from blockchain.tasks import update_address_cache, scan_inbound_deposits
        if request.method == 'POST':
            try:
                update_address_cache.delay()
                scan_inbound_deposits.delay()
                messages.success(request, 'Scan triggered. Check back in a moment for updated rounds.')
            except Exception:
                # As a fallback, attempt synchronous execution (may take time)
                try:
                    update_address_cache()
                    scan_inbound_deposits()
                    messages.warning(request, 'Celery unavailable; ran scan synchronously.')
                except Exception as e:
                    messages.error(request, f'Failed to trigger scan: {e}')
        return redirect('admin:blockchain_analytics')


# Create custom admin site instance
confio_admin_site = ConfioAdminSite(name='confio_admin')

# Re-register all models with the custom admin site
from django.contrib.auth.models import Group
from users.admin import (
    UserAdmin, AccountAdmin, BusinessAdmin, CountryAdmin, BankAdmin, 
    BankInfoAdmin, UnifiedTransactionAdmin, BusinessEmployeeAdmin, 
    EmployeeInvitationAdmin, WalletPepperAdmin, WalletDerivationPepperAdmin
)
from security.admin import IdentityVerificationAdmin, SuspiciousActivityAdmin
from p2p_exchange.admin import (
    P2PPaymentMethodAdmin, P2POfferAdmin, P2PTradeAdmin, 
    P2PMessageAdmin, P2PUserStatsAdmin, P2PEscrowAdmin,
    P2PTradeRatingAdmin, P2PDisputeAdmin, P2PDisputeTransactionAdmin, P2PDisputeEvidenceAdmin,
    P2PFavoriteTraderAdmin, PremiumUpgradeRequestAdmin
)
from payments.admin import PaymentTransactionAdmin, InvoiceAdmin
from send.admin import SendTransactionAdmin, PhoneInviteAdmin
from conversion.admin import ConversionAdmin
from payroll.admin import PayrollRunAdmin, PayrollItemAdmin, PayrollRecipientAdmin
from payroll.models import PayrollRun, PayrollItem, PayrollRecipient

# Register with custom admin site
confio_admin_site.register(Group)
confio_admin_site.register(User, UserAdmin)
confio_admin_site.register(Account, AccountAdmin)
confio_admin_site.register(Business, BusinessAdmin)
# Security models
confio_admin_site.register(IdentityVerification, IdentityVerificationAdmin)
from security.models import SuspiciousActivity, UserBan, IPAddress, UserSession, DeviceFingerprint, UserDevice, AMLCheck, IntegrityVerdict
from security.admin import UserBanAdmin, IPAddressAdmin, UserSessionAdmin, DeviceFingerprintAdmin, UserDeviceAdmin, AMLCheckAdmin, IntegrityVerdictAdmin
confio_admin_site.register(SuspiciousActivity, SuspiciousActivityAdmin)
confio_admin_site.register(UserBan, UserBanAdmin)
confio_admin_site.register(IPAddress, IPAddressAdmin)
confio_admin_site.register(UserSession, UserSessionAdmin)
confio_admin_site.register(DeviceFingerprint, DeviceFingerprintAdmin)
confio_admin_site.register(UserDevice, UserDeviceAdmin)
confio_admin_site.register(AMLCheck, AMLCheckAdmin)
confio_admin_site.register(IntegrityVerdict, IntegrityVerdictAdmin)
confio_admin_site.register(Country, CountryAdmin)
confio_admin_site.register(Bank, BankAdmin)
confio_admin_site.register(BankInfo, BankInfoAdmin)
confio_admin_site.register(WalletPepper, WalletPepperAdmin)
confio_admin_site.register(WalletDerivationPepper, WalletDerivationPepperAdmin)

# Payroll
confio_admin_site.register(PayrollRun, PayrollRunAdmin)
confio_admin_site.register(PayrollItem, PayrollItemAdmin)
confio_admin_site.register(PayrollRecipient, PayrollRecipientAdmin)

# Employee models
from users.models_employee import BusinessEmployee, EmployeeInvitation
confio_admin_site.register(BusinessEmployee, BusinessEmployeeAdmin)
confio_admin_site.register(EmployeeInvitation, EmployeeInvitationAdmin)

# CONFIO Reward models
from achievements.models import (
    ConfioRewardBalance,
    ConfioRewardTransaction,
    AchievementType,
    UserAchievement,
    UserReferral,
    ReferralWithdrawalLog,
    TikTokViralShare,
    ConfioGrowthMetric,
)
# Achievement models are now registered below

# Achievement models
from achievements.admin import (
    RewardProgramAdmin,
    UserRewardAdmin,
    UserReferralAdmin,
    ReferralRewardEventAdmin,
    SocialReferralShareAdmin,
    RewardWalletAdmin,
    RewardLedgerEntryAdmin,
    ReferralWithdrawalLogAdmin,
    ConfioGrowthMetricAdmin,
)
confio_admin_site.register(ConfioRewardBalance, RewardWalletAdmin)
confio_admin_site.register(ConfioRewardTransaction, RewardLedgerEntryAdmin)
confio_admin_site.register(AchievementType, RewardProgramAdmin)
confio_admin_site.register(UserAchievement, UserRewardAdmin)
confio_admin_site.register(UserReferral, UserReferralAdmin)
confio_admin_site.register(ReferralRewardEvent, ReferralRewardEventAdmin)
confio_admin_site.register(ReferralWithdrawalLog, ReferralWithdrawalLogAdmin)
confio_admin_site.register(TikTokViralShare, SocialReferralShareAdmin)
confio_admin_site.register(ConfioGrowthMetric, ConfioGrowthMetricAdmin)

# Ambassador models
from achievements.models import InfluencerAmbassador, AmbassadorActivity, PioneroBetaTracker
from achievements.admin import ReferralAmbassadorAdmin, ReferralAmbassadorActivityAdmin, PioneroBetaTrackerAdmin
confio_admin_site.register(InfluencerAmbassador, ReferralAmbassadorAdmin)
confio_admin_site.register(AmbassadorActivity, ReferralAmbassadorActivityAdmin)
confio_admin_site.register(PioneroBetaTracker, PioneroBetaTrackerAdmin)

# Unified Transaction Tables
from users.models_unified import UnifiedTransactionTable
from usdc_transactions.models_unified import UnifiedUSDCTransactionTable
from usdc_transactions.admin import UnifiedUSDCTransactionAdmin
confio_admin_site.register(UnifiedTransactionTable, UnifiedTransactionAdmin)
confio_admin_site.register(UnifiedUSDCTransactionTable, UnifiedUSDCTransactionAdmin)

# Analytics models
from users.models_analytics import DailyMetrics, CountryMetrics
from users.admin_analytics import DailyMetricsAdmin, CountryMetricsAdmin
confio_admin_site.register(DailyMetrics, DailyMetricsAdmin)
confio_admin_site.register(CountryMetrics, CountryMetricsAdmin)

# P2P models
from p2p_exchange.models import (
    P2PPaymentMethod, P2POffer, P2PTrade, P2PMessage, 
    P2PUserStats, P2PEscrow, P2PTradeRating, P2PDispute, P2PDisputeEvidence,
    P2PDisputeTransaction, P2PFavoriteTrader, PremiumUpgradeRequest
)
confio_admin_site.register(P2PPaymentMethod, P2PPaymentMethodAdmin)
confio_admin_site.register(P2POffer, P2POfferAdmin)
confio_admin_site.register(P2PTrade, P2PTradeAdmin)
confio_admin_site.register(P2PMessage, P2PMessageAdmin)
confio_admin_site.register(P2PUserStats, P2PUserStatsAdmin)
confio_admin_site.register(P2PEscrow, P2PEscrowAdmin)
confio_admin_site.register(P2PTradeRating, P2PTradeRatingAdmin)
confio_admin_site.register(P2PDispute, P2PDisputeAdmin)
confio_admin_site.register(P2PDisputeTransaction, P2PDisputeTransactionAdmin)
confio_admin_site.register(P2PDisputeEvidence, P2PDisputeEvidenceAdmin)
confio_admin_site.register(P2PFavoriteTrader, P2PFavoriteTraderAdmin)
confio_admin_site.register(PremiumUpgradeRequest, PremiumUpgradeRequestAdmin)

# Payment models
from payments.models import Invoice, PaymentTransaction
confio_admin_site.register(Invoice, InvoiceAdmin)
confio_admin_site.register(PaymentTransaction, PaymentTransactionAdmin)

# Send models
from send.models import SendTransaction, PhoneInvite
confio_admin_site.register(SendTransaction, SendTransactionAdmin)
confio_admin_site.register(PhoneInvite, PhoneInviteAdmin)

# Conversion models
from conversion.models import Conversion
confio_admin_site.register(Conversion, ConversionAdmin)

# Exchange rate models
from exchange_rates.models import ExchangeRate, RateFetchLog
from exchange_rates.admin import ExchangeRateAdmin, RateFetchLogAdmin
confio_admin_site.register(ExchangeRate, ExchangeRateAdmin)
confio_admin_site.register(RateFetchLog, RateFetchLogAdmin)

# USDC Transaction models
from usdc_transactions.models import USDCDeposit, USDCWithdrawal, GuardarianTransaction
from usdc_transactions.admin import USDCDepositAdmin, USDCWithdrawalAdmin, GuardarianTransactionAdmin
confio_admin_site.register(USDCDeposit, USDCDepositAdmin)
confio_admin_site.register(USDCWithdrawal, USDCWithdrawalAdmin)
confio_admin_site.register(GuardarianTransaction, GuardarianTransactionAdmin)

# Presale models
from presale.models import PresalePhase, PresalePurchase, PresaleStats, UserPresaleLimit, PresaleSettings, PresaleWaitlist
from presale.admin import PresalePhaseAdmin, PresalePurchaseAdmin, PresaleStatsAdmin, UserPresaleLimitAdmin, PresaleSettingsAdmin, PresaleWaitlistAdmin
confio_admin_site.register(PresaleSettings, PresaleSettingsAdmin)
confio_admin_site.register(PresalePhase, PresalePhaseAdmin)
confio_admin_site.register(PresalePurchase, PresalePurchaseAdmin)
confio_admin_site.register(PresaleStats, PresaleStatsAdmin)
confio_admin_site.register(UserPresaleLimit, UserPresaleLimitAdmin)
confio_admin_site.register(PresaleWaitlist, PresaleWaitlistAdmin)

# Notification models
from notifications.models import Notification, NotificationPreference, FCMDeviceToken
from notifications.admin import NotificationAdmin, NotificationPreferenceAdmin, FCMDeviceTokenAdmin
confio_admin_site.register(Notification, NotificationAdmin)
confio_admin_site.register(NotificationPreference, NotificationPreferenceAdmin)
confio_admin_site.register(FCMDeviceToken, FCMDeviceTokenAdmin)

# Blockchain models (events and processing logs removed); add indexer cursor + processed markers
from blockchain.models import Balance, ProcessedIndexerTransaction, IndexerAssetCursor
from blockchain.admin import BalanceAdmin, ProcessedIndexerTransactionAdmin, IndexerAssetCursorAdmin
confio_admin_site.register(Balance, BalanceAdmin)
confio_admin_site.register(ProcessedIndexerTransaction, ProcessedIndexerTransactionAdmin)
confio_admin_site.register(IndexerAssetCursor, IndexerAssetCursorAdmin)

# SMS Verification
from sms_verification.models import SMSVerification
from sms_verification.admin import SMSVerificationAdmin
confio_admin_site.register(SMSVerification, SMSVerificationAdmin)

# Telegram Verification
from telegram_verification.models import TelegramVerification
from telegram_verification.admin import TelegramVerificationAdmin
confio_admin_site.register(TelegramVerification, TelegramVerificationAdmin)
