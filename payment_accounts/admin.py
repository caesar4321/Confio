from django.contrib import admin

from .models import (
    AccountCapability,
    EligibilityDecision,
    EligibilityPolicy,
    EligibilityRule,
    FinancialAccount,
    FundingInstruction,
    LedgerEntry,
    MoneyFlow,
    MoneyOperation,
    PayoutDestination,
    ProviderProfile,
    ProviderWebhookEvent,
    PaymentBridgeQuote,
    PaymentBridgeTransfer,
)


class PaymentBridgeQuoteAdmin(admin.ModelAdmin):
    list_display = ('internal_id', 'confio_account', 'source_token_id', 'destination_token_id', 'expires_at')
    readonly_fields = tuple(field.name for field in PaymentBridgeQuote._meta.fields)
    search_fields = ('internal_id', 'request_id')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PaymentBridgeTransferAdmin(admin.ModelAdmin):
    list_display = ('internal_id', 'status', 'source_tx_hash', 'destination_tx_hash', 'failure_code', 'updated_at')
    list_filter = ('status',)
    readonly_fields = tuple(field.name for field in PaymentBridgeTransfer._meta.fields if field.name != 'signed_raw_tx')
    exclude = ('signed_raw_tx',)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class EligibilityRuleInline(admin.TabularInline):
    model = EligibilityRule
    extra = 0
    ordering = ('priority',)


class EligibilityPolicyAdmin(admin.ModelAdmin):
    list_display = ('provider', 'scope', 'version', 'is_active', 'default_decision')
    list_filter = ('provider', 'scope', 'is_active', 'default_decision')
    inlines = [EligibilityRuleInline]


class ProviderProfileAdmin(admin.ModelAdmin):
    list_display = ('internal_id', 'confio_account', 'provider', 'owner_type', 'status')
    list_filter = ('provider', 'owner_type', 'status')
    search_fields = ('internal_id', 'provider_owner_id')


class FinancialAccountAdmin(admin.ModelAdmin):
    list_display = ('internal_id', 'provider_profile', 'ownership_structure', 'country', 'asset', 'status')
    list_filter = ('ownership_structure', 'country', 'asset', 'status')
    search_fields = ('internal_id', 'provider_account_id')


class MoneyFlowAdmin(admin.ModelAdmin):
    list_display = ('internal_id', 'confio_account', 'kind', 'source_asset', 'target_asset', 'status')
    list_filter = ('kind', 'status')
    search_fields = ('internal_id',)


class MoneyOperationAdmin(admin.ModelAdmin):
    list_display = ('internal_id', 'provider', 'operation_type', 'status', 'source_asset', 'source_amount')
    list_filter = ('provider', 'operation_type', 'status')
    search_fields = ('internal_id', 'provider_operation_id', 'idempotency_key')


from .models import InfiniaJourney


class InfiniaJourneyAdmin(admin.ModelAdmin):
    list_display = ('internal_id', 'direction', 'stage', 'failure_code', 'updated_at')
    list_filter = ('direction', 'stage')
    readonly_fields = tuple(field.name for field in InfiniaJourney._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


from .models import CobreJourney


class CobreJourneyAdmin(admin.ModelAdmin):
    list_display = ('internal_id', 'direction', 'stage', 'failure_code', 'updated_at')
    list_filter = ('direction', 'stage')
    readonly_fields = tuple(field.name for field in CobreJourney._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
