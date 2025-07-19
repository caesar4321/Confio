from django.contrib import admin
from django.utils import timezone
from django.contrib import messages
from .models import Invoice

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    """Admin configuration for Invoice model"""
    list_display = [
        'invoice_id', 
        'merchant_user', 
        'amount', 
        'token_type', 
        'status', 
        'created_at', 
        'expires_at',
        'is_expired_display'
    ]
    list_filter = [
        'status', 
        'token_type', 
        'created_at', 
        'expires_at',
        'merchant_user__is_active'
    ]
    search_fields = [
        'invoice_id', 
        'merchant_user__username', 
        'merchant_user__email',
        'merchant_user__first_name',
        'merchant_user__last_name',
        'description'
    ]
    readonly_fields = [
        'invoice_id', 
        'created_at', 
        'updated_at', 
        'qr_code_data', 
        'is_expired'
    ]
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    
    actions = ['mark_as_expired', 'extend_expiration', 'cancel_invoices']
    
    fieldsets = (
        ('Invoice Information', {
            'fields': ('invoice_id', 'merchant_user', 'merchant_account', 'amount', 'token_type', 'description')
        }),
        ('Status & Timing', {
            'fields': ('status', 'created_at', 'expires_at', 'is_expired')
        }),
        ('Payment Details', {
            'fields': ('paid_by_user', 'paid_at', 'transaction'),
            'classes': ('collapse',)
        }),
        ('QR Code', {
            'fields': ('qr_code_data',),
            'classes': ('collapse',)
        }),
        ('System Fields', {
            'fields': ('updated_at', 'deleted_at'),
            'classes': ('collapse',)
        }),
    )
    
    def is_expired_display(self, obj):
        """Display if invoice is expired with color coding"""
        if obj.is_expired:
            return '🔴 Expired'
        return '🟢 Active'
    is_expired_display.short_description = 'Expired'
    is_expired_display.admin_order_field = 'expires_at'
    
    def mark_as_expired(self, request, queryset):
        """Mark selected invoices as expired"""
        updated = queryset.update(status='EXPIRED')
        self.message_user(
            request, 
            f'Successfully marked {updated} invoice(s) as expired.',
            messages.SUCCESS
        )
    mark_as_expired.short_description = "Mark selected invoices as expired"
    
    def extend_expiration(self, request, queryset):
        """Extend expiration time by 24 hours"""
        from datetime import timedelta
        updated = 0
        for invoice in queryset:
            if invoice.status == 'PENDING':
                invoice.expires_at = invoice.expires_at + timedelta(hours=24)
                invoice.save()
                updated += 1
        
        self.message_user(
            request, 
            f'Successfully extended expiration for {updated} invoice(s).',
            messages.SUCCESS
        )
    extend_expiration.short_description = "Extend expiration by 24 hours"
    
    def cancel_invoices(self, request, queryset):
        """Cancel selected invoices"""
        updated = queryset.filter(status='PENDING').update(status='CANCELLED')
        self.message_user(
            request, 
            f'Successfully cancelled {updated} invoice(s).',
            messages.SUCCESS
        )
    cancel_invoices.short_description = "Cancel selected invoices"
    
    def get_queryset(self, request):
        """Show only non-deleted invoices by default"""
        return super().get_queryset(request).filter(deleted_at__isnull=True)
    
    def has_delete_permission(self, request, obj=None):
        """Use soft delete instead of hard delete"""
        return True
    
    def delete_model(self, request, obj):
        """Override delete to use soft delete"""
        obj.delete()  # This will use the soft delete from SoftDeleteModel
    
    def delete_queryset(self, request, queryset):
        """Override bulk delete to use soft delete"""
        for obj in queryset:
            obj.delete()  # This will use the soft delete from SoftDeleteModel
