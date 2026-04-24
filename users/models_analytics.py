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


# ---------------------------------------------------------------------------
# Funnel tracking (Invitar y Enviar + referral loop)
# ---------------------------------------------------------------------------
#
# Design notes:
# - FunnelEvent is the raw per-event stream. One row per occurrence.
# - We keep 90 days of raw rows and roll up nightly into FunnelDailyRollup.
# - Emissions from mutations MUST be fire-and-forget via
#   users.funnel.emit_event() to avoid coupling financial paths to analytics.
# - `user` is nullable so we can capture pre-signup events (e.g. /invite link
#   click from Cloudflare Worker where only an IP/session fingerprint exists).
# - `session_id` lets us stitch pre-signup → signup → first_deposit without a
#   user FK.
# - `properties` is intentionally JSON for schema flexibility; structured
#   fields that we filter on (country, platform, source_type, channel,
#   event_name) are columns.


class FunnelEvent(models.Model):
    """Raw per-event stream for funnel analysis.

    Retention: 90 days. A nightly Celery job rolls up into FunnelDailyRollup
    and deletes rows older than the retention window.
    """

    # Canonical event names. Kept as free-form CharField (not choices) so new
    # events can be added without a migration, but document them here:
    #   invite_submitted      — on-chain escrow created (SubmitInviteForPhone)
    #   whatsapp_share_tapped — user tapped the WhatsApp share button
    #   invite_link_clicked   — click attributable to a send-and-invite share
    #   referral_link_clicked — generic /invite/{USERNAME} hit on Cloudflare Worker
    #   invite_claimed        — recipient claimed escrow (ClaimInviteForPhone)
    #   first_send            — user's first outbound send of any kind
    #   first_deposit         — user's first successful on-ramp (Koywe, etc.)

    event_name = models.CharField(
        max_length=64,
        db_index=True,
        help_text="Canonical event name, e.g. 'invite_submitted'",
    )

    user = models.ForeignKey(
        'users.User',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='funnel_events',
        help_text="Authenticated user, if any. NULL for pre-signup events.",
    )

    session_id = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text=(
            "Opaque session/fingerprint id for stitching pre-signup events "
            "to post-signup ones. Typically the Worker's IP-referral key or "
            "a client-generated UUID."
        ),
    )

    country = models.CharField(
        max_length=2,
        blank=True,
        db_index=True,
        help_text="ISO 3166-1 alpha-2; empty if unknown.",
    )

    platform = models.CharField(
        max_length=16,
        blank=True,
        help_text="'ios', 'android', 'web', or empty.",
    )

    source_type = models.CharField(
        max_length=32,
        blank=True,
        db_index=True,
        help_text="Attribution bucket such as 'send_invite', 'referral_link', or 'install_referrer'.",
    )

    channel = models.CharField(
        max_length=32,
        blank=True,
        db_index=True,
        help_text="Acquisition/share channel such as 'whatsapp', 'instagram', 'youtube', or 'tiktok'.",
    )

    properties = models.JSONField(
        default=dict,
        blank=True,
        help_text="Event-specific payload. Keep small; not indexed.",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['event_name', 'created_at']),
            models.Index(fields=['country', 'event_name', 'created_at']),
            models.Index(fields=['source_type', 'event_name', 'created_at']),
            models.Index(fields=['channel', 'event_name', 'created_at']),
            models.Index(fields=['user', 'event_name']),
            models.Index(fields=['session_id', 'event_name']),
        ]
        verbose_name = "Funnel Event"
        verbose_name_plural = "Funnel Events (raw, 90d)"

    def __str__(self):
        who = self.user_id or f"session:{self.session_id[:8]}" or 'anon'
        return f"{self.event_name} · {self.source_type or '??'}/{self.channel or '??'} · {self.country or '??'} · {who}"


class FunnelDailyRollup(models.Model):
    """Daily aggregate of FunnelEvent, segmented by country + platform + attribution.

    One row per (date, event_name, country, platform, source_type, channel, cohort).
    Built by nightly Celery job from the raw stream before raw rows are purged.
    """

    date = models.DateField(db_index=True)
    event_name = models.CharField(max_length=64, db_index=True)
    country = models.CharField(max_length=2, blank=True)
    platform = models.CharField(max_length=16, blank=True)
    source_type = models.CharField(max_length=32, blank=True)
    channel = models.CharField(max_length=32, blank=True)
    cohort = models.CharField(
        max_length=32,
        blank=True,
        db_index=True,
        help_text=(
            "Low-cardinality funnel cohort, e.g. 'creator_julianmoonluna', "
            "'user_driven', 'send_invite', or 'unknown'."
        ),
    )

    count = models.IntegerField(
        validators=[MinValueValidator(0)],
        help_text="Total events on this date/segment.",
    )
    unique_users = models.IntegerField(
        validators=[MinValueValidator(0)],
        help_text="Distinct authenticated users. Pre-signup events not counted here.",
    )
    unique_sessions = models.IntegerField(
        validators=[MinValueValidator(0)],
        default=0,
        help_text="Distinct session_ids (includes pre-signup).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['date', 'event_name', 'country', 'platform', 'source_type', 'channel', 'cohort'],
                name='unique_funnel_rollup',
            ),
        ]
        indexes = [
            models.Index(fields=['-date', 'event_name']),
            models.Index(fields=['event_name', 'country', '-date']),
            models.Index(fields=['event_name', 'source_type', 'channel', '-date']),
            models.Index(
                fields=['event_name', 'source_type', 'cohort', '-date'],
                name='users_funne_ev_so_co_5c6_idx',
            ),
        ]
        verbose_name = "Funnel Daily Rollup"
        verbose_name_plural = "Funnel Daily Rollups"

    def __str__(self):
        seg = (
            f"{self.country or '??'}/{self.platform or '??'}/"
            f"{self.source_type or '??'}/{self.channel or '??'}/{self.cohort or '??'}"
        )
        return f"{self.date} · {self.event_name} · {seg} · {self.count}"
