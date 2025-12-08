"""
Analytics models for tracking DAU/WAU/MAU metrics over time

This module provides historical snapshots of user activity metrics for:
- Time-series analysis and growth tracking
- PMF (Product-Market Fit) evaluation
- Investor reporting and analytics
- Feature impact analysis (before/after comparisons)
- Geographic expansion insights

All metrics are calculated from the centralized last_activity_at field
in the User model (see users/activity_tracking.py).
"""

from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from decimal import Decimal


class DailyMetrics(models.Model):
    """
    Daily snapshot of platform-wide activity metrics
    
    Captures DAU/WAU/MAU at a specific point in time for historical analysis.
    This enables tracking growth rates, engagement trends, and feature impact.
    
    Snapshots are typically captured daily at 3:00 AM UTC via Celery Beat.
    """
    
    # Snapshot metadata
    date = models.DateField(
        unique=True,
        db_index=True,
        help_text="Date of this metrics snapshot (typically yesterday)"
    )
    
    # Core activity metrics
    dau = models.IntegerField(
        validators=[MinValueValidator(0)],
        help_text="Daily Active Users - users active in last 24 hours"
    )
    wau = models.IntegerField(
        validators=[MinValueValidator(0)],
        help_text="Weekly Active Users - users active in last 7 days"
    )
    mau = models.IntegerField(
        validators=[MinValueValidator(0)],
        help_text="Monthly Active Users - users active in last 30 days"
    )
    
    # User growth metrics
    total_users = models.IntegerField(
        validators=[MinValueValidator(0)],
        help_text="Total registered users as of this date"
    )
    new_users_today = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="New user signups on this date"
    )
    
    # Engagement metrics
    dau_mau_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        validators=[MinValueValidator(Decimal('0'))],
        help_text="DAU/MAU ratio - engagement indicator (0.0 to 1.0)"
    )
    
    # Timestamps
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this snapshot was created"
    )
    
    class Meta:
        ordering = ['-date']
        verbose_name = "Daily Metrics"
        verbose_name_plural = "Daily Metrics"
        indexes = [
            models.Index(fields=['-date']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"Metrics for {self.date}: DAU={self.dau:,} WAU={self.wau:,} MAU={self.mau:,}"
    
    @property
    def dau_wau_ratio(self):
        """Calculate DAU/WAU ratio"""
        if self.wau == 0:
            return Decimal('0')
        return Decimal(self.dau) / Decimal(self.wau)
    
    @property
    def wau_mau_ratio(self):
        """Calculate WAU/MAU ratio"""
        if self.mau == 0:
            return Decimal('0')
        return Decimal(self.wau) / Decimal(self.mau)
    
    def get_growth_rate(self, days_back=7):
        """
        Calculate growth rate compared to N days ago
        
        Args:
            days_back: Number of days to look back for comparison
            
        Returns:
            Decimal: Growth rate as percentage (e.g., 15.5 for 15.5% growth)
        """
        from datetime import timedelta
        
        comparison_date = self.date - timedelta(days=days_back)
        try:
            previous = DailyMetrics.objects.get(date=comparison_date)
            if previous.mau == 0:
                return Decimal('0')
            
            growth = ((self.mau - previous.mau) / previous.mau) * 100
            return Decimal(str(growth)).quantize(Decimal('0.01'))
        except DailyMetrics.DoesNotExist:
            return None


class CountryMetrics(models.Model):
    """
    Daily snapshot of country-specific activity metrics
    
    Tracks DAU/WAU/MAU by country for geographic expansion analysis.
    Country is determined by the user's phone_country field.
    
    This enables:
    - Identifying high-growth markets
    - Comparing engagement across countries
    - Evaluating market penetration
    - Planning geographic expansion
    """
    
    # Snapshot metadata
    date = models.DateField(
        db_index=True,
        help_text="Date of this metrics snapshot"
    )
    country_code = models.CharField(
        max_length=2,
        db_index=True,
        help_text="ISO 3166-1 alpha-2 country code (e.g., VE, AR, CO)"
    )
    
    # Country-specific activity metrics
    dau = models.IntegerField(
        validators=[MinValueValidator(0)],
        help_text="Daily Active Users from this country"
    )
    wau = models.IntegerField(
        validators=[MinValueValidator(0)],
        help_text="Weekly Active Users from this country"
    )
    mau = models.IntegerField(
        validators=[MinValueValidator(0)],
        help_text="Monthly Active Users from this country"
    )
    
    # Country user base
    total_users = models.IntegerField(
        validators=[MinValueValidator(0)],
        help_text="Total registered users from this country"
    )
    new_users_today = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        help_text="New signups from this country on this date"
    )
    
    # Timestamps
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="When this snapshot was created"
    )
    
    class Meta:
        ordering = ['-date', 'country_code']
        verbose_name = "Country Metrics"
        verbose_name_plural = "Country Metrics"
        unique_together = [['date', 'country_code']]
        indexes = [
            models.Index(fields=['-date', 'country_code']),
            models.Index(fields=['country_code', '-date']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.country_code} on {self.date}: DAU={self.dau:,} MAU={self.mau:,}"
    
    @property
    def dau_mau_ratio(self):
        """Calculate DAU/MAU ratio for this country"""
        if self.mau == 0:
            return Decimal('0')
        return Decimal(self.dau) / Decimal(self.mau)
    
    @property
    def country_name(self):
        """Get country name from country code"""
        from users.country_codes import COUNTRY_CODES
        for country in COUNTRY_CODES:
            if country[2] == self.country_code:
                return country[0]
        return self.country_code
    
    @property
    def country_flag(self):
        """Get country flag emoji"""
        # Map of country codes to flag emojis
        flags = {
            'VE': '🇻🇪', 'CO': '🇨🇴', 'AR': '🇦🇷', 'PE': '🇵🇪', 'CL': '🇨🇱',
            'BR': '🇧🇷', 'MX': '🇲🇽', 'US': '🇺🇸', 'DO': '🇩🇴', 'PA': '🇵🇦',
            'EC': '🇪🇨', 'BO': '🇧🇴', 'UY': '🇺🇾', 'PY': '🇵🇾', 'GT': '🇬🇹',
            'HN': '🇭🇳', 'SV': '🇸🇻', 'NI': '🇳🇮', 'CR': '🇨🇷', 'CU': '🇨🇺',
        }
        return flags.get(self.country_code, '🌐')
