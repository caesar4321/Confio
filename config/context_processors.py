from django.db.models import Count, Sum, Q
from django.utils import timezone
from datetime import timedelta
from users.models import User
from achievements.models import UserAchievement
from p2p_exchange.models import P2PTrade


def admin_dashboard_stats(request):
    """Add dashboard statistics to admin context"""
    # Only compute stats for admin pages
    if not request.path.startswith('/admin/'):
        return {}
    
    # Only for authenticated staff users
    if not (request.user.is_authenticated and request.user.is_staff):
        return {}
    
    
    try:
        # Fraud Statistics
        total_achievements = UserAchievement.objects.count()
        fraud_detected = UserAchievement.objects.filter(
            security_metadata__fraud_detected__isnull=False
        ).count()
        suspicious_activity = UserAchievement.objects.filter(
            security_metadata__suspicious_ip=True
        ).count()
        
        # Count unique devices with multiple users
        from collections import defaultdict
        device_stats = defaultdict(set)
        
        achievements_with_device = UserAchievement.objects.filter(
            device_fingerprint_hash__isnull=False
        ).values('device_fingerprint_hash', 'user_id')
        
        for achievement in achievements_with_device:
            device_stats[achievement['device_fingerprint_hash']].add(achievement['user_id'])
        
        multi_user_devices = sum(1 for users in device_stats.values() if len(users) > 1)
        
        # Calculate potential fraud loss
        potential_loss = UserAchievement.objects.filter(
            security_metadata__fraud_detected__isnull=False,
            status='claimed'
        ).aggregate(
            total=Sum('achievement_type__confio_reward')
        )['total'] or 0
        
        fraud_stats = {
            'total_achievements': total_achievements,
            'fraud_detected': fraud_detected,
            'fraud_percentage': (fraud_detected / total_achievements * 100) if total_achievements > 0 else 0,
            'suspicious_activity': suspicious_activity,
            'multi_user_devices': multi_user_devices,
            'potential_loss': potential_loss,
            'potential_loss_usd': float(potential_loss) / 4,  # 4 CONFIO = $1
        }
        
        # User Statistics
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)
        
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
        
        return {
            'fraud_stats': fraud_stats,
            'user_stats': user_stats,
            'p2p_stats': p2p_stats,
        }
    except Exception as e:
        # Don't break the admin if stats fail
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error computing admin dashboard stats: {e}")
        return {}