from django.contrib import admin, messages


class CusdPlusConversionAdmin(admin.ModelAdmin):
    list_display = (
        'internal_id', 'actor_display_name', 'direction', 'source', 'amount_usd',
        'status', 'created_at', 'src_committed_at', 'dest_arrived_at',
        'completed_at',
    )
    list_filter = ('status', 'direction', 'source', 'actor_type')
    search_fields = (
        'internal_id', 'src_tx_id', 'dest_tx_hash', 'bridge_arrival_tx',
        'actor_display_name', 'user_bsc_address', 'user_algo_address',
    )
    readonly_fields = (
        'internal_id', 'created_at', 'updated_at',
        'src_committed_at', 'dest_arrived_at', 'completed_at',
        'bridge_arrival_tx', 'dest_scan_from_block',
    )
    ordering = ('-created_at',)
    actions = ('run_allbridge_diagnose',)

    @admin.action(description='Allbridge diagnose (support tool for STUCK rows)')
    def run_allbridge_diagnose(self, request, queryset):
        from .tasks import allbridge_diagnose
        for conv in queryset[:5]:  # support tool, not a batch job
            try:
                result = allbridge_diagnose(str(conv.internal_id))
                self.message_user(
                    request,
                    f'{conv.internal_id}: HTTP {result["status_code"]} — {str(result["body"])[:300]}',
                    level=messages.INFO,
                )
            except Exception as exc:  # noqa: BLE001
                self.message_user(
                    request, f'{conv.internal_id}: diagnose failed — {exc}',
                    level=messages.WARNING,
                )
