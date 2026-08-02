import logging

from django.contrib import admin
from .models import Balance, ProcessedIndexerTransaction, IndexerAssetCursor

logger = logging.getLogger(__name__)


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


class SponsoredBatchAdmin(admin.ModelAdmin):
    """Read-only 7702 sponsorship ledger: rows are written by sponsor_7702
    at broadcast and resolved by the receipt task. Support triage keys:
    'noop_failed' = delegation didn't apply (auth nonce raced — client
    should have retried); lingering 'sent' = receipt never resolved."""
    list_display = (
        'user', 'kind', 'user_bsc_address', 'num_calls', 'status',
        'gas_limit', 'tx_hash', 'created_at',
    )
    list_filter = ('status', 'kind')
    search_fields = ('tx_hash', 'user_bsc_address', 'user__username', 'user__email')
    readonly_fields = (
        'user', 'user_bsc_address', 'kind', 'num_calls', 'calls_json',
        'tx_hash', 'gas_limit', 'max_fee_wei', 'status', 'created_at',
        'updated_at',
    )
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # NO terminalize/clear action here, deliberately. An operator button that
    # moves a 'sent' batch to 'dropped' looks like the obvious escape hatch for
    # a receipt that never resolves, but 'sent' only says the DATABASE has not
    # seen an outcome — it cannot say the broadcast transaction will never
    # mine. Marking it dropped frees the presale uniqueness slot and fails the
    # domain row, so the user retries; if the original then mines, the buy or
    # send executes TWICE (Codex audit 2026-08-02, P1). Doing this safely needs
    # authoritative proof the original is impossible — replacing the sponsor
    # nonce and waiting for finality — which is a piece of infrastructure, not
    # an admin action. Until that exists, a stuck batch is escalated by the
    # reconciler's give-up ERROR and resolved by engineering, not by a button.
