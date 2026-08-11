import logging
from decimal import Decimal, InvalidOperation

from django.contrib import admin
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.utils.html import format_html
from .models import (
    Balance, IndexerAssetCursor, OndoStockTrade, PendingAutoSwap,
    ProcessedIndexerTransaction, SponsoredBatch,
)

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


class PendingAutoSwapAdmin(admin.ModelAdmin):
    """Actionable auto-swap work waiting on the client signer.

    Covers both rails: Algorand USDC/ALGO rescues and the BSC 'BNB' rows,
    which are ALSO the authoritative allowlist for outbound native BNB — an
    outbound transfer with no row here is dust extraction. That makes this
    an audit surface, so nothing here is editable and rows are never
    deleted; a PENDING pile is a stranded-deposit queue, not a backlog to
    clear by hand.
    """
    list_display = (
        'id', 'account', 'asset_type', 'amount_decimal', 'status',
        'source_address', 'source_tx_hash', 'created_at', 'completed_at',
    )
    list_filter = ('asset_type', 'status', 'actor_type', 'created_at')
    search_fields = (
        'source_tx_hash', 'source_address', 'actor_address',
        'account__user__username', 'account__user__email',
    )
    # Derived from the model so a field added later cannot appear here as an
    # editable input on what is also an audit surface.
    readonly_fields = tuple(f.name for f in PendingAutoSwap._meta.fields)
    ordering = ('-created_at',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('account', 'account__user')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class SponsoredBatchAdmin(admin.ModelAdmin):
    """Read-only 7702 sponsorship ledger: rows are written by sponsor_7702
    at broadcast and resolved by the receipt task. Support triage keys:
    'noop_failed' = delegation didn't apply (auth nonce raced — client
    should have retried); lingering 'sent' = receipt never resolved."""
    list_display = (
        'user', 'kind', 'source_id', 'user_bsc_address', 'num_calls', 'status',
        'block_number', 'gas_limit', 'tx_hash', 'created_at',
    )
    list_filter = ('status', 'kind', 'created_at')
    search_fields = ('tx_hash', 'user_bsc_address', 'user__username', 'user__email')
    # Derived from the model rather than hand-listed: this admin blocks
    # changes, and a hand-list silently exposed every field added after it
    # was written (source_id, delegate_nonce, block_number, block_hash) as
    # an EDITABLE input on an audit ledger.
    readonly_fields = tuple(f.name for f in SponsoredBatch._meta.fields)
    ordering = ('-created_at',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
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


@admin.register(OndoStockTrade)
class OndoStockTradeAdmin(SponsoredBatchAdmin):
    """Read-only stock projection of the sponsored execution ledger.

    The linked unified row carries the exact event-backed USD settlement used
    by account history. Pending and failed attempts remain visible even though
    they do not have a settlement row yet.
    """

    list_display = (
        'id', 'trade_side', 'stock_symbol', 'settled_usd', 'user', 'status',
        'user_bsc_address', 'transaction_link', 'block_number', 'created_at',
    )
    list_display_links = None
    list_filter = ('kind', 'status', 'created_at')
    search_fields = (
        'tx_hash', 'user_bsc_address', 'user__username', 'user__email',
        'unified_transaction__description',
    )
    date_hierarchy = 'created_at'

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .filter(kind__in=('stock_buy', 'stock_sell'))
            .select_related('unified_transaction')
        )

    @admin.display(description='Side', ordering='kind')
    def trade_side(self, obj):
        return 'Buy' if obj.kind == 'stock_buy' else 'Sell'

    @staticmethod
    def _settlement(obj):
        try:
            return obj.unified_transaction
        except ObjectDoesNotExist:
            return None

    @admin.display(description='Stock')
    def stock_symbol(self, obj):
        row = self._settlement(obj)
        description = (getattr(row, 'description', '') or '').strip()
        marker = ' de '
        return description.rsplit(marker, 1)[-1] if marker in description else '—'

    @admin.display(description='Settled USD')
    def settled_usd(self, obj):
        row = self._settlement(obj)
        try:
            value = Decimal(row.amount)
        except (AttributeError, InvalidOperation, TypeError):
            return '—'
        return f'${value:,.2f}'

    @admin.display(description='Transaction')
    def transaction_link(self, obj):
        if not obj.tx_hash:
            return '—'
        explorer = (
            'https://testnet.bscscan.com'
            if int(getattr(settings, 'BSC_CHAIN_ID', 56)) == 97
            else 'https://bscscan.com'
        )
        return format_html(
            '<a href="{}/tx/{}" target="_blank" rel="noopener">{}…</a>',
            explorer, obj.tx_hash, obj.tx_hash[:12],
        )
