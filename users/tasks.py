"""
Celery tasks for user achievements and scheduled checks
"""
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from django.core.management import call_command
import logging

logger = logging.getLogger(__name__)


@shared_task(name='users.check_hodler_achievements')
def check_hodler_achievements():
    """
    Daily task to check and award Hodler achievements
    
    This task should be scheduled to run daily at midnight UTC:
    
    In your celery beat schedule:
    
    CELERY_BEAT_SCHEDULE = {
        'check-hodler-achievements': {
            'task': 'users.check_hodler_achievements',
            'schedule': crontab(hour=0, minute=0),  # Run at midnight UTC
        },
    }
    """
    try:
        logger.info("Starting Hodler achievement check...")
        call_command('check_hodler_achievements')
        logger.info("Hodler achievement check completed successfully")
        return "Success"
    except Exception as e:
        logger.error(f"Error in Hodler achievement check: {str(e)}")
        raise


@shared_task(name='users.cleanup_expired_referrals')
def cleanup_expired_referrals():
    """
    Clean up expired referral windows (users who didn't complete first transaction)
    
    This task should run weekly to update referral statuses:
    
    CELERY_BEAT_SCHEDULE = {
        'cleanup-expired-referrals': {
            'task': 'users.cleanup_expired_referrals',
            'schedule': crontab(hour=1, minute=0, day_of_week=1),  # Monday 1 AM UTC
        },
    }
    """
    from users.models import InfluencerReferral
    
    try:
        # Find referrals that are still pending after 30 days
        cutoff_date = timezone.now() - timedelta(days=30)
        
        expired_referrals = InfluencerReferral.objects.filter(
            status='pending',
            created_at__lte=cutoff_date
        )
        
        count = expired_referrals.count()
        
        # Update to expired status
        expired_referrals.update(status='expired')
        
        logger.info(f"Marked {count} referrals as expired")
        return f"Expired {count} referrals"
        
    except Exception as e:
        logger.error(f"Error cleaning up expired referrals: {str(e)}")
        raise


@shared_task(name='users.achievement_stats_report')
def achievement_stats_report():
    """
    Generate weekly achievement statistics report
    
    CELERY_BEAT_SCHEDULE = {
        'achievement-stats-report': {
            'task': 'users.achievement_stats_report',
            'schedule': crontab(hour=9, minute=0, day_of_week=1),  # Monday 9 AM UTC
        },
    }
    """
    from users.models import AchievementType, UserAchievement
    from django.db.models import Count, Q
    
    try:
        stats = {}
        
        # Get stats for each active achievement
        for achievement in AchievementType.objects.filter(is_active=True):
            earned_count = UserAchievement.objects.filter(
                achievement_type=achievement,
                status='earned'
            ).count()
            
            claimed_count = UserAchievement.objects.filter(
                achievement_type=achievement,
                status='claimed'
            ).count()
            
            stats[achievement.slug] = {
                'name': achievement.name,
                'total_earned': earned_count,
                'total_claimed': claimed_count,
                'unclaimed': earned_count,
                'confio_reward': float(achievement.confio_reward),
                'total_confio_distributed': float(achievement.confio_reward * claimed_count)
            }
        
        # Special check for Pionero Beta limit
        pionero_count = UserAchievement.objects.filter(
            achievement_type__slug='pionero_beta'
        ).count()
        
        stats['pionero_beta']['remaining_slots'] = max(0, 10000 - pionero_count)
        
        logger.info(f"Achievement stats generated: {stats}")
        return stats
        
    except Exception as e:
        logger.error(f"Error generating achievement stats: {str(e)}")
        raise