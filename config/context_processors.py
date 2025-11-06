from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Sum, Q
from django.utils import timezone

from users.models import User
from achievements.models import (
    UserAchievement,
    ReferralWithdrawalLog,
    ConfioRewardTransaction,
)
from p2p_exchange.models import P2PTrade
from presale.models import PresalePurchase, PresalePhase
from security.models import DeviceFingerprint
from blockchain.mutations import REFERRAL_ACHIEVEMENT_SLUGS


def admin_dashboard_stats(request):
    """Add dashboard statistics to admin context"""
    # Only compute stats for admin pages
    if not request.path.startswith('/admin/'):
        return {}
    
    # Only for authenticated staff users
    if not (request.user.is_authenticated and request.user.is_staff):
        return {}
    
    
    try:
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)

        # Referral reward statistics
        referral_logs = ReferralWithdrawalLog.objects.all()
        referral_daily = referral_logs.filter(created_at__gte=now - timedelta(days=1))
        referral_weekly = referral_logs.filter(created_at__gte=week_start)

        total_withdrawn = referral_logs.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        daily_withdrawn = referral_daily.aggregate(total=Sum('amount'))['total'] or Decimal('0')
        weekly_withdrawn = referral_weekly.aggregate(total=Sum('amount'))['total'] or Decimal('0')
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

        # Multi-user device detection (legacy achievements still informative for abuse)
        multi_user_devices = DeviceFingerprint.objects.annotate(
            user_count=Count(
                'users',
                filter=Q(users__achievements__achievement_type__slug__in=REFERRAL_ACHIEVEMENT_SLUGS),
                distinct=True,
            )
        ).filter(user_count__gt=1).count()

        fraud_stats = {
            'earned_total': referral_earned_total,
            'total_withdrawn': total_withdrawn,
            'available_total': referral_available,
            'daily_withdrawn': daily_withdrawn,
            'weekly_withdrawn': weekly_withdrawn,
            'pending_review': pending_review,
            'high_value': high_value,
            'unique_users': unique_referral_users,
            'multi_user_devices': multi_user_devices,
        }
        
        # User Statistics
        user_stats = {
            'total_users': User.objects.filter(is_active=True).count(),
            'new_users_today': User.objects.filter(date_joined__gte=today_start).count(),
            'new_users_week': User.objects.filter(date_joined__gte=week_start).count(),
            'verified_phones': User.objects.filter(
                phone_number__isnull=False,
                phone_country__isnull=False
            ).exclude(phone_number='').count(),
        }
        
        # P2P Statistics
        p2p_stats = {
            'total_trades': P2PTrade.objects.filter(deleted_at__isnull=True).count(),
            'completed_trades': P2PTrade.objects.filter(
                status='COMPLETED',
                deleted_at__isnull=True
            ).count(),
            'pending_trades': P2PTrade.objects.filter(
                status__in=['PENDING', 'PAYMENT_PENDING', 'PAYMENT_SENT'],
                deleted_at__isnull=True
            ).count(),
            'total_volume': P2PTrade.objects.filter(
                status='COMPLETED',
                deleted_at__isnull=True
            ).aggregate(
                total=Sum('crypto_amount')  # Sum crypto amount (cUSD)
            )['total'] or 0,
        }
        
        # Presale Statistics
        presale_completed = PresalePurchase.objects.filter(status='completed')
        presale_stats = {
            'active_phase': PresalePhase.objects.filter(status='active').values('phase_number', 'name').first(),
            'today_purchases': presale_completed.filter(created_at__gte=today_start).count(),
            'week_purchases': presale_completed.filter(created_at__gte=week_start).count(),
            'today_cusd': presale_completed.filter(created_at__gte=today_start).aggregate(total=Sum('cusd_amount'))['total'] or 0,
            'week_cusd': presale_completed.filter(created_at__gte=week_start).aggregate(total=Sum('cusd_amount'))['total'] or 0,
            'total_confio': presale_completed.aggregate(total=Sum('confio_amount'))['total'] or 0,
        }

        return {
            'fraud_stats': fraud_stats,
            'user_stats': user_stats,
            'p2p_stats': p2p_stats,
            'presale_stats': presale_stats,
        }
    except Exception as e:
        # Don't break the admin if stats fail
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error computing admin dashboard stats: {e}")
        return {}
