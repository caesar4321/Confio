from django.contrib import admin


class CusdPlusConversionAdmin(admin.ModelAdmin):
    list_display = (
        'internal_id', 'actor_display_name', 'direction', 'amount_usd',
        'status', 'created_at', 'src_committed_at', 'completed_at',
    )
    list_filter = ('status', 'direction', 'actor_type')
    search_fields = ('internal_id', 'src_tx_id', 'dest_tx_hash', 'actor_display_name')
    readonly_fields = (
        'internal_id', 'created_at', 'updated_at',
        'src_committed_at', 'dest_arrived_at', 'completed_at',
    )
    ordering = ('-created_at',)
