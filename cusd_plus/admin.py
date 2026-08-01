from django.contrib import admin, messages


class BnbAutoConvertAdmin(admin.ModelAdmin):
    """Read-only ledger view: rows are written by the relay, never by hand.
    Support uses this to answer "why did subsidies stop for this user" —
    outbound BNB txs missing from here are the farming signal."""
    list_display = ('user', 'value_wei', 'tx_hash', 'created_at')
    search_fields = ('tx_hash', 'user__username', 'user__email')
    readonly_fields = ('user', 'value_wei', 'tx_hash', 'created_at')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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

