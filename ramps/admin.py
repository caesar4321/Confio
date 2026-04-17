import json

from django.contrib import admin

from ramps.models import KoyweBankInfo, RampPaymentMethod, RampTransaction, RampUserAddress, RampWebhookEvent


@admin.register(KoyweBankInfo)
class KoyweBankInfoAdmin(admin.ModelAdmin):
    list_display = ('name', 'bank_code', 'country_code', 'is_active', 'synced_at')
    list_filter = ('country_code', 'is_active')
    search_fields = ('name', 'bank_code', 'institution_name')
    readonly_fields = ('synced_at',)


@admin.register(RampUserAddress)
class RampUserAddressAdmin(admin.ModelAdmin):
    list_display = ('user', 'address_city', 'address_state', 'address_zip_code', 'updated_at')
    search_fields = ('user__email', 'user__username', 'address_street', 'address_city', 'address_state', 'address_zip_code')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(RampPaymentMethod)
class RampPaymentMethodAdmin(admin.ModelAdmin):
    list_display = (
        'display_name',
        'code',
        'country_code',
        'provider_type',
        'supports_on_ramp',
        'supports_off_ramp',
        'is_active',
        'display_order',
    )
    list_filter = (
        'country_code',
        'provider_type',
        'supports_on_ramp',
        'supports_off_ramp',
        'is_active',
    )
    search_fields = (
        'display_name',
        'code',
        'country_code',
        'description',
    )
    readonly_fields = ('legacy_payment_method',)


@admin.register(RampTransaction)
class RampTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'provider',
        'direction',
        'status',
        'status_detail_short',
        'provider_order_id',
        'actor_display_name',
        'fiat_currency',
        'fiat_amount',
        'final_currency',
        'final_amount',
        'created_at',
    )
    list_filter = (
        'provider',
        'direction',
        'status',
        'fiat_currency',
        'final_currency',
        'created_at',
    )
    search_fields = (
        'provider_order_id',
        'external_id',
        'actor_display_name',
        'actor_address',
        'status_detail',
        'guardarian_transaction__guardarian_id',
    )
    readonly_fields = (
        'internal_id',
        'provider',
        'direction',
        'status',
        'status_detail',
        'provider_order_id',
        'external_id',
        'country_code',
        'actor_user',
        'actor_business',
        'actor_type',
        'actor_display_name',
        'actor_address',
        'fiat_currency',
        'fiat_amount',
        'crypto_currency',
        'crypto_amount_estimated',
        'crypto_amount_actual',
        'final_currency',
        'final_amount',
        'instruction_snapshot_created_pretty',
        'instruction_snapshot_latest_pretty',
        'provider_payload_created_pretty',
        'provider_payload_latest_pretty',
        'metadata',
        'guardarian_transaction',
        'usdc_deposit',
        'usdc_withdrawal',
        'conversion',
        'created_at',
        'updated_at',
        'completed_at',
    )
    fieldsets = (
        ('Estado', {
            'fields': (
                'internal_id',
                'provider',
                'direction',
                'status',
                'status_detail',
                'provider_order_id',
                'external_id',
                'country_code',
            ),
        }),
        ('Actor', {
            'fields': (
                'actor_user',
                'actor_business',
                'actor_type',
                'actor_display_name',
                'actor_address',
            ),
        }),
        ('Montos', {
            'fields': (
                'fiat_currency',
                'fiat_amount',
                'crypto_currency',
                'crypto_amount_estimated',
                'crypto_amount_actual',
                'final_currency',
                'final_amount',
            ),
        }),
        ('Vínculos', {
            'fields': (
                'guardarian_transaction',
                'usdc_deposit',
                'usdc_withdrawal',
                'conversion',
            ),
        }),
        ('Metadata', {
            'fields': (
                'instruction_snapshot_created_pretty',
                'instruction_snapshot_latest_pretty',
                'provider_payload_created_pretty',
                'provider_payload_latest_pretty',
                'metadata',
            ),
        }),
        ('Fechas', {
            'fields': (
                'created_at',
                'updated_at',
                'completed_at',
            ),
        }),
    )

    def status_detail_short(self, obj):
        value = obj.status_detail or ''
        return value if len(value) <= 80 else f'{value[:77]}...'

    status_detail_short.short_description = 'Status detail'

    def _pretty_json(self, value):
        if not value:
            return '—'
        try:
            return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return str(value)

    @admin.display(description='Instruction snapshot (created)')
    def instruction_snapshot_created_pretty(self, obj):
        return self._pretty_json((obj.metadata or {}).get('instruction_snapshot_created'))

    @admin.display(description='Instruction snapshot (latest)')
    def instruction_snapshot_latest_pretty(self, obj):
        return self._pretty_json((obj.metadata or {}).get('instruction_snapshot_latest'))

    @admin.display(description='Provider payload (created)')
    def provider_payload_created_pretty(self, obj):
        return self._pretty_json((obj.metadata or {}).get('provider_payload_created'))

    @admin.display(description='Provider payload (latest)')
    def provider_payload_latest_pretty(self, obj):
        return self._pretty_json((obj.metadata or {}).get('provider_payload_latest'))


@admin.register(RampWebhookEvent)
class RampWebhookEventAdmin(admin.ModelAdmin):
    list_display = (
        'provider',
        'event_type',
        'event_id',
        'processed_at',
    )
    list_filter = (
        'provider',
        'event_type',
        'processed_at',
    )
    search_fields = (
        'event_id',
        'event_type',
    )
    readonly_fields = (
        'provider',
        'event_id',
        'event_type',
        'payload',
        'processed_at',
    )
