"""Admin for month-summary spending categories (registered on confio_admin_site
in config/admin_dashboard.py). Read-mostly: labels are user data."""
from django.contrib import admin


class CounterpartyRuleAdmin(admin.ModelAdmin):
    list_display = ('account', 'counterparty_key', 'category', 'updated_at')
    list_filter = ('category',)
    search_fields = ('counterparty_key', 'account__id')
    raw_id_fields = ('account', 'created_by')
    readonly_fields = ('created_at', 'updated_at')


class MovementOverrideAdmin(admin.ModelAdmin):
    list_display = ('account', 'movement', 'category', 'updated_at')
    list_filter = ('category',)
    raw_id_fields = ('account', 'movement', 'created_by')
    readonly_fields = ('created_at', 'updated_at')


class CounterpartyPromptStateAdmin(admin.ModelAdmin):
    list_display = ('account', 'counterparty_key', 'skip_count', 'dismiss_count', 'updated_at')
    search_fields = ('counterparty_key', 'account__id')
    raw_id_fields = ('account',)
    readonly_fields = ('updated_at',)
