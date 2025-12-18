from django.contrib import admin
from .models import Conversion


@admin.register(Conversion)
class ConversionAdmin(admin.ModelAdmin):
    list_display = ['internal_id_hex', 'actor_display', 'actor_type_icon', 'conversion_type', 'from_amount', 'to_amount', 'status', 'created_at']
    list_filter = ['status', 'conversion_type', 'created_at', 'actor_type']
    search_fields = ['internal_id', 'actor_user__username', 'actor_user__email', 'actor_business__name', 'actor_display_name', 'from_transaction_hash', 'to_transaction_hash']
    readonly_fields = ['internal_id', 'created_at', 'updated_at', 'completed_at']
    
    def actor_display(self, obj):
        """Display actor with appropriate info"""
        if obj.actor_type == 'business' and obj.actor_business:
            return f"{obj.actor_business.name} (Business)"
        elif obj.actor_user:
            return f"{obj.actor_user.username} ({obj.actor_user.email})"
        return obj.actor_display_name or "Unknown"
    actor_display.short_description = 'Actor'
    
    def actor_type_icon(self, obj):
        """Display account type with icon"""
        if obj.actor_type == 'business':
            return f"🏢 Business"
        return f"👤 Personal"
    actor_type_icon.short_description = 'Type'
    
    def internal_id_hex(self, obj):
        """Display internal_id as 32-char hex"""
        return obj.internal_id.hex if obj.internal_id else '-'
    internal_id_hex.short_description = 'Internal ID'
    internal_id_hex.admin_order_field = 'internal_id'

    fieldsets = (
        ('Basic Information', {
            'fields': ('internal_id', 'conversion_type', 'status')
        }),
        ('Actor Information', {
            'fields': ('actor_type', 'actor_user', 'actor_business', 'actor_display_name', 'actor_address')
        }),
        ('Conversion Details', {
            'fields': ('from_amount', 'to_amount', 'exchange_rate', 'fee_amount')
        }),
        ('Transaction Hashes', {
            'fields': ('from_transaction_hash', 'to_transaction_hash')
        }),
        ('Status & Errors', {
            'fields': ('error_message',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'completed_at')
        }),
        ('Soft Delete', {
            'fields': ('is_deleted', 'deleted_at'),
            'classes': ('collapse',)
        }),
    )
    
    def has_delete_permission(self, request, obj=None):
        """Prevent hard deletes from admin"""
        return False
