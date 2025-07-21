from django.contrib import admin
from django.utils import timezone
from django.contrib import messages
from django.utils.html import format_html
from .models import Invoice, PaymentTransaction

class MerchantBusinessFilter(admin.SimpleListFilter):
    title = 'Merchant Business Status'
    parameter_name = 'merchant_business_status'

    def lookups(self, request, model_admin):
        return (
            ('has_business', 'Has Business'),
            ('missing_business', 'Missing Business (Legacy)'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'has_business':
            return queryset.filter(merchant_business__isnull=False)
        elif self.value() == 'missing_business':
            return queryset.filter(merchant_business__isnull=True)

@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    """Admin configuration for PaymentTransaction model"""
    list_display = [
        'id',
        'payment_transaction_id',
        'payer_display', 
        'merchant_display',
        'amount', 
        'token_type', 
        'status', 
        'created_at',
        'transaction_hash_display'
    ]
    list_filter = [
        'status', 
        'token_type',
        'payer_type',
        'merchant_type', 
        'created_at', 
        'updated_at',
        'payer_user__is_active',
        'merchant_account_user__is_active',
        MerchantBusinessFilter  # Shows if merchant_business is missing
    ]
    search_fields = [
        'payment_transaction_id',
        'transaction_hash',
        'payer_user__username', 
        'payer_user__email',
        'payer_business__name',
        'merchant_account_user__username',
        'merchant_account_user__email',
        'merchant_business__name',
        'payer_address',
        'merchant_address',
        'description',
        'payer_display_name',
        'merchant_display_name'
    ]
    readonly_fields = [
        'payment_transaction_id',
        'created_at', 
        'updated_at', 
        'transaction_hash'
    ]
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    
    actions = ['retry_failed_payments', 'mark_as_confirmed', 'mark_as_failed']
    
    fieldsets = (
        ('Payment Information', {
            'fields': ('payment_transaction_id', 'amount', 'token_type', 'description')
        }),
        ('Payer Details', {
            'fields': ('payer_type', 'payer_user', 'payer_business', 'payer_display_name'),
            'description': 'Payer can be Personal (payer_user) OR Business (payer_business)'
        }),
        ('Merchant Details', {
            'fields': ('merchant_type', 'merchant_business', 'merchant_account_user', 'merchant_display_name'),
            'description': 'Merchant Business (REQUIRED) + User who handled the transaction (owner/cashier)'
        }),
        ('Legacy User Fields', {
            'fields': ('merchant_user',),
            'classes': ('collapse',),
            'description': 'DEPRECATED: Use merchant_business + merchant_account_user instead'
        }),
        ('Legacy Account Details', {
            'fields': ('payer_account', 'merchant_account'),
            'classes': ('collapse',),
            'description': 'Legacy account fields - will be deprecated'
        }),
        ('Blockchain Details', {
            'fields': ('payer_address', 'merchant_address', 'transaction_hash'),
            'classes': ('collapse',)
        }),
        ('Status & Timing', {
            'fields': ('status', 'error_message', 'created_at', 'updated_at')
        }),
        ('Invoice Reference', {
            'fields': ('invoice',),
            'classes': ('collapse',)
        }),
        ('System Fields', {
            'fields': ('deleted_at',),
            'classes': ('collapse',)
        }),
    )
    
    def payer_display(self, obj):
        """Display payer with type indicator and colored badge"""
        if obj.payer_business:
            return format_html(
                '<span style="background-color: #3B82F6; color: white; padding: 2px 6px; '
                'border-radius: 4px; font-size: 11px; margin-right: 4px;">BUSINESS</span>'
                '<strong>{}</strong>',
                obj.payer_business.name
            )
        elif obj.payer_user:
            return format_html(
                '<span style="background-color: #10B981; color: white; padding: 2px 6px; '
                'border-radius: 4px; font-size: 11px; margin-right: 4px;">PERSONAL</span>'
                '{} {}',
                obj.payer_user.first_name or obj.payer_user.username,
                obj.payer_user.last_name or ''
            )
        return "Unknown Payer"
    payer_display.short_description = "Payer"
    payer_display.admin_order_field = 'payer_user__username'
    
    def merchant_display(self, obj):
        """Display merchant with business and account user info"""
        business_part = ""
        user_part = ""
        
        # Show merchant business (the actual merchant entity)
        if obj.merchant_business:
            business_part = format_html(
                '<span style="background-color: #8B5CF6; color: white; padding: 2px 6px; '
                'border-radius: 4px; font-size: 11px; margin-right: 4px;">BUSINESS</span>'
                '<strong>{}</strong>',
                obj.merchant_business.name
            )
        elif obj.merchant_user:
            # Legacy fallback - should be migrated
            business_part = format_html(
                '<span style="background-color: #F59E0B; color: white; padding: 2px 6px; '
                'border-radius: 4px; font-size: 11px; margin-right: 4px;">LEGACY</span>'
                '{}',
                obj.merchant_user.username
            )
        else:
            business_part = format_html(
                '<span style="background-color: #EF4444; color: white; padding: 2px 6px; '
                'border-radius: 4px; font-size: 11px;">⚠️ MISSING BUSINESS</span>'
            )
        
        # Show account user (who handled the transaction)
        if obj.merchant_account_user:
            user_part = format_html(
                '<br><small>👤 Handled by: {}</small>',
                obj.merchant_account_user.username
            )
        
        return format_html('{}{}', business_part, user_part)
    
    merchant_display.short_description = "Merchant Business & Handler"
    merchant_display.admin_order_field = 'merchant_business__name'
    
    def transaction_hash_display(self, obj):
        """Display transaction hash with truncation"""
        if obj.transaction_hash:
            return f"{obj.transaction_hash[:8]}...{obj.transaction_hash[-8:]}"
        return "Pending"
    transaction_hash_display.short_description = "Transaction Hash"
    
    def retry_failed_payments(self, request, queryset):
        """Retry failed payment transactions"""
        updated = queryset.filter(status='FAILED').update(status='PENDING')
        self.message_user(request, f"{updated} failed payments marked for retry.")
    retry_failed_payments.short_description = "Retry failed payments"
    
    def mark_as_confirmed(self, request, queryset):
        """Mark payment transactions as confirmed"""
        updated = queryset.filter(status='PENDING').update(status='CONFIRMED')
        self.message_user(request, f"{updated} payments marked as confirmed.")
    mark_as_confirmed.short_description = "Mark as confirmed"
    
    def mark_as_failed(self, request, queryset):
        """Mark payment transactions as failed"""
        updated = queryset.filter(status='PENDING').update(status='FAILED')
        self.message_user(request, f"{updated} payments marked as failed.")
    mark_as_failed.short_description = "Mark as failed"

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    """Admin configuration for Invoice model"""
    list_display = [
        'invoice_id', 
        'merchant_display', 
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
        'merchant_type', 
        'created_at', 
        'expires_at',
        'created_by_user__is_active',
        MerchantBusinessFilter  # Shows if merchant_business is missing
    ]
    search_fields = [
        'invoice_id', 
        'created_by_user__username', 
        'created_by_user__email',
        'merchant_business__name',
        'merchant_display_name',
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
            'fields': ('invoice_id', 'amount', 'token_type', 'description')
        }),
        ('Merchant Details', {
            'fields': ('merchant_type', 'merchant_business', 'created_by_user', 'merchant_display_name'),
            'description': 'Merchant Business (REQUIRED) + User who created the invoice (owner/cashier)'
        }),
        ('Legacy User Fields', {
            'fields': ('merchant_user',),
            'classes': ('collapse',),
            'description': 'DEPRECATED: Use merchant_business + created_by_user instead'
        }),
        ('Legacy Account Details', {
            'fields': ('merchant_account',),
            'classes': ('collapse',),
            'description': 'Legacy account field - will be deprecated'
        }),
        ('Status & Timing', {
            'fields': ('status', 'created_at', 'expires_at', 'is_expired')
        }),
        ('Payment Details', {
            'fields': ('paid_by_user', 'paid_by_business', 'paid_at', 'transaction'),
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
    
    def merchant_display(self, obj):
        """Display merchant with business and creator info"""
        business_part = ""
        creator_part = ""
        
        # Show merchant business (the actual merchant entity)
        if obj.merchant_business:
            business_part = format_html(
                '<span style="background-color: #8B5CF6; color: white; padding: 2px 6px; '
                'border-radius: 4px; font-size: 11px; margin-right: 4px;">BUSINESS</span>'
                '<strong>{}</strong>',
                obj.merchant_business.name
            )
        elif obj.merchant_user:
            # Legacy fallback - should be migrated
            business_part = format_html(
                '<span style="background-color: #F59E0B; color: white; padding: 2px 6px; '
                'border-radius: 4px; font-size: 11px; margin-right: 4px;">LEGACY</span>'
                '{}',
                obj.merchant_user.username
            )
        else:
            business_part = format_html(
                '<span style="background-color: #EF4444; color: white; padding: 2px 6px; '
                'border-radius: 4px; font-size: 11px;">⚠️ MISSING BUSINESS</span>'
            )
        
        # Show creator user (who created the invoice)
        if obj.created_by_user:
            creator_part = format_html(
                '<br><small>📝 Created by: {}</small>',
                obj.created_by_user.username
            )
        
        return format_html('{}{}', business_part, creator_part)
    
    merchant_display.short_description = "Merchant Business & Creator"
    merchant_display.admin_order_field = 'merchant_business__name'
    
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
