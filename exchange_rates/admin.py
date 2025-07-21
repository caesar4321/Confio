from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from .models import ExchangeRate, RateFetchLog


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = (
        'currency_pair_display', 'rate_display', 'rate_type_badge', 
        'source_badge', 'fetched_ago', 'is_active'
    )
    list_filter = ('source_currency', 'target_currency', 'rate_type', 'source', 'is_active', 'fetched_at')
    search_fields = ('source_currency', 'target_currency')
    readonly_fields = ('created_at', 'fetched_at', 'raw_data_display')
    ordering = ('-fetched_at',)
    
    fieldsets = (
        ('Currency Pair', {
            'fields': ('source_currency', 'target_currency')
        }),
        ('Rate Information', {
            'fields': ('rate', 'rate_type', 'source', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('fetched_at', 'created_at'),
            'classes': ('collapse',)
        }),
        ('Debug Information', {
            'fields': ('raw_data_display',),
            'classes': ('collapse',)
        }),
    )
    
    def currency_pair_display(self, obj):
        return f"{obj.source_currency}/{obj.target_currency}"
    currency_pair_display.short_description = "Currency Pair"
    
    def rate_display(self, obj):
        try:
            rate_value = float(obj.rate)
            formatted_rate = f"{rate_value:.6f}"
        except (ValueError, TypeError):
            formatted_rate = str(obj.rate)
        
        return format_html(
            '<span style="font-weight: bold; font-family: monospace;">{}</span>',
            formatted_rate
        )
    rate_display.short_description = "Rate"
    
    def rate_type_badge(self, obj):
        colors = {
            'parallel': '#10B981',    # Green
            'official': '#3B82F6',    # Blue  
            'average': '#F59E0B',     # Yellow
            'black_market': '#EF4444' # Red
        }
        color = colors.get(obj.rate_type, '#6B7280')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 6px; '
            'border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            obj.get_rate_type_display()
        )
    rate_type_badge.short_description = "Type"
    
    def source_badge(self, obj):
        colors = {
            'yadio': '#7C3AED', 
            'exchangerate_api': '#DC2626',
            'currencylayer': '#F59E0B',
            'bluelytics': '#0EA5E9',  # Sky blue for Argentine sources
            'dolarapi': '#06B6D4',   # Cyan for Argentine sources  
            'bcv': '#1D4ED8',
            'manual': '#6B7280'
        }
        color = colors.get(obj.source, '#6B7280')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 6px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            color,
            obj.get_source_display()
        )
    source_badge.short_description = "Source"
    
    def fetched_ago(self, obj):
        now = timezone.now()
        diff = now - obj.fetched_at
        
        if diff.days > 0:
            return f"{diff.days} days ago"
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f"{hours} hours ago"
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f"{minutes} minutes ago"
        else:
            return "Just now"
    fetched_ago.short_description = "Fetched"
    
    def raw_data_display(self, obj):
        if obj.raw_data:
            import json
            formatted_json = json.dumps(obj.raw_data, indent=2)
            return format_html('<pre style="background: #f8f9fa; padding: 10px; border-radius: 4px;">{}</pre>', formatted_json)
        return "No raw data"
    raw_data_display.short_description = "Raw API Response"


@admin.register(RateFetchLog)
class RateFetchLogAdmin(admin.ModelAdmin):
    list_display = (
        'source_badge', 'status_badge', 'rates_fetched', 
        'response_time_display', 'created_ago', 'error_preview'
    )
    list_filter = ('source', 'status', 'created_at')
    search_fields = ('source', 'error_message')
    readonly_fields = ('created_at', 'error_message_display')
    ordering = ('-created_at',)
    
    fieldsets = (
        ('Fetch Information', {
            'fields': ('source', 'status', 'rates_fetched', 'response_time_ms')
        }),
        ('Timestamps', {
            'fields': ('created_at',)
        }),
        ('Error Details', {
            'fields': ('error_message_display',),
            'classes': ('collapse',)
        }),
    )
    
    def source_badge(self, obj):
        colors = {
            'yadio': '#7C3AED', 
            'exchangerate_api': '#DC2626',
            'currencylayer': '#F59E0B',
            'bluelytics': '#0EA5E9',  # Sky blue for Argentine sources
            'dolarapi': '#06B6D4',   # Cyan for Argentine sources  
            'bcv': '#1D4ED8',
            'manual': '#6B7280'
        }
        color = colors.get(obj.source, '#6B7280')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 6px; '
            'border-radius: 4px; font-size: 11px;">{}</span>',
            color,
            obj.source
        )
    source_badge.short_description = "Source"
    
    def status_badge(self, obj):
        colors = {
            'success': '#10B981',
            'failed': '#EF4444',
            'partial': '#F59E0B'
        }
        color = colors.get(obj.status, '#6B7280')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 6px; '
            'border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = "Status"
    
    def response_time_display(self, obj):
        if obj.response_time_ms:
            if obj.response_time_ms > 1000:
                return f"{obj.response_time_ms / 1000:.1f}s"
            else:
                return f"{obj.response_time_ms}ms"
        return "N/A"
    response_time_display.short_description = "Response Time"
    
    def created_ago(self, obj):
        now = timezone.now()
        diff = now - obj.created_at
        
        if diff.days > 0:
            return f"{diff.days} days ago"
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f"{hours} hours ago"
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f"{minutes} minutes ago"
        else:
            return "Just now"
    created_ago.short_description = "Created"
    
    def error_preview(self, obj):
        if obj.error_message:
            preview = obj.error_message[:50]
            if len(obj.error_message) > 50:
                preview += "..."
            return preview
        return "-"
    error_preview.short_description = "Error Preview"
    
    def error_message_display(self, obj):
        if obj.error_message:
            return format_html('<pre style="background: #fef2f2; padding: 10px; border-radius: 4px; color: #dc2626;">{}</pre>', obj.error_message)
        return "No error message"
    error_message_display.short_description = "Full Error Message"