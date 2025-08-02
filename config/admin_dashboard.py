"""
Custom Admin Dashboard for Confío
Provides a comprehensive overview of platform metrics and quick actions
"""
from django.contrib import admin
from django.urls import path
from django.shortcuts import render
from django.utils import timezone
from django.db.models import Count, Sum, Q, F, Avg
from django.db.models.functions import Cast
from django.db.models import DecimalField
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.html import format_html
from datetime import datetime, timedelta
from decimal import Decimal

from users.models import User, Account, Business, Country, Bank, BankInfo
from security.models import IdentityVerification
from achievements.admin_views import achievement_dashboard
from achievements.models import UserAchievement
from p2p_exchange.models import P2POffer, P2PTrade, P2PUserStats, P2PDispute
from send.models import SendTransaction
from payments.models import PaymentTransaction


class ConfioAdminSite(admin.AdminSite):
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
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)
        
        # User metrics
        context['total_users'] = User.objects.count()
        context['active_users_today'] = User.objects.filter(last_login__gte=today_start).count()
        context['new_users_this_week'] = User.objects.filter(created_at__gte=week_start).count()
        context['verified_users'] = IdentityVerification.objects.filter(status='verified').count()
        
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
        
        # Fraud Detection Statistics
        total_achievements = UserAchievement.objects.count()
        fraud_detected = UserAchievement.objects.filter(
            security_metadata__fraud_detected__isnull=False
        ).count()
        suspicious_activity = UserAchievement.objects.filter(
            security_metadata__suspicious_ip=True
        ).count()
        
        # Count unique devices with multiple users from DeviceFingerprint model
        from security.models import DeviceFingerprint
        from django.db.models import Count
        
        # Count devices that have more than one user
        multi_user_devices = DeviceFingerprint.objects.annotate(
            user_count=Count('users', distinct=True)
        ).filter(user_count__gt=1).count()
        
        # Also get total unique devices tracked
        total_devices_tracked = DeviceFingerprint.objects.count()
        
        # Calculate potential fraud loss
        potential_loss = UserAchievement.objects.filter(
            security_metadata__fraud_detected__isnull=False,
            status='claimed'
        ).aggregate(
            total=Sum('achievement_type__confio_reward')
        )['total'] or 0
        
        context['fraud_stats'] = {
            'total_achievements': total_achievements,
            'fraud_detected': fraud_detected,
            'fraud_percentage': (fraud_detected / total_achievements * 100) if total_achievements > 0 else 0,
            'suspicious_activity': suspicious_activity,
            'multi_user_devices': multi_user_devices,
            'total_devices_tracked': total_devices_tracked,
            'potential_loss': potential_loss,
            'potential_loss_usd': float(potential_loss) / 4,  # 4 CONFIO = $1
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
        context['conversions_this_week'] = Conversion.objects.filter(
            created_at__gte=week_start
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
        
        # Blockchain metrics
        from blockchain.models import RawBlockchainEvent, Balance, TransactionProcessingLog
        context['blockchain_events_today'] = RawBlockchainEvent.objects.filter(
            created_at__gte=today_start
        ).count()
        context['blockchain_events_unprocessed'] = RawBlockchainEvent.objects.filter(
            processed=False
        ).count()
        context['cached_balances'] = Balance.objects.count()
        context['stale_balances'] = Balance.objects.filter(is_stale=True).count()
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
        
        # Processing success rate
        processing_logs = TransactionProcessingLog.objects.filter(
            created_at__gte=today_start
        )
        total_processed = processing_logs.count()
        failed_processed = processing_logs.filter(status='failed').count()
        context['blockchain_processing_success_rate'] = (
            ((total_processed - failed_processed) / total_processed * 100) 
            if total_processed > 0 else 100
        )
        
        # Recent activities
        context['recent_trades'] = P2PTrade.objects.select_related(
            'buyer_user', 'seller_user', 'offer'
        ).order_by('-created_at')[:10]
        
        context['recent_disputes'] = P2PDispute.objects.select_related(
            'trade', 'initiator_user'
        ).order_by('-opened_at')[:5]
        
        # Presale metrics
        from presale.models import PresalePhase, PresalePurchase, PresaleSettings
        presale_settings = PresaleSettings.get_settings()
        active_presale = PresalePhase.objects.filter(status='active').first() if presale_settings.is_presale_active else None
        print(f"DEBUG: Presale enabled: {presale_settings.is_presale_active}, Active presale: {active_presale}")  # Debug line
        if active_presale and presale_settings.is_presale_active:
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
        days = int(request.GET.get('days', 30))
        start_date = timezone.now() - timedelta(days=days)
        
        daily_signups = User.objects.filter(
            created_at__gte=start_date
        ).extra(
            select={'day': 'date(users_user.created_at)'}
        ).values('day').annotate(
            count=Count('id')
        ).order_by('day')
        
        context['daily_signups'] = list(daily_signups)
        
        # Verification funnel
        context['users_total'] = User.objects.count()
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
        
        # User activity metrics
        active_ranges = [
            ('Last 24h', 1),
            ('Last 7 days', 7),
            ('Last 30 days', 30),
            ('Last 90 days', 90),
        ]
        
        activity_metrics = []
        for label, days in active_ranges:
            cutoff = timezone.now() - timedelta(days=days)
            count = User.objects.filter(last_login__gte=cutoff).count()
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
            cusd_count=Count('id', filter=Q(token_type='cUSD')),
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
        """Blockchain integration analytics"""
        from blockchain.models import RawBlockchainEvent, Balance, TransactionProcessingLog
        
        context = dict(
            self.each_context(request),
            title="Blockchain Analytics",
        )
        
        # Get date range from request
        days = int(request.GET.get('days', 30))
        start_date = timezone.now() - timedelta(days=days)
        
        # Event processing by day
        daily_events = RawBlockchainEvent.objects.filter(
            created_at__gte=start_date
        ).extra(
            select={'day': 'date(blockchain_rawblockchainevent.created_at)'}
        ).values('day').annotate(
            total=Count('id'),
            processed=Count('id', filter=Q(processed=True)),
            unprocessed=Count('id', filter=Q(processed=False))
        ).order_by('day')
        
        context['daily_events'] = list(daily_events)
        
        # Event types breakdown
        event_types = RawBlockchainEvent.objects.filter(
            created_at__gte=start_date
        ).values('module', 'function').annotate(
            count=Count('id')
        ).order_by('-count')[:20]
        
        context['event_types'] = event_types
        
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
        
        # Processing performance
        processing_stats = TransactionProcessingLog.objects.filter(
            created_at__gte=start_date
        ).values('status').annotate(
            count=Count('id'),
            avg_attempts=Avg('attempts')
        ).order_by('status')
        
        context['processing_stats'] = processing_stats
        
        # Recent failed processing
        context['recent_failures'] = TransactionProcessingLog.objects.filter(
            status='failed'
        ).select_related('raw_event').order_by('-updated_at')[:20]
        
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
        context['network'] = settings.NETWORK if hasattr(settings, 'NETWORK') else 'Unknown'
        context['rpc_url'] = settings.SUI_RPC_URL if hasattr(settings, 'SUI_RPC_URL') else 'Not configured'
        
        # Recent blockchain events
        context['recent_events'] = RawBlockchainEvent.objects.order_by('-block_time')[:20]
        
        return render(request, 'admin/blockchain_analytics.html', context)


# Create custom admin site instance
confio_admin_site = ConfioAdminSite(name='confio_admin')

# Re-register all models with the custom admin site
from django.contrib.auth.models import Group
from users.admin import UserAdmin, AccountAdmin, BusinessAdmin, CountryAdmin, BankAdmin, BankInfoAdmin, UnifiedTransactionAdmin, BusinessEmployeeAdmin, EmployeeInvitationAdmin
from security.admin import IdentityVerificationAdmin, SuspiciousActivityAdmin
from p2p_exchange.admin import (
    P2PPaymentMethodAdmin, P2POfferAdmin, P2PTradeAdmin, 
    P2PMessageAdmin, P2PUserStatsAdmin, P2PEscrowAdmin,
    P2PTradeRatingAdmin, P2PDisputeAdmin, P2PDisputeTransactionAdmin,
    P2PFavoriteTraderAdmin
)
from payments.admin import PaymentTransactionAdmin, InvoiceAdmin
from send.admin import SendTransactionAdmin
from conversion.admin import ConversionAdmin

# Register with custom admin site
confio_admin_site.register(Group)
confio_admin_site.register(User, UserAdmin)
confio_admin_site.register(Account, AccountAdmin)
confio_admin_site.register(Business, BusinessAdmin)
# Security models
confio_admin_site.register(IdentityVerification, IdentityVerificationAdmin)
from security.models import SuspiciousActivity, UserBan, IPAddress, UserSession, DeviceFingerprint, UserDevice, AMLCheck
from security.admin import UserBanAdmin, IPAddressAdmin, UserSessionAdmin, DeviceFingerprintAdmin, UserDeviceAdmin, AMLCheckAdmin
confio_admin_site.register(SuspiciousActivity, SuspiciousActivityAdmin)
confio_admin_site.register(UserBan, UserBanAdmin)
confio_admin_site.register(IPAddress, IPAddressAdmin)
confio_admin_site.register(UserSession, UserSessionAdmin)
confio_admin_site.register(DeviceFingerprint, DeviceFingerprintAdmin)
confio_admin_site.register(UserDevice, UserDeviceAdmin)
confio_admin_site.register(AMLCheck, AMLCheckAdmin)
confio_admin_site.register(Country, CountryAdmin)
confio_admin_site.register(Bank, BankAdmin)
confio_admin_site.register(BankInfo, BankInfoAdmin)

# Employee models
from users.models_employee import BusinessEmployee, EmployeeInvitation
confio_admin_site.register(BusinessEmployee, BusinessEmployeeAdmin)
confio_admin_site.register(EmployeeInvitation, EmployeeInvitationAdmin)

# CONFIO Reward models
from achievements.models import ConfioRewardBalance, ConfioRewardTransaction, AchievementType, UserAchievement, InfluencerReferral, TikTokViralShare, ConfioGrowthMetric
# Achievement models are now registered below

# Achievement models
from achievements.admin import AchievementTypeAdmin, UserAchievementAdmin, InfluencerReferralAdmin, TikTokViralShareAdmin, ConfioRewardBalanceAdmin, ConfioRewardTransactionAdmin, ConfioGrowthMetricAdmin
confio_admin_site.register(ConfioRewardBalance, ConfioRewardBalanceAdmin)
confio_admin_site.register(ConfioRewardTransaction, ConfioRewardTransactionAdmin)
confio_admin_site.register(AchievementType, AchievementTypeAdmin)
confio_admin_site.register(UserAchievement, UserAchievementAdmin)
confio_admin_site.register(InfluencerReferral, InfluencerReferralAdmin)
confio_admin_site.register(TikTokViralShare, TikTokViralShareAdmin)
confio_admin_site.register(ConfioGrowthMetric, ConfioGrowthMetricAdmin)

# Ambassador models
from achievements.models import InfluencerAmbassador, AmbassadorActivity, PioneroBetaTracker
from achievements.admin import InfluencerAmbassadorAdmin, AmbassadorActivityAdmin, PioneroBetaTrackerAdmin
confio_admin_site.register(InfluencerAmbassador, InfluencerAmbassadorAdmin)
confio_admin_site.register(AmbassadorActivity, AmbassadorActivityAdmin)
confio_admin_site.register(PioneroBetaTracker, PioneroBetaTrackerAdmin)

# Unified Transaction Tables
from users.models_unified import UnifiedTransactionTable
from usdc_transactions.models_unified import UnifiedUSDCTransactionTable
from usdc_transactions.admin import UnifiedUSDCTransactionAdmin
confio_admin_site.register(UnifiedTransactionTable, UnifiedTransactionAdmin)
confio_admin_site.register(UnifiedUSDCTransactionTable, UnifiedUSDCTransactionAdmin)

# P2P models
from p2p_exchange.models import (
    P2PPaymentMethod, P2POffer, P2PTrade, P2PMessage, 
    P2PUserStats, P2PEscrow, P2PTradeRating, P2PDispute,
    P2PDisputeTransaction, P2PFavoriteTrader
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
confio_admin_site.register(P2PFavoriteTrader, P2PFavoriteTraderAdmin)

# Payment models
from payments.models import Invoice, PaymentTransaction
confio_admin_site.register(Invoice, InvoiceAdmin)
confio_admin_site.register(PaymentTransaction, PaymentTransactionAdmin)

# Send models
from send.models import SendTransaction
confio_admin_site.register(SendTransaction, SendTransactionAdmin)

# Conversion models
from conversion.models import Conversion
confio_admin_site.register(Conversion, ConversionAdmin)

# USDC Transaction models
from usdc_transactions.models import USDCDeposit, USDCWithdrawal
from usdc_transactions.admin import USDCDepositAdmin, USDCWithdrawalAdmin
confio_admin_site.register(USDCDeposit, USDCDepositAdmin)
confio_admin_site.register(USDCWithdrawal, USDCWithdrawalAdmin)

# Presale models
from presale.models import PresalePhase, PresalePurchase, PresaleStats, UserPresaleLimit, PresaleSettings
from presale.admin import PresalePhaseAdmin, PresalePurchaseAdmin, PresaleStatsAdmin, UserPresaleLimitAdmin, PresaleSettingsAdmin
confio_admin_site.register(PresaleSettings, PresaleSettingsAdmin)
confio_admin_site.register(PresalePhase, PresalePhaseAdmin)
confio_admin_site.register(PresalePurchase, PresalePurchaseAdmin)
confio_admin_site.register(PresaleStats, PresaleStatsAdmin)
confio_admin_site.register(UserPresaleLimit, UserPresaleLimitAdmin)

# Notification models
from notifications.models import Notification, NotificationPreference, FCMDeviceToken
from notifications.admin import NotificationAdmin, NotificationPreferenceAdmin, FCMDeviceTokenAdmin
confio_admin_site.register(Notification, NotificationAdmin)
confio_admin_site.register(NotificationPreference, NotificationPreferenceAdmin)
confio_admin_site.register(FCMDeviceToken, FCMDeviceTokenAdmin)

# Blockchain models
from blockchain.models import RawBlockchainEvent, Balance, TransactionProcessingLog, SuiEpoch
from blockchain.admin import RawBlockchainEventAdmin, BalanceAdmin, TransactionProcessingLogAdmin, SuiEpochAdmin
confio_admin_site.register(RawBlockchainEvent, RawBlockchainEventAdmin)
confio_admin_site.register(Balance, BalanceAdmin)
confio_admin_site.register(TransactionProcessingLog, TransactionProcessingLogAdmin)
confio_admin_site.register(SuiEpoch, SuiEpochAdmin)