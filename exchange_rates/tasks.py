from celery import shared_task
from celery.utils.log import get_task_logger
from .services import exchange_rate_service
from functools import wraps
from django.db import connection

logger = get_task_logger(__name__)


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


@shared_task(bind=True, max_retries=3)
@ensure_db_connection_closed
def fetch_exchange_rates(self):
    """
    Celery task to fetch exchange rates from all sources
    Runs periodically to keep rates up to date
    """
    try:
        logger.info("Starting exchange rate fetch task")
        
        results = exchange_rate_service.fetch_all_rates()
        
        # Count successful sources
        successful_sources = sum(1 for success in results.values() if success)
        total_sources = len(results)
        
        logger.info(f"Exchange rate fetch completed: {successful_sources}/{total_sources} sources successful")
        
        # If no sources were successful, retry
        if successful_sources == 0:
            logger.warning("No exchange rate sources were successful, retrying...")
            raise Exception("All exchange rate sources failed")
        
        return {
            'success': True,
            'sources': results,
            'successful_sources': successful_sources,
            'total_sources': total_sources
        }
        
    except Exception as exc:
        logger.error(f"Exchange rate fetch failed: {exc}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 2 ** self.request.retries * 60  # 1min, 2min, 4min
            logger.info(f"Retrying in {retry_delay} seconds...")
            raise self.retry(exc=exc, countdown=retry_delay)
        
        # Max retries reached
        logger.error("Max retries reached for exchange rate fetch")
        return {
            'success': False,
            'error': str(exc),
            'retries': self.request.retries
        }


@shared_task
@ensure_db_connection_closed
def fetch_dolartoday_rates():
    """
    Task to fetch only DolarToday rates (most reliable for VES)
    """
    logger.info("Fetching DolarToday rates")
    success = exchange_rate_service.fetch_dolartoday_rates()
    
    return {
        'success': success,
        'source': 'dolartoday'
    }


@shared_task
@ensure_db_connection_closed
def cleanup_old_rates():
    """
    Task to clean up old exchange rate records
    Keeps last 7 days of data for analysis
    """
    from django.utils import timezone
    from datetime import timedelta
    from .models import ExchangeRate, RateFetchLog
    
    # Delete rates older than 7 days
    cutoff_date = timezone.now() - timedelta(days=7)
    
    deleted_rates = ExchangeRate.objects.filter(
        fetched_at__lt=cutoff_date
    ).delete()
    
    # Delete logs older than 30 days
    log_cutoff_date = timezone.now() - timedelta(days=30)
    deleted_logs = RateFetchLog.objects.filter(
        created_at__lt=log_cutoff_date
    ).delete()
    
    logger.info(f"Cleanup completed: {deleted_rates[0]} rates, {deleted_logs[0]} logs deleted")
    
    return {
        'deleted_rates': deleted_rates[0],
        'deleted_logs': deleted_logs[0]
    }

@shared_task(name='exchange_rates.snapshot_daily_rates')
@ensure_db_connection_closed
def snapshot_daily_rates():
    """Keep one Binance P2P rate per currency per UTC day (ExchangeRate rows
    are purged after 7 days). Tu mes compares the 1st of the month with today
    in countries without a Confío on-ramp. Runs hourly and is idempotent: the
    first run of the day that finds a fresh rate writes it."""
    from datetime import timedelta
    from django.db import IntegrityError
    from django.utils import timezone
    from .models import DailyRateSnapshot, ExchangeRate

    today = timezone.now().date()
    written = []
    for currency in ('VES', 'ARS', 'BOB'):
        if DailyRateSnapshot.objects.filter(date=today, currency=currency, source='binance_p2p').exists():
            continue
        row = (ExchangeRate.objects.filter(source_currency=currency, target_currency='USD', source='binance_p2p',
                                           is_active=True, fetched_at__gte=timezone.now() - timedelta(hours=2))
               .order_by('-fetched_at').first())
        if row is None or row.rate <= 0:
            continue                       # no fresh rate: the next hourly run tries again
        try:
            DailyRateSnapshot.objects.create(date=today, currency=currency, source='binance_p2p',
                                             rate=row.rate, fetched_at=row.fetched_at)
            written.append(currency)
        except IntegrityError:
            pass                           # another worker wrote it first
    return ','.join(written) or 'none'
