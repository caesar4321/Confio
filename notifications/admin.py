from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from django.urls import path, reverse
from django.utils.safestring import mark_safe
from .models import Notification, NotificationRead, NotificationPreference, FCMDeviceToken
from .admin_views import broadcast_notification_view, notification_stats_view


class NotificationReadInline(admin.TabularInline):
    model = NotificationRead
    extra = 0
    readonly_fields = ['user', 'read_at']
    can_delete = False


class NotificationAdmin(admin.ModelAdmin):
    change_list_template = 'admin/notifications/notification_changelist.html'
    list_display = [
        'id', 'notification_type_badge', 'title', 'user_display', 
        'is_broadcast_badge', 'push_sent_badge', 'created_at'
    ]
    list_filter = [
        'notification_type', 'is_broadcast', 'push_sent', 
        'created_at', 'broadcast_target'
    ]
    search_fields = [
        'title', 'message', 'user__email', 'user__phone_number',
        'account__id', 'business__name'
    ]
    readonly_fields = [
        'created_at', 'updated_at', 'push_sent_at',
        'related_info_display', 'data_display'
    ]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('notification_type', 'title', 'message', 'action_url')
        }),
        ('Recipients', {
            'fields': ('user', 'account', 'business', 'is_broadcast', 'broadcast_target'),
            'description': 'For personalized notifications, set user/account/business. For broadcasts, set is_broadcast=True.'
        }),
        ('Related Object', {
            'fields': ('related_object_type', 'related_object_id', 'related_info_display', 'data', 'data_display')
        }),
        ('Push Notification', {
            'fields': ('push_sent', 'push_sent_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        })
    )
    
    inlines = [NotificationReadInline]
    
    def notification_type_badge(self, obj):
        colors = {
            'SEND': '#4CAF50',
            'PAYMENT': '#2196F3',
            'P2P': '#FF9800',
            'CONVERSION': '#9C27B0',
            'USDC': '#00BCD4',
            'ACCOUNT': '#607D8B',
            'BUSINESS': '#795548',
            'SECURITY': '#F44336',
            'PROMOTION': '#E91E63',
            'SYSTEM': '#9E9E9E',
            'ANNOUNCEMENT': '#3F51B5'
        }
        
        # Get color based on notification type prefix
        color = '#9E9E9E'  # default gray
        for prefix, c in colors.items():
            if obj.notification_type.startswith(prefix):
                color = c
                break
        
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">{}</span>',
            color, obj.get_notification_type_display()
        )
    notification_type_badge.short_description = 'Type'
    
    def user_display(self, obj):
        if obj.is_broadcast:
            return format_html('<em>Broadcast to: {}</em>', obj.broadcast_target or 'All')
        elif obj.user:
            return f"{obj.user.email} ({obj.user.phone_number or 'No phone'})"
        return '-'
    user_display.short_description = 'Recipient'
    
    def is_broadcast_badge(self, obj):
        if obj.is_broadcast:
            read_count = obj.reads.count()
            return format_html(
                '<span style="background-color: #FF5722; color: white; padding: 3px 8px; '
                'border-radius: 3px; font-size: 11px;">BROADCAST ({} reads)</span>',
                read_count
            )
        return format_html(
            '<span style="background-color: #4CAF50; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">PERSONAL</span>'
        )
    is_broadcast_badge.short_description = 'Type'
    
    def push_sent_badge(self, obj):
        if obj.push_sent:
            return format_html(
                '<span style="background-color: #4CAF50; color: white; padding: 3px 8px; '
                'border-radius: 3px; font-size: 11px;">✓ SENT</span>'
            )
        return format_html(
            '<span style="background-color: #FFC107; color: #333; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">PENDING</span>'
        )
    push_sent_badge.short_description = 'Push Status'
    
    def related_info_display(self, obj):
        if obj.related_object_type and obj.related_object_id:
            return format_html(
                '<strong>Type:</strong> {}<br><strong>ID:</strong> {}',
                obj.related_object_type, obj.related_object_id
            )
        return '-'
    related_info_display.short_description = 'Related Object'
    
    def data_display(self, obj):
        if obj.data:
            import json
            return format_html('<pre>{}</pre>', json.dumps(obj.data, indent=2))
        return '-'
    data_display.short_description = 'Additional Data (JSON)'
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('user', 'account', 'business')
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('broadcast/', self.admin_site.admin_view(broadcast_notification_view), 
                 name='notifications_notification_broadcast'),
            path('stats/', self.admin_site.admin_view(notification_stats_view),
                 name='notifications_notification_stats'),
        ]
        return custom_urls + urls
    
    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['broadcast_url'] = reverse('admin:notifications_notification_broadcast')
        extra_context['stats_url'] = reverse('admin:notifications_notification_stats')
        return super().changelist_view(request, extra_context=extra_context)


class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'push_enabled_badge', 'in_app_enabled_badge',
        'push_summary', 'created_at'
    ]
    list_filter = [
        'push_enabled', 'in_app_enabled',
        'push_transactions', 'push_p2p', 'push_security',
        'push_promotions', 'push_announcements'
    ]
    search_fields = ['user__email', 'user__phone_number']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('User', {
            'fields': ('user',)
        }),
        ('Push Notification Preferences', {
            'fields': (
                'push_enabled', 'push_transactions', 'push_p2p',
                'push_security', 'push_promotions', 'push_announcements'
            )
        }),
        ('In-App Notification Preferences', {
            'fields': (
                'in_app_enabled', 'in_app_transactions', 'in_app_p2p',
                'in_app_security', 'in_app_promotions', 'in_app_announcements'
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        })
    )
    
    def push_enabled_badge(self, obj):
        if obj.push_enabled:
            return format_html(
                '<span style="background-color: #4CAF50; color: white; padding: 3px 8px; '
                'border-radius: 3px; font-size: 11px;">✓ ENABLED</span>'
            )
        return format_html(
            '<span style="background-color: #F44336; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">✗ DISABLED</span>'
        )
    push_enabled_badge.short_description = 'Push'
    
    def in_app_enabled_badge(self, obj):
        if obj.in_app_enabled:
            return format_html(
                '<span style="background-color: #4CAF50; color: white; padding: 3px 8px; '
                'border-radius: 3px; font-size: 11px;">✓ ENABLED</span>'
            )
        return format_html(
            '<span style="background-color: #F44336; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">✗ DISABLED</span>'
        )
    in_app_enabled_badge.short_description = 'In-App'
    
    def push_summary(self, obj):
        enabled = []
        if obj.push_transactions: enabled.append('Transactions')
        if obj.push_p2p: enabled.append('P2P')
        if obj.push_security: enabled.append('Security')
        if obj.push_promotions: enabled.append('Promotions')
        if obj.push_announcements: enabled.append('Announcements')
        
        return ', '.join(enabled) if enabled else 'None'
    push_summary.short_description = 'Push Categories'


class FCMDeviceTokenAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'user_display', 'device_type_badge', 'device_name',
        'is_active_badge', 'last_used', 'failure_info'
    ]
    list_filter = [
        'device_type', 'is_active', 'created_at', 'last_used'
    ]
    search_fields = [
        'user__email', 'user__phone_number', 'device_id', 
        'device_name', 'token'
    ]
    readonly_fields = [
        'token_preview', 'created_at', 'updated_at', 'last_used',
        'failure_count', 'last_failure', 'last_failure_reason'
    ]
    
    fieldsets = (
        ('User & Device', {
            'fields': ('user', 'device_type', 'device_id', 'device_name', 'app_version')
        }),
        ('Token Information', {
            'fields': ('token', 'token_preview', 'is_active')
        }),
        ('Usage & Status', {
            'fields': ('last_used', 'failure_count', 'last_failure', 'last_failure_reason')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        })
    )
    
    def user_display(self, obj):
        return f"{obj.user.email} ({obj.user.phone_number or 'No phone'})"
    user_display.short_description = 'User'
    
    def device_type_badge(self, obj):
        colors = {
            'ios': '#007AFF',
            'android': '#3DDC84',
            'web': '#FF6900'
        }
        color = colors.get(obj.device_type, '#9E9E9E')
        icon = '📱' if obj.device_type in ['ios', 'android'] else '🌐'
        
        return format_html(
            '{} <span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">{}</span>',
            icon, color, obj.device_type.upper()
        )
    device_type_badge.short_description = 'Type'
    
    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="background-color: #4CAF50; color: white; padding: 3px 8px; '
                'border-radius: 3px; font-size: 11px;">✓ ACTIVE</span>'
            )
        return format_html(
            '<span style="background-color: #F44336; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">✗ INACTIVE</span>'
        )
    is_active_badge.short_description = 'Status'
    
    def failure_info(self, obj):
        if obj.failure_count == 0:
            return format_html(
                '<span style="color: #4CAF50;">✓ No failures</span>'
            )
        
        color = '#FF9800' if obj.failure_count < 3 else '#F44336'
        return format_html(
            '<span style="color: {};">⚠ {} failure{}</span>',
            color, obj.failure_count, 's' if obj.failure_count != 1 else ''
        )
    failure_info.short_description = 'Failures'
    
    def token_preview(self, obj):
        """Show first and last 10 characters of token for security"""
        if len(obj.token) > 20:
            return f"{obj.token[:10]}...{obj.token[-10:]}"
        return obj.token
    token_preview.short_description = 'Token Preview'
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('user')
    
    actions = ['activate_tokens', 'deactivate_tokens', 'reset_failure_counts']
    
    def activate_tokens(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f'{count} token(s) activated.')
    activate_tokens.short_description = 'Activate selected tokens'
    
    def deactivate_tokens(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f'{count} token(s) deactivated.')
    deactivate_tokens.short_description = 'Deactivate selected tokens'
    
    def reset_failure_counts(self, request, queryset):
        count = queryset.update(
            failure_count=0,
            last_failure=None,
            last_failure_reason=''
        )
        self.message_user(request, f'Reset failure counts for {count} token(s).')
    reset_failure_counts.short_description = 'Reset failure counts'
