from django.contrib import admin
from .models import RawBlockchainEvent, Balance, TransactionProcessingLog, SuiEpoch


@admin.register(RawBlockchainEvent)
class RawBlockchainEventAdmin(admin.ModelAdmin):
    list_display = ['tx_hash', 'module', 'function', 'sender', 'epoch', 'checkpoint', 'block_time', 'processed', 'created_at']
    list_filter = ['processed', 'module', 'function', 'epoch', 'created_at']
    search_fields = ['tx_hash', 'sender', 'epoch', 'checkpoint']
    readonly_fields = ['tx_hash', 'sender', 'module', 'function', 'raw_data', 'block_time', 'epoch', 'checkpoint', 'created_at']
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


@admin.register(SuiEpoch)
class SuiEpochAdmin(admin.ModelAdmin):
    list_display = ['epoch_number', 'is_current', 'duration_hours_display', 'total_transactions', 
                    'avg_gas_price_display', 'start_time', 'end_time']
    list_filter = ['is_current', 'created_at']
    search_fields = ['epoch_number']
    readonly_fields = ['epoch_number', 'start_timestamp_ms', 'end_timestamp_ms', 
                       'first_checkpoint', 'last_checkpoint', 'total_transactions',
                       'total_gas_cost', 'stake_subsidy_amount', 'total_stake_rewards',
                       'storage_fund_balance', 'epoch_commitments', 'duration_hours_display',
                       'avg_gas_price_display', 'created_at', 'updated_at']
    ordering = ['-epoch_number']
    
    def has_add_permission(self, request):
        return False  # Don't allow manual creation
    
    def duration_hours_display(self, obj):
        duration = obj.duration_hours
        if duration:
            return f"{duration:.2f} hours"
        return "In Progress"
    duration_hours_display.short_description = "Duration"
    
    def avg_gas_price_display(self, obj):
        avg_price = obj.avg_gas_price
        if avg_price:
            return f"{avg_price:,.0f} MIST"
        return "0 MIST"
    avg_gas_price_display.short_description = "Avg Gas Price"
    
    def start_time(self, obj):
        from django.utils import timezone
        from datetime import datetime
        return timezone.make_aware(datetime.fromtimestamp(obj.start_timestamp_ms / 1000))
    start_time.short_description = "Start Time"
    
    def end_time(self, obj):
        if obj.end_timestamp_ms:
            from django.utils import timezone
            from datetime import datetime
            return timezone.make_aware(datetime.fromtimestamp(obj.end_timestamp_ms / 1000))
        return "Ongoing"
    end_time.short_description = "End Time"
