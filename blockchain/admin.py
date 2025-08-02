from django.contrib import admin
from .models import RawBlockchainEvent, Balance, TransactionProcessingLog


@admin.register(RawBlockchainEvent)
class RawBlockchainEventAdmin(admin.ModelAdmin):
    list_display = ['tx_hash', 'module', 'function', 'sender', 'block_time', 'processed', 'created_at']
    list_filter = ['processed', 'module', 'function', 'created_at']
    search_fields = ['tx_hash', 'sender']
    readonly_fields = ['tx_hash', 'sender', 'module', 'function', 'raw_data', 'block_time', 'created_at']
    ordering = ['-block_time']
    
    def has_add_permission(self, request):
        return False  # Don't allow manual creation


@admin.register(Balance)
class BalanceAdmin(admin.ModelAdmin):
    list_display = ['account', 'token', 'amount', 'available_amount', 'pending_amount', 'is_stale', 'last_synced']
    list_filter = ['token', 'is_stale', 'last_synced']
    search_fields = ['account__user__email', 'account__sui_address']
    readonly_fields = ['last_synced', 'last_blockchain_check', 'available_amount']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('account', 'account__user')


@admin.register(TransactionProcessingLog)
class TransactionProcessingLogAdmin(admin.ModelAdmin):
    list_display = ['raw_event', 'status', 'attempts', 'created_at', 'updated_at']
    list_filter = ['status', 'created_at']
    search_fields = ['raw_event__tx_hash']
    readonly_fields = ['created_at', 'updated_at']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('raw_event')
