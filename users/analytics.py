"""
Analytics calculation functions for DAU/WAU/MAU metrics

This module provides the core calculation logic for user activity metrics.
All calculations are based on the centralized last_activity_at field in the User model.

Usage:
    from users.analytics import calculate_dau, calculate_wau, calculate_mau
    
    dau = calculate_dau()  # Yesterday's DAU
    wau = calculate_wau()  # Yesterday's WAU
    mau = calculate_mau()  # Yesterday's MAU
"""

from django.utils import timezone
from django.db.models import Count, Q
from datetime import date, timedelta, datetime
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


def calculate_dau(target_date=None):
    """
    Calculate Daily Active Users for a specific date
    
    Args:
        target_date: Date to calculate DAU for (defaults to yesterday)
        
    Returns:
        int: Number of users active in the 24 hours ending at target_date
        
    Example:
        >>> calculate_dau(date(2025, 12, 6))
        2917
    """
    from users.models import User
    
    if target_date is None:
        target_date = (timezone.now() - timedelta(days=1)).date()
    
    # Convert date to datetime range
    end_time = timezone.make_aware(datetime.combine(target_date, datetime.max.time()))
    start_time = end_time - timedelta(days=1)
    
    dau = User.objects.filter(
        last_activity_at__gte=start_time,
        last_activity_at__lte=end_time
    ).count()
    
    logger.debug(f"DAU for {target_date}: {dau}")
    return dau


def calculate_wau(target_date=None):
    """
    Calculate Weekly Active Users for a specific date
    
    Args:
        target_date: Date to calculate WAU for (defaults to yesterday)
        
    Returns:
        int: Number of users active in the 7 days ending at target_date
        
    Example:
        >>> calculate_wau(date(2025, 12, 6))
        5234
    """
    from users.models import User
    
    if target_date is None:
        target_date = (timezone.now() - timedelta(days=1)).date()
    
    # Convert date to datetime range
    end_time = timezone.make_aware(datetime.combine(target_date, datetime.max.time()))
    start_time = end_time - timedelta(days=7)
    
    wau = User.objects.filter(
        last_activity_at__gte=start_time,
        last_activity_at__lte=end_time
    ).count()
    
    logger.debug(f"WAU for {target_date}: {wau}")
    return wau


def calculate_mau(target_date=None):
    """
    Calculate Monthly Active Users for a specific date
    
    Args:
        target_date: Date to calculate MAU for (defaults to yesterday)
        
    Returns:
        int: Number of users active in the 30 days ending at target_date
        
    Example:
        >>> calculate_mau(date(2025, 12, 6))
        8456
    """
    from users.models import User
    
    if target_date is None:
        target_date = (timezone.now() - timedelta(days=1)).date()
    
    # Convert date to datetime range
    end_time = timezone.make_aware(datetime.combine(target_date, datetime.max.time()))
    start_time = end_time - timedelta(days=30)
    
    mau = User.objects.filter(
        last_activity_at__gte=start_time,
        last_activity_at__lte=end_time
    ).count()
    
    logger.debug(f"MAU for {target_date}: {mau}")
    return mau


def calculate_country_metrics(target_date=None):
    """
    Calculate DAU/WAU/MAU broken down by country
    
    Args:
        target_date: Date to calculate metrics for (defaults to yesterday)
        
    Returns:
        dict: Country code -> metrics dict
        
    Example:
        >>> calculate_country_metrics(date(2025, 12, 6))
        {
            'VE': {'dau': 1500, 'wau': 2800, 'mau': 4200, 'total_users': 5000},
            'AR': {'dau': 800, 'wau': 1500, 'mau': 2300, 'total_users': 3000},
            ...
        }
    """
    from users.models import User
    
    if target_date is None:
        target_date = (timezone.now() - timedelta(days=1)).date()
    
    # Convert date to datetime range
    end_time = timezone.make_aware(datetime.combine(target_date, datetime.max.time()))
    dau_start = end_time - timedelta(days=1)
    wau_start = end_time - timedelta(days=7)
    mau_start = end_time - timedelta(days=30)
    
    # Get all countries with users
    countries = User.objects.filter(
        phone_country__isnull=False
    ).values_list('phone_country', flat=True).distinct()
    
    metrics = {}
    
    for country_code in countries:
        if not country_code:
            continue
            
        country_users = User.objects.filter(phone_country=country_code)
        
        # Calculate DAU for this country
        dau = country_users.filter(
            last_activity_at__gte=dau_start,
            last_activity_at__lte=end_time
        ).count()
        
        # Calculate WAU for this country
        wau = country_users.filter(
            last_activity_at__gte=wau_start,
            last_activity_at__lte=end_time
        ).count()
        
        # Calculate MAU for this country
        mau = country_users.filter(
            last_activity_at__gte=mau_start,
            last_activity_at__lte=end_time
        ).count()
        
        # Total users from this country
        total_users = country_users.count()
        
        # New users today from this country
        new_users_today = country_users.filter(
            created_at__gte=dau_start,
            created_at__lte=end_time
        ).count()
        
        metrics[country_code] = {
            'dau': dau,
            'wau': wau,
            'mau': mau,
            'total_users': total_users,
            'new_users_today': new_users_today,
        }
        
        logger.debug(f"Country {country_code} metrics for {target_date}: {metrics[country_code]}")
    
    return metrics


def snapshot_daily_metrics(target_date=None):
    """
    Create a daily metrics snapshot for a specific date
    
    This function calculates and stores DAU/WAU/MAU metrics for the target date.
    It's idempotent - if a snapshot already exists for the date, it will be updated.
    
    Args:
        target_date: Date to snapshot (defaults to yesterday)
        
    Returns:
        DailyMetrics: The created or updated snapshot
        
    Example:
        >>> snapshot = snapshot_daily_metrics(date(2025, 12, 6))
        >>> print(f"DAU: {snapshot.dau}, MAU: {snapshot.mau}")
    """
    from users.models import User
    from users.models_analytics import DailyMetrics
    
    if target_date is None:
        target_date = (timezone.now() - timedelta(days=1)).date()
    
    logger.info(f"Creating daily metrics snapshot for {target_date}")
    
    # Calculate metrics
    dau = calculate_dau(target_date)
    wau = calculate_wau(target_date)
    mau = calculate_mau(target_date)
    
    # Calculate total users as of target date
    end_time = timezone.make_aware(datetime.combine(target_date, datetime.max.time()))
    total_users = User.objects.filter(created_at__lte=end_time).count()
    
    # Calculate new users on target date
    start_time = end_time - timedelta(days=1)
    new_users_today = User.objects.filter(
        created_at__gte=start_time,
        created_at__lte=end_time
    ).count()
    
    # Calculate DAU/MAU ratio
    dau_mau_ratio = Decimal(dau) / Decimal(mau) if mau > 0 else Decimal('0')
    
    # Create or update snapshot
    snapshot, created = DailyMetrics.objects.update_or_create(
        date=target_date,
        defaults={
            'dau': dau,
            'wau': wau,
            'mau': mau,
            'total_users': total_users,
            'new_users_today': new_users_today,
            'dau_mau_ratio': dau_mau_ratio,
        }
    )
    
    action = "Created" if created else "Updated"
    logger.info(f"{action} daily metrics snapshot for {target_date}: DAU={dau}, WAU={wau}, MAU={mau}")
    
    return snapshot


def snapshot_country_metrics(target_date=None):
    """
    Create country-specific metrics snapshots for a specific date
    
    Args:
        target_date: Date to snapshot (defaults to yesterday)
        
    Returns:
        list: List of created/updated CountryMetrics objects
        
    Example:
        >>> snapshots = snapshot_country_metrics(date(2025, 12, 6))
        >>> print(f"Captured metrics for {len(snapshots)} countries")
    """
    from users.models_analytics import CountryMetrics
    
    if target_date is None:
        target_date = (timezone.now() - timedelta(days=1)).date()
    
    logger.info(f"Creating country metrics snapshots for {target_date}")
    
    # Calculate metrics for all countries
    country_data = calculate_country_metrics(target_date)
    
    snapshots = []
    for country_code, metrics in country_data.items():
        snapshot, created = CountryMetrics.objects.update_or_create(
            date=target_date,
            country_code=country_code,
            defaults={
                'dau': metrics['dau'],
                'wau': metrics['wau'],
                'mau': metrics['mau'],
                'total_users': metrics['total_users'],
                'new_users_today': metrics['new_users_today'],
            }
        )
        snapshots.append(snapshot)
        
        action = "Created" if created else "Updated"
        logger.debug(f"{action} country metrics for {country_code} on {target_date}")
    
    logger.info(f"Captured metrics for {len(snapshots)} countries on {target_date}")
    return snapshots


def get_growth_rate(metric='mau', days_back=7, target_date=None):
    """
    Calculate growth rate for a specific metric
    
    Args:
        metric: Metric to calculate growth for ('dau', 'wau', or 'mau')
        days_back: Number of days to look back for comparison
        target_date: Date to calculate from (defaults to yesterday)
        
    Returns:
        Decimal: Growth rate as percentage (e.g., 15.5 for 15.5% growth)
        None if insufficient data
        
    Example:
        >>> growth = get_growth_rate('mau', days_back=7)
        >>> print(f"MAU grew {growth}% this week")
    """
    from users.models_analytics import DailyMetrics
    
    if target_date is None:
        target_date = (timezone.now() - timedelta(days=1)).date()
    
    comparison_date = target_date - timedelta(days=days_back)
    
    try:
        current = DailyMetrics.objects.get(date=target_date)
        previous = DailyMetrics.objects.get(date=comparison_date)
        
        current_value = getattr(current, metric)
        previous_value = getattr(previous, metric)
        
        if previous_value == 0:
            return None
        
        growth = ((current_value - previous_value) / previous_value) * 100
        return Decimal(str(growth)).quantize(Decimal('0.01'))
        
    except DailyMetrics.DoesNotExist:
        logger.warning(f"Missing metrics for growth calculation: {target_date} or {comparison_date}")
        return None


def get_dau_mau_ratio(target_date=None):
    """
    Calculate DAU/MAU ratio for a specific date
    
    Args:
        target_date: Date to calculate ratio for (defaults to yesterday)
        
    Returns:
        Decimal: DAU/MAU ratio (0.0 to 1.0)
        
    Example:
        >>> ratio = get_dau_mau_ratio()
        >>> print(f"Engagement ratio: {ratio:.2%}")
    """
    from users.models_analytics import DailyMetrics
    
    if target_date is None:
        target_date = (timezone.now() - timedelta(days=1)).date()
    
    try:
        snapshot = DailyMetrics.objects.get(date=target_date)
        return snapshot.dau_mau_ratio
    except DailyMetrics.DoesNotExist:
        # Calculate on the fly if no snapshot exists
        dau = calculate_dau(target_date)
        mau = calculate_mau(target_date)
        return Decimal(dau) / Decimal(mau) if mau > 0 else Decimal('0')
