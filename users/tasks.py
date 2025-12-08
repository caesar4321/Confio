"""
Celery tasks for user achievements and scheduled checks
"""
from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from django.core.management import call_command
import logging
from functools import wraps
from django.db import connection

logger = logging.getLogger(__name__)


def ensure_db_connection_closed(func):
    """Decorator to ensure database connections are properly closed after task execution"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            # Explicitly close database connections to prevent accumulation
            connection.close()
    return wrapper


@shared_task(name='users.check_hodler_achievements')
@ensure_db_connection_closed
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
@ensure_db_connection_closed
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
@ensure_db_connection_closed
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


@shared_task(name='users.capture_daily_metrics')
@ensure_db_connection_closed
def capture_daily_metrics():
    """
    Capture daily DAU/WAU/MAU metrics snapshot
    
    This task should be scheduled to run daily at 3:00 AM UTC:
    
    CELERY_BEAT_SCHEDULE = {
        'capture-daily-metrics': {
            'task': 'users.capture_daily_metrics',
            'schedule': crontab(hour=3, minute=0),  # Daily at 3:00 AM UTC
        },
    }
    
    The task captures metrics for yesterday (the most recently completed day).
    """
    from users.analytics import snapshot_daily_metrics
    from datetime import timedelta
    
    try:
        # Capture metrics for yesterday (most recently completed day)
        target_date = (timezone.now() - timedelta(days=1)).date()
        
        logger.info(f"Starting daily metrics capture for {target_date}")
        snapshot = snapshot_daily_metrics(target_date)
        
        logger.info(
            f"Successfully captured daily metrics for {target_date}: "
            f"DAU={snapshot.dau:,}, WAU={snapshot.wau:,}, MAU={snapshot.mau:,}, "
            f"Total Users={snapshot.total_users:,}, New Users={snapshot.new_users_today:,}"
        )
        
        return {
            'date': str(target_date),
            'dau': snapshot.dau,
            'wau': snapshot.wau,
            'mau': snapshot.mau,
            'total_users': snapshot.total_users,
            'new_users_today': snapshot.new_users_today,
        }
        
    except Exception as e:
        logger.error(f"Error capturing daily metrics: {str(e)}", exc_info=True)
        raise


@shared_task(name='users.capture_country_metrics')
@ensure_db_connection_closed
def capture_country_metrics():
    """
    Capture country-specific DAU/WAU/MAU metrics snapshots
    
    This task should be scheduled to run daily at 3:15 AM UTC:
    
    CELERY_BEAT_SCHEDULE = {
        'capture-country-metrics': {
            'task': 'users.capture_country_metrics',
            'schedule': crontab(hour=3, minute=15),  # Daily at 3:15 AM UTC
        },
    }
    
    The task captures metrics for yesterday (the most recently completed day).
    """
    from users.analytics import snapshot_country_metrics
    from datetime import timedelta
    
    try:
        # Capture metrics for yesterday (most recently completed day)
        target_date = (timezone.now() - timedelta(days=1)).date()
        
        logger.info(f"Starting country metrics capture for {target_date}")
        snapshots = snapshot_country_metrics(target_date)
        
        # Log summary
        country_summary = {}
        for snapshot in snapshots:
            country_summary[snapshot.country_code] = {
                'dau': snapshot.dau,
                'mau': snapshot.mau,
            }
        
        logger.info(
            f"Successfully captured country metrics for {target_date}: "
            f"{len(snapshots)} countries tracked"
        )
        
        return {
            'date': str(target_date),
            'countries_tracked': len(snapshots),
            'summary': country_summary,
        }
        
    except Exception as e:
        logger.error(f"Error capturing country metrics: {str(e)}", exc_info=True)
        raise
