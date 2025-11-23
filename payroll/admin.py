from django.contrib import admin
from django.utils.timezone import localtime

from .models import PayrollRun, PayrollItem, PayrollRecipient


@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    list_display = (
        'run_id',
        'business',
        'token_type',
        'status',
        'scheduled_at_local',
        'net_total',
        'gross_total',
        'fee_total',
        'created_by_user',
        'created_at',
    )
    list_filter = ('status', 'token_type', 'business', 'created_at', 'scheduled_at', 'deleted_at')
    search_fields = ('run_id', 'business__name', 'created_by_user__username')
    readonly_fields = ('run_id', 'gross_total', 'net_total', 'fee_total', 'created_at', 'updated_at')
    ordering = ('-created_at',)

    def scheduled_at_local(self, obj):
        if not obj.scheduled_at:
            return 'No programado'
        return localtime(obj.scheduled_at).strftime('%Y-%m-%d %H:%M')
    scheduled_at_local.short_description = 'Programado'


@admin.register(PayrollItem)
class PayrollItemAdmin(admin.ModelAdmin):
    list_display = (
        'item_id',
        'run',
        'recipient_user',
        'recipient_account',
        'token_type',
        'net_amount',
        'status',
        'executed_at',
        'created_at',
    )
    list_filter = ('status', 'token_type', 'run__business', 'created_at', 'deleted_at')
    search_fields = ('item_id', 'run__run_id', 'recipient_user__username')
    readonly_fields = ('item_id', 'gross_amount', 'net_amount', 'fee_amount', 'created_at', 'updated_at')
    ordering = ('-created_at',)


@admin.register(PayrollRecipient)
class PayrollRecipientAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'display_name',
        'business',
        'recipient_user',
        'recipient_account',
        'created_at',
    )
    list_filter = ('business', 'created_at', 'deleted_at')
    search_fields = ('display_name', 'recipient_user__username', 'business__name')
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-created_at',)

    def display_name(self, obj):
        return obj.display_name or (obj.recipient_user.username if obj.recipient_user else '-')
    display_name.short_description = 'Nombre'
