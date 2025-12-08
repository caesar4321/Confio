"""
Django Admin integration for analytics metrics

Provides admin interfaces for viewing and managing DAU/WAU/MAU snapshots.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils import timezone
from django.db.models import F
from datetime import timedelta
from decimal import Decimal

from .models_analytics import DailyMetrics, CountryMetrics


@admin.register(DailyMetrics)
class DailyMetricsAdmin(admin.ModelAdmin):
    """Admin interface for daily metrics snapshots"""
    
    list_display = (
        'date',
        'dau_display',
        'wau_display',
        'mau_display',
        'total_users_display',
        'new_users_display',
        'engagement_ratio',
        'growth_indicator',
        'created_at',
    )
    list_filter = ('date', 'created_at')
    search_fields = ('date',)
    date_hierarchy = 'date'
    ordering = ('-date',)
    
    # All fields are read-only (snapshots shouldn't be manually edited)
    readonly_fields = (
        'date', 'dau', 'wau', 'mau', 'total_users', 'new_users_today',
        'dau_mau_ratio', 'created_at', 'growth_details'
    )
    
    fieldsets = (
        ('Snapshot Date', {
            'fields': ('date', 'created_at')
        }),
        ('Activity Metrics', {
            'fields': ('dau', 'wau', 'mau', 'dau_mau_ratio')
        }),
        ('User Growth', {
            'fields': ('total_users', 'new_users_today')
        }),
        ('Growth Analysis', {
            'fields': ('growth_details',),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        """Prevent manual creation - use management command or Celery task"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Allow deletion for cleanup"""
        return request.user.is_superuser
    
    def dau_display(self, obj):
        """Display DAU with formatting"""
        return format_html(
            '<strong style="font-size: 1.1em; color: #3B82F6;">{:,}</strong>',
            obj.dau
        )
    dau_display.short_description = 'DAU'
    dau_display.admin_order_field = 'dau'
    
    def wau_display(self, obj):
        """Display WAU with formatting"""
        return format_html(
            '<strong style="font-size: 1.1em; color: #8B5CF6;">{:,}</strong>',
            obj.wau
        )
    wau_display.short_description = 'WAU'
    wau_display.admin_order_field = 'wau'
    
    def mau_display(self, obj):
        """Display MAU with formatting"""
        return format_html(
            '<strong style="font-size: 1.1em; color: #10B981;">{:,}</strong>',
            obj.mau
        )
    mau_display.short_description = 'MAU'
    mau_display.admin_order_field = 'mau'
    
    def total_users_display(self, obj):
        """Display total users"""
        return f"{obj.total_users:,}"
    total_users_display.short_description = 'Total Users'
    total_users_display.admin_order_field = 'total_users'
    
    def new_users_display(self, obj):
        """Display new users with badge"""
        if obj.new_users_today > 0:
            return format_html(
                '<span style="background-color: #10B981; color: white; padding: 2px 6px; border-radius: 4px;">+{:,}</span>',
                obj.new_users_today
            )
        return '0'
    new_users_display.short_description = 'New Users'
    new_users_display.admin_order_field = 'new_users_today'
    
    def engagement_ratio(self, obj):
        """Display DAU/MAU ratio as engagement indicator"""
        ratio = obj.dau_mau_ratio
        
        # Color code based on engagement level
        if ratio >= Decimal('0.20'):
            color = '#10B981'  # Green - excellent
        elif ratio >= Decimal('0.10'):
            color = '#F59E0B'  # Orange - good
        else:
            color = '#EF4444'  # Red - needs improvement
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{:.1%}</span>',
            color,
            ratio
        )
    engagement_ratio.short_description = 'DAU/MAU'
    engagement_ratio.admin_order_field = 'dau_mau_ratio'
    
    def growth_indicator(self, obj):
        """Display week-over-week growth indicator"""
        growth = obj.get_growth_rate(days_back=7)
        
        if growth is None:
            return format_html('<span style="color: gray;">N/A</span>')
        
        # Color code based on growth
        if growth > 0:
            color = '#10B981'  # Green
            icon = '📈'
        elif growth < 0:
            color = '#EF4444'  # Red
            icon = '📉'
        else:
            color = '#6B7280'  # Gray
            icon = '➡️'
        
        return format_html(
            '<span style="color: {};">{} {:+.1f}%</span>',
            color,
            icon,
            growth
        )
    growth_indicator.short_description = 'WoW Growth'
    
    def growth_details(self, obj):
        """Display detailed growth analysis"""
        growth_7d = obj.get_growth_rate(days_back=7)
        growth_30d = obj.get_growth_rate(days_back=30)
        
        html = '<table style="width: 100%; font-size: 14px;">'
        html += '<tr><th style="text-align: left;">Period</th><th style="text-align: right;">MAU Growth</th></tr>'
        
        if growth_7d is not None:
            color = '#10B981' if growth_7d > 0 else '#EF4444'
            html += f'<tr><td>Week-over-Week</td><td style="text-align: right; color: {color}; font-weight: bold;">{growth_7d:+.2f}%</td></tr>'
        
        if growth_30d is not None:
            color = '#10B981' if growth_30d > 0 else '#EF4444'
            html += f'<tr><td>Month-over-Month</td><td style="text-align: right; color: {color}; font-weight: bold;">{growth_30d:+.2f}%</td></tr>'
        
        html += '</table>'
        
        return format_html(html)
    growth_details.short_description = 'Growth Analysis'
    
    actions = ['capture_snapshot_now']
    
    def capture_snapshot_now(self, request, queryset):
        """Manual action to capture a snapshot for today"""
        from users.analytics import snapshot_daily_metrics
        from datetime import date
        
        try:
            target_date = (timezone.now() - timedelta(days=1)).date()
            snapshot = snapshot_daily_metrics(target_date)
            
            self.message_user(
                request,
                f"Successfully captured metrics for {target_date}: DAU={snapshot.dau:,}, MAU={snapshot.mau:,}",
                level='success'
            )
        except Exception as e:
            self.message_user(
                request,
                f"Error capturing metrics: {str(e)}",
                level='error'
            )
    
    capture_snapshot_now.short_description = "Capture snapshot for yesterday"


@admin.register(CountryMetrics)
class CountryMetricsAdmin(admin.ModelAdmin):
    """Admin interface for country-specific metrics"""
    
    list_display = (
        'country_display',
        'date',
        'dau_display',
        'wau_display',
        'mau_display',
        'total_users_display',
        'new_users_display',
        'engagement_ratio',
    )
    list_filter = ('country_code', 'date', 'created_at')
    search_fields = ('country_code', 'date')
    date_hierarchy = 'date'
    ordering = ('-date', '-mau')
    
    # All fields are read-only
    readonly_fields = (
        'date', 'country_code', 'dau', 'wau', 'mau',
        'total_users', 'new_users_today', 'created_at'
    )
    
    fieldsets = (
        ('Location & Date', {
            'fields': ('country_code', 'date', 'created_at')
        }),
        ('Activity Metrics', {
            'fields': ('dau', 'wau', 'mau')
        }),
        ('User Base', {
            'fields': ('total_users', 'new_users_today')
        }),
    )
    
    def has_add_permission(self, request):
        """Prevent manual creation"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Allow deletion for cleanup"""
        return request.user.is_superuser
    
    def country_display(self, obj):
        """Display country with flag"""
        return format_html(
            '<span style="font-size: 1.2em;">{}</span> <strong>{}</strong>',
            obj.country_flag,
            obj.country_code
        )
    country_display.short_description = 'Country'
    country_display.admin_order_field = 'country_code'
    
    def dau_display(self, obj):
        """Display DAU with formatting"""
        return f"{obj.dau:,}"
    dau_display.short_description = 'DAU'
    dau_display.admin_order_field = 'dau'
    
    def wau_display(self, obj):
        """Display WAU with formatting"""
        return f"{obj.wau:,}"
    wau_display.short_description = 'WAU'
    wau_display.admin_order_field = 'wau'
    
    def mau_display(self, obj):
        """Display MAU with formatting"""
        return format_html(
            '<strong style="color: #10B981;">{:,}</strong>',
            obj.mau
        )
    mau_display.short_description = 'MAU'
    mau_display.admin_order_field = 'mau'
    
    def total_users_display(self, obj):
        """Display total users"""
        return f"{obj.total_users:,}"
    total_users_display.short_description = 'Total Users'
    total_users_display.admin_order_field = 'total_users'
    
    def new_users_display(self, obj):
        """Display new users"""
        if obj.new_users_today > 0:
            return format_html(
                '<span style="color: #10B981;">+{:,}</span>',
                obj.new_users_today
            )
        return '0'
    new_users_display.short_description = 'New'
    new_users_display.admin_order_field = 'new_users_today'
    
    def engagement_ratio(self, obj):
        """Display DAU/MAU ratio"""
        ratio = obj.dau_mau_ratio
        
        if ratio >= Decimal('0.20'):
            color = '#10B981'
        elif ratio >= Decimal('0.10'):
            color = '#F59E0B'
        else:
            color = '#EF4444'
        
        return format_html(
            '<span style="color: {};">{:.1%}</span>',
            color,
            ratio
        )
    engagement_ratio.short_description = 'DAU/MAU'
