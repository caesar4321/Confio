from django.contrib import admin
from django.contrib import messages
from .models import Transaction

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """Admin configuration for Transaction model"""
    list_display = [
        'id',
        'sender_user', 
        'recipient_user',
        'amount', 
        'token_type', 
        'status', 
        'created_at',
        'transaction_hash_display'
    ]
    list_filter = [
        'status', 
        'token_type', 
        'created_at', 
        'updated_at',
        'sender_user__is_active',
        'recipient_user__is_active'
    ]
    search_fields = [
        'transaction_hash',
        'sender_user__username', 
        'sender_user__email',
        'recipient_user__username',
        'recipient_user__email',
        'sender_address',
        'recipient_address',
        'memo'
    ]
    readonly_fields = [
        'created_at', 
        'updated_at', 
        'transaction_hash'
    ]
    date_hierarchy = 'created_at'
    ordering = ['-created_at']
    
    actions = ['retry_failed_transactions', 'mark_as_confirmed', 'mark_as_failed']
    
    fieldsets = (
        ('Transaction Information', {
            'fields': ('sender_user', 'recipient_user', 'amount', 'token_type', 'memo')
        }),
        ('Blockchain Details', {
            'fields': ('sender_address', 'recipient_address', 'transaction_hash'),
            'classes': ('collapse',)
        }),
        ('Status & Timing', {
            'fields': ('status', 'error_message', 'created_at', 'updated_at')
        }),
        ('System Fields', {
            'fields': ('deleted_at',),
            'classes': ('collapse',)
        }),
    )
    
    def transaction_hash_display(self, obj):
        """Display transaction hash with truncation"""
        if obj.transaction_hash:
            return f"{obj.transaction_hash[:8]}...{obj.transaction_hash[-8:]}"
        return "Pending"
    transaction_hash_display.short_description = 'Transaction Hash'
    
    def retry_failed_transactions(self, request, queryset):
        """Retry failed transactions by setting status back to PENDING"""
        updated = queryset.filter(status='FAILED').update(status='PENDING', error_message='')
        self.message_user(
            request, 
            f'Successfully queued {updated} failed transaction(s) for retry.',
            messages.SUCCESS
        )
    retry_failed_transactions.short_description = "Retry failed transactions"
    
    def mark_as_confirmed(self, request, queryset):
        """Mark selected transactions as confirmed"""
        updated = queryset.filter(status__in=['PENDING', 'SUBMITTED']).update(status='CONFIRMED')
        self.message_user(
            request, 
            f'Successfully marked {updated} transaction(s) as confirmed.',
            messages.SUCCESS
        )
    mark_as_confirmed.short_description = "Mark as confirmed"
    
    def mark_as_failed(self, request, queryset):
        """Mark selected transactions as failed"""
        updated = queryset.filter(status__in=['PENDING', 'SUBMITTED']).update(
            status='FAILED', 
            error_message='Manually marked as failed by admin'
        )
        self.message_user(
            request, 
            f'Successfully marked {updated} transaction(s) as failed.',
            messages.SUCCESS
        )
    mark_as_failed.short_description = "Mark as failed"
    
    def get_queryset(self, request):
        """Show only non-deleted transactions by default"""
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
