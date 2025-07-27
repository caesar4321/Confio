from django.contrib import admin
from .models import Conversion


@admin.register(Conversion)
class ConversionAdmin(admin.ModelAdmin):
    list_display = ['conversion_id', 'actor_display', 'actor_type_icon', 'conversion_type', 'from_amount', 'to_amount', 'status', 'created_at']
    list_filter = ['status', 'conversion_type', 'actor_type', 'created_at']
    search_fields = ['conversion_id', 'actor_user__username', 'actor_user__email', 'actor_business__name', 'actor_display_name', 'from_transaction_hash', 'to_transaction_hash']
    readonly_fields = ['conversion_id', 'created_at', 'updated_at', 'completed_at']
    
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
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('conversion_id', 'conversion_type', 'status')
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
