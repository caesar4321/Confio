"""Admin for Cuenta inteligente. Registered on the custom admin site
(config/admin_dashboard.py), never the default one. Mirrors of chain state
are read-only: they are written by smart_account/reconcile.py only."""
from django.contrib import admin

from .models import (
    SmartAccount, SmartAccountBeneficiary, SmartAccountCardPause, SmartAccountCardPull, SmartAccountCardSpender,
    SmartAccountCharge, SmartAccountClaim, SmartAccountEvent,
    SmartAccountForcedSale, SmartAccountForcedSaleLeg, SmartAccountPagoMovilDestination, SmartAccountPayout,
    SmartAccountPreparedAction,
    SmartAccountRelayTx, SmartAccountRule, SmartAccountRuleRun, SmartAccountScanCursor,
    SmartAccountStandingAuthorization, SmartAccountTargetAllocation, SmartAccountWatch,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Chain mirrors and audit rows: view only."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class SmartAccountAdmin(ReadOnlyAdmin):
    list_display = ('contract_address', 'owner_user', 'status', 'billing_status', 'plan', 'next_plan',
                    'paid_until', 'cancel_requested_at', 'inherited_from_user', 'created_at')
    list_filter = ('status', 'billing_status', 'plan')
    search_fields = ('contract_address', 'owner_user__username', 'owner_user__phone_number', 'created_tx')
    raw_id_fields = ('owner_user', 'owner_account', 'account', 'inherited_from_user')
    date_hierarchy = 'created_at'

    def get_queryset(self, request):
        return SmartAccount.all_objects.select_related('owner_user', 'inherited_from_user')


class SmartAccountEventAdmin(ReadOnlyAdmin):
    list_display = ('name', 'smart_account', 'block_number', 'log_index', 'block_time', 'tx_hash', 'applied_at')
    list_filter = ('name', ('applied_at', admin.EmptyFieldListFilter))
    search_fields = ('tx_hash', 'address', 'smart_account__contract_address')
    date_hierarchy = 'block_time'


class SmartAccountChargeAdmin(ReadOnlyAdmin):
    list_display = ('smart_account', 'plan', 'fee_usd', 'paid_with', 'period_start', 'period_end', 'tx_hash')
    list_filter = ('plan', 'paid_with')
    search_fields = ('tx_hash', 'smart_account__contract_address', 'smart_account__owner_user__username')
    date_hierarchy = 'charged_at'


class ForcedSaleLegInline(admin.TabularInline):
    model = SmartAccountForcedSaleLeg
    extra = 0
    can_delete = False
    readonly_fields = ('attempt', 'position', 'asset', 'asset_key', 'amount_in', 'dollars_out', 'quote_ref')

    def has_add_permission(self, request, obj=None):
        return False


class SmartAccountForcedSaleAdmin(ReadOnlyAdmin):
    list_display = ('smart_account', 'period_end', 'status', 'attempts', 'dollars_out', 'last_attempt_at', 'tx_hash')
    list_filter = ('status',)
    search_fields = ('tx_hash', 'smart_account__contract_address')
    inlines = [ForcedSaleLegInline]


class SmartAccountRuleAdmin(ReadOnlyAdmin):
    list_display = ('id', 'smart_account', 'kind', 'state', 'active', 'amount', 'frequency', 'onchain_id',
                    'scheduled_for', 'next_run_at', 'deactivated_reason')
    list_filter = ('kind', 'state', 'active', 'frequency')
    search_fields = ('smart_account__contract_address', 'smart_account__owner_user__username', 'payee_address')
    raw_id_fields = ('smart_account', 'payee_user', 'payout_method', 'pagomovil_destination',
                     'standing_authorization', 'replaces')

    def get_queryset(self, request):
        return SmartAccountRule.all_objects.select_related('smart_account')


class SmartAccountRuleRunAdmin(ReadOnlyAdmin):
    list_display = ('rule', 'scheduled_for', 'status', 'amount_in', 'amount_out', 'tx_hash', 'message')
    list_filter = ('status',)
    search_fields = ('tx_hash', 'rule__smart_account__contract_address')
    date_hierarchy = 'scheduled_for'


class SmartAccountPayoutAdmin(ReadOnlyAdmin):
    list_display = ('rule_run', 'provider', 'rail', 'status', 'usdt_amount', 'fiat_amount', 'fiat_currency',
                    'deposit_address', 'ramp', 'created_at')
    list_filter = ('provider', 'rail', 'status')
    search_fields = ('deposit_address', 'ramp__internal_id')
    raw_id_fields = ('rule_run', 'journey', 'ramp')


class SmartAccountPagoMovilDestinationAdmin(ReadOnlyAdmin):
    """Phone and cédula are encrypted and not listed; the label carries the
    bank and the phone's last digits."""
    list_display = ('internal_id', 'user', 'label', 'bank_code', 'holder_name', 'created_at', 'deleted_at')
    list_filter = ('bank_code', ('deleted_at', admin.EmptyFieldListFilter))
    search_fields = ('user__username', 'holder_name', 'label')
    raw_id_fields = ('user',)
    exclude = ('phone', 'id_number')


class SmartAccountStandingAuthorizationAdmin(ReadOnlyAdmin):
    list_display = ('internal_id', 'kind', 'user', 'rail', 'payee_address', 'amount_usd', 'frequency',
                    'face_required', 'authorized_at', 'revoked_at', 'revoked_reason')
    list_filter = ('kind', 'rail', 'frequency', ('revoked_at', admin.EmptyFieldListFilter))
    search_fields = ('user__username', 'binding_hash', 'payee_address')
    raw_id_fields = ('user', 'payout_destination', 'pagomovil_destination')


class SmartAccountBeneficiaryAdmin(ReadOnlyAdmin):
    list_display = ('designation_id', 'smart_account', 'beneficiary_user', 'state', 'challenge_window_seconds',
                    'verified_at_designation', 'residence_check', 'disclosure_accepted_at', 'designated_at',
                    'accepted_at', 'declined_at', 'removed_at')
    list_filter = ('state', 'residence_check', 'verified_at_designation')
    search_fields = ('beneficiary_address', 'beneficiary_user__username', 'smart_account__contract_address',
                     'designated_tx', 'accepted_tx')
    raw_id_fields = ('smart_account', 'beneficiary_user')


class SmartAccountClaimAdmin(ReadOnlyAdmin):
    list_display = ('beneficiary_row', 'state', 'initiated_at', 'executable_at', 'cancelled_at', 'executed_at',
                    'owner_notices_sent', 'last_owner_notice_at')
    list_filter = ('state',)
    search_fields = ('initiated_tx', 'cancelled_tx', 'executed_tx',
                     'beneficiary_row__smart_account__contract_address')
    date_hierarchy = 'initiated_at'


class SmartAccountRelayTxAdmin(ReadOnlyAdmin):
    list_display = ('signed_tx_hash', 'smart_account', 'kind', 'source_id', 'status', 'sponsor_nonce',
                    'gas_limit', 'block_number', 'created_at')
    list_filter = ('kind', 'status')
    search_fields = ('signed_tx_hash', 'source_id', 'smart_account__contract_address')
    date_hierarchy = 'created_at'


class SmartAccountPreparedActionAdmin(ReadOnlyAdmin):
    list_display = ('request_id', 'user', 'kind', 'target_address', 'consumed', 'expires_at',
                    'sponsored_batch', 'created_at')
    list_filter = ('kind', 'consumed')
    search_fields = ('request_id', 'user__username', 'target_address', 'signer_address')
    raw_id_fields = ('user', 'smart_account', 'sponsored_batch')
    date_hierarchy = 'created_at'


class SmartAccountTargetAllocationAdmin(ReadOnlyAdmin):
    list_display = ('smart_account', 'total_usd', 'frequency', 'weights', 'created_at', 'updated_at', 'deleted_at')
    list_filter = ('frequency',)
    search_fields = ('smart_account__contract_address', 'smart_account__owner_user__username')
    raw_id_fields = ('smart_account',)

    def get_queryset(self, request):
        return SmartAccountTargetAllocation.all_objects.select_related('smart_account')


class SmartAccountWatchAdmin(ReadOnlyAdmin):
    list_display = ('smart_account', 'kind', 'asset_key', 'currency', 'threshold', 'active',
                    'last_triggered_at', 'created_at', 'deleted_at')
    list_filter = ('kind', 'active')
    search_fields = ('smart_account__contract_address', 'user__username', 'asset_key')
    raw_id_fields = ('smart_account', 'user')

    def get_queryset(self, request):
        return SmartAccountWatch.all_objects.select_related('smart_account', 'user')


class SmartAccountCardSpenderAdmin(admin.ModelAdmin):
    """Card issuers' spenders (decision 35). `allowed` mirrors the factory's
    CardSpenderSet and only the Safe changes it on chain; ops set only the
    label the owner sees. Rows appear from the chain, never by hand."""
    list_display = ('address', 'label', 'allowed', 'set_block', 'set_tx', 'updated_at')
    list_filter = ('allowed',)
    search_fields = ('address', 'label', 'set_tx')
    fields = ('address', 'label', 'allowed', 'set_block', 'set_log_index', 'set_tx', 'created_at', 'updated_at')
    readonly_fields = ('address', 'allowed', 'set_block', 'set_log_index', 'set_tx', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class SmartAccountCardPauseAdmin(ReadOnlyAdmin):
    """The factory's cardPaused flag (Safe-set), mirrored."""
    list_display = ('paused', 'set_block', 'set_tx', 'updated_at')


class SmartAccountCardPullAdmin(ReadOnlyAdmin):
    list_display = ('pulled_at', 'smart_account', 'onchain_rule_id', 'rule', 'spender', 'usd_spent',
                    'usdt_out_wei', 'spent_in_period', 'period_start', 'tx_hash', 'notified_at')
    list_filter = ('spender', ('rule', admin.EmptyFieldListFilter))
    search_fields = ('tx_hash', 'spender', 'smart_account__contract_address', 'smart_account__owner_user__username')
    raw_id_fields = ('smart_account', 'rule', 'event')
    date_hierarchy = 'pulled_at'


class SmartAccountScanCursorAdmin(ReadOnlyAdmin):
    list_display = ('key', 'block_number', 'updated_at')


REGISTRY = (
    (SmartAccount, SmartAccountAdmin),
    (SmartAccountEvent, SmartAccountEventAdmin),
    (SmartAccountCharge, SmartAccountChargeAdmin),
    (SmartAccountForcedSale, SmartAccountForcedSaleAdmin),
    (SmartAccountRule, SmartAccountRuleAdmin),
    (SmartAccountRuleRun, SmartAccountRuleRunAdmin),
    (SmartAccountPayout, SmartAccountPayoutAdmin),
    (SmartAccountStandingAuthorization, SmartAccountStandingAuthorizationAdmin),
    (SmartAccountPagoMovilDestination, SmartAccountPagoMovilDestinationAdmin),
    (SmartAccountBeneficiary, SmartAccountBeneficiaryAdmin),
    (SmartAccountClaim, SmartAccountClaimAdmin),
    (SmartAccountRelayTx, SmartAccountRelayTxAdmin),
    (SmartAccountPreparedAction, SmartAccountPreparedActionAdmin),
    (SmartAccountTargetAllocation, SmartAccountTargetAllocationAdmin),
    (SmartAccountWatch, SmartAccountWatchAdmin),
    (SmartAccountCardSpender, SmartAccountCardSpenderAdmin),
    (SmartAccountCardPause, SmartAccountCardPauseAdmin),
    (SmartAccountCardPull, SmartAccountCardPullAdmin),
    (SmartAccountScanCursor, SmartAccountScanCursorAdmin),
)
