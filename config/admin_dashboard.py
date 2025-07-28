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

from users.models import User, Account, Business, IdentityVerification, Country, Bank, BankInfo
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
            path('dashboard/', self.admin_view(self.dashboard_view), name='dashboard'),
            path('p2p-analytics/', self.admin_view(self.p2p_analytics_view), name='p2p_analytics'),
            path('user-analytics/', self.admin_view(self.user_analytics_view), name='user_analytics'),
            path('transaction-analytics/', self.admin_view(self.transaction_analytics_view), name='transaction_analytics'),
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
        
        # Recent activities
        context['recent_trades'] = P2PTrade.objects.select_related(
            'buyer_user', 'seller_user', 'offer'
        ).order_by('-created_at')[:10]
        
        context['recent_disputes'] = P2PDispute.objects.select_related(
            'trade', 'initiator_user'
        ).order_by('-opened_at')[:5]
        
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


# Create custom admin site instance
confio_admin_site = ConfioAdminSite(name='confio_admin')

# Re-register all models with the custom admin site
from django.contrib.auth.models import Group
from users.admin import UserAdmin, AccountAdmin, BusinessAdmin, IdentityVerificationAdmin, CountryAdmin, BankAdmin, BankInfoAdmin, UnifiedTransactionAdmin, BusinessEmployeeAdmin, EmployeeInvitationAdmin
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
confio_admin_site.register(IdentityVerification, IdentityVerificationAdmin)
confio_admin_site.register(Country, CountryAdmin)
confio_admin_site.register(Bank, BankAdmin)
confio_admin_site.register(BankInfo, BankInfoAdmin)

# Employee models
from users.models_employee import BusinessEmployee, EmployeeInvitation
confio_admin_site.register(BusinessEmployee, BusinessEmployeeAdmin)
confio_admin_site.register(EmployeeInvitation, EmployeeInvitationAdmin)

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