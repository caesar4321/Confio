from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import Notification, NotificationRead, NotificationPreference


class NotificationReadInline(admin.TabularInline):
    model = NotificationRead
    extra = 0
    readonly_fields = ['user', 'read_at']
    can_delete = False


class NotificationAdmin(admin.ModelAdmin):
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
