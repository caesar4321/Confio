from django.contrib import admin
from .models import Balance, ProcessedIndexerTransaction, IndexerAssetCursor


@admin.register(Balance)
class BalanceAdmin(admin.ModelAdmin):
    list_display = ['account', 'token', 'amount', 'available_amount', 'pending_amount', 'is_stale', 'last_synced']
    list_filter = ['token', 'is_stale', 'last_synced']
    search_fields = ['account__user__email', 'account__algorand_address']
    readonly_fields = ['last_synced', 'last_blockchain_check', 'available_amount']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('account', 'account__user')


@admin.register(ProcessedIndexerTransaction)
class ProcessedIndexerTransactionAdmin(admin.ModelAdmin):
    list_display = ['txid', 'asset_id', 'receiver', 'confirmed_round', 'intra', 'created_at']
    list_filter = ['asset_id', 'confirmed_round', 'created_at']
    search_fields = ['txid', 'receiver', 'sender']
    ordering = ['-created_at']


@admin.register(IndexerAssetCursor)
class IndexerAssetCursorAdmin(admin.ModelAdmin):
    list_display = ['asset_id', 'last_scanned_round', 'updated_at']
    search_fields = ['asset_id']
    ordering = ['-updated_at']
    actions = ['reset_cursors']

    def reset_cursors(self, request, queryset):
        updated = queryset.update(last_scanned_round=0)
        self.message_user(request, f"Reset {updated} cursor(s) to round 0.")
    reset_cursors.short_description = "Reset selected cursors to round 0"
