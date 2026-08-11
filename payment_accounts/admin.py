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
)


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
