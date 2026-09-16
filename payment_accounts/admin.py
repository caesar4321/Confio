from django.contrib import admin
from .models import ThirdPartyPayinSwitch, PayinAdmission


@admin.register(ThirdPartyPayinSwitch)
class ThirdPartyPayinSwitchAdmin(admin.ModelAdmin):
    list_display = ('provider', 'country', 'rail', 'confio_account', 'enabled', 'updated_at')
    list_filter = ('provider', 'country', 'rail', 'enabled')
    raw_id_fields = ('confio_account',)
    readonly_fields = ('updated_at',)


@admin.register(PayinAdmission)
class PayinAdmissionAdmin(admin.ModelAdmin):
    list_display = ('entry', 'allowed', 'reason', 'country', 'rail', 'updated_at')
    list_filter = ('allowed', 'country', 'rail', 'reason')
    readonly_fields = tuple(field.name for field in PayinAdmission._meta.fields)
    actions = ('reassess_deposits',)

    @admin.action(description='Reassess deposits against current switches (does not move funds)', permissions=['change'])
    def reassess_deposits(self, request, queryset):
        from .payin_admission import assess
        count = 0
        for admission in queryset.select_related('entry__financial_account__provider_profile__identity_verification'):
            assess(admission.entry)
            self.log_change(request, admission, 'Reassessed pay-in admission; no funds moved.')
            count += 1
        self.message_user(request, f'Reassessed {count} deposits. No funds moved or journeys resumed.')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

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
    list_display = ('internal_id', 'confio_account', 'direction', 'corridor', 'receiving_rail', 'counterparty', 'input_amount', 'current_stage', 'wallet_credit_usd', 'failure_code', 'updated_at')
    list_filter = ('direction', 'stage', 'local_account__country', 'local_account__asset')
    search_fields = ('internal_id', 'confio_account__user__username', 'confio_account__user__email', 'failure_code')
    ordering = ('-created_at',)
    readonly_fields = tuple(field.name for field in InfiniaJourney._meta.fields)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('confio_account__user', 'confio_account__business', 'local_account', 'money_flow', 'bridge', 'wallet_conversion', 'funding_credit')

    @admin.display(description='Sender / recipient')
    def counterparty(self, obj):
        from .incoming_details import incoming_credit, sender_details
        if obj.direction == 'to_wallet':
            return (sender_details(incoming_credit(obj)) or {}).get('name') or 'Unknown'
        return (obj.destination_snapshot or {}).get('display_label') or 'See destination details'

    @admin.display(description='Country / currency')
    def corridor(self, obj):
        return f'{obj.local_account.country} / {obj.local_account.asset}'

    @admin.display(description='Receiving rail')
    def receiving_rail(self, obj):
        return obj.local_account.payin_rail if obj.direction == 'to_wallet' else '—'

    @admin.display(description='Input')
    def input_amount(self, obj):
        return f'{obj.money_flow.source_amount} {obj.money_flow.source_asset}'

    @admin.display(description='End-to-end status')
    def current_stage(self, obj):
        from .activity import display_stage
        return display_stage(obj)

    @admin.display(description='Delivered wallet USD')
    def wallet_credit_usd(self, obj):
        from .monitoring import delivered_usd
        return delivered_usd(obj) if obj.direction == 'to_wallet' else '—'

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


from .models import CobreJourney

from .models import AutomaticPayin


class AutomaticPayinAdmin(admin.ModelAdmin):
    list_display = ('id', 'deposit_account', 'deposit_amount', 'status', 'reason', 'updated_at')
    list_filter = ('status', 'reason', 'entry__financial_account__country')
    ordering = ('-updated_at',)
    readonly_fields = tuple(field.name for field in AutomaticPayin._meta.fields)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('entry__financial_account')

    @admin.display(description='Financial account')
    def deposit_account(self, obj):
        return obj.entry.financial_account.internal_id

    @admin.display(description='Fiat received')
    def deposit_amount(self, obj):
        return f'{obj.entry.amount} {obj.entry.asset}'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


from django import forms
from django.contrib import messages
from django.core import signing
from django.db import transaction
from django.utils import timezone
from .models import LimitIncreaseRequest


_SHOWN_STATUS_SALT = 'limit-increase-admin-shown-status'


class LimitIncreaseRequestAdminForm(forms.ModelForm):
    # The status the reviewer actually saw, signed when the page was rendered.
    # The instance a POST re-reads already carries any change made meanwhile,
    # so neither it nor form.initial can tell what the reviewer decided on.
    loaded_status = forms.CharField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = LimitIncreaseRequest
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and not self.is_bound:
            self.fields['loaded_status'].initial = signing.dumps(self.instance.status, salt=_SHOWN_STATUS_SALT)

    def shown_status(self):
        try:
            return signing.loads(self.data.get('loaded_status') or '', salt=_SHOWN_STATUS_SALT)
        except signing.BadSignature:
            return None

    def clean(self):
        data = super().clean()
        if self.instance.pk:
            shown = self.shown_status()
            if shown is None:
                raise forms.ValidationError('Recarga la página e inténtalo de nuevo.')
            # A status the reviewer changed, on a request that moved since they
            # saw it (a sync or a forward), is refused rather than applied.
            current = LimitIncreaseRequest.objects.filter(pk=self.instance.pk).values_list('status', flat=True).first()
            if data.get('status') not in (None, shown) and current != shown:
                raise forms.ValidationError(
                    f'Esta solicitud cambió mientras la revisabas (ahora: {current}). Recarga la página.')
        return data


class LimitIncreaseRequestAdmin(admin.ModelAdmin):
    """EDD handoff diagnostics and recovery. Submissions are sent automatically;
    the action below can retry a pending handoff. Infinia decides the limit.
    """
    list_display = ('internal_id', 'confio_account', 'status', 'didit_status', 'income_type',
                    'expected_monthly_usd', 'submitted_at')
    list_filter = ('status', 'didit_status', 'income_type', 'provider')
    raw_id_fields = ('confio_account',)
    readonly_fields = ('internal_id', 'confio_account', 'provider', 'income_type', 'occupation',
                       'expected_monthly_usd', 'source_of_funds', 'didit_session_id', 'didit_status',
                       'provider_documents', 'forwarded_at', 'submitted_at', 'reviewed_at', 'created_at', 'updated_at')
    fields = readonly_fields[:10] + ('status', 'user_message', 'reviewer_note') + readonly_fields[10:] + (
        'loaded_status',)
    actions = ('forward_to_provider',)
    form = LimitIncreaseRequestAdminForm
    REVIEWER_FIELDS = ('status', 'user_message', 'reviewer_note')

    @admin.action(description='Forward EDD documents to the provider (uploads to the account owner)',
                  permissions=['change'])
    def forward_to_provider(self, request, queryset):
        from .edd import forward_to_provider
        for row in queryset:
            try:
                forward_to_provider(row)
                self.log_change(request, row, 'Forwarded EDD documents to the provider owner.')
                self.message_user(request, f'{row.internal_id}: forwarded.')
            except Exception as exc:  # noqa: BLE001 — surfaced to the reviewer per row
                self.message_user(request, f'{row.internal_id}: {exc}', level='error')

    def save_model(self, request, obj, form, change):
        if not change:
            return super().save_model(request, obj, form, change)
        # The status counts as edited only if it differs from what the reviewer
        # SAW; the browser re-posts the displayed value even when untouched.
        shown = form.shown_status() if hasattr(form, 'shown_status') else form.initial.get('status')
        status_edited = obj.status != shown
        changed = [field for field in ('user_message', 'reviewer_note') if field in form.changed_data]
        if status_edited:
            changed.append('status')
        if not changed:
            return None
        # Only what the reviewer changed is written, on a freshly locked row: a
        # sync or a forward committed after the page loaded is never undone.
        with transaction.atomic():
            current = LimitIncreaseRequest.objects.select_for_update().get(pk=obj.pk)
            if status_edited and current.status != shown:
                self.message_user(request, 'La solicitud cambió mientras la revisabas; no se guardó. Recarga la página.',
                                  level=messages.ERROR)
                return None
            for field in changed:
                setattr(current, field, getattr(obj, field))
            update = [*changed, 'updated_at']
            if status_edited and current.status != 'submitted':
                current.reviewed_at = timezone.now()
                update.append('reviewed_at')
            current.save(update_fields=update)
        return None

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class CobreJourneyAdmin(admin.ModelAdmin):
    list_display = ('internal_id', 'direction', 'stage', 'failure_code', 'updated_at')
    list_filter = ('direction', 'stage')
    readonly_fields = tuple(field.name for field in CobreJourney._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


from .models import AccountActivation


class AccountActivationAdmin(admin.ModelAdmin):
    list_display = ('internal_id', 'confio_account', 'country', 'asset', 'amount', 'status', 'updated_at')
    list_filter = ('status', 'country', 'asset')
    readonly_fields = tuple(field.name for field in AccountActivation._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


from .models import BrebLocationCheck


class BrebLocationCheckAdmin(admin.ModelAdmin):
    """Compliance evidence: read-only, never added or deleted from the admin."""
    list_display = ('created_at', 'confio_account', 'passed', 'platform', 'ip_country', 'accuracy_m', 'reason')
    list_filter = ('passed', 'platform', 'ip_country')
    readonly_fields = tuple(field.name for field in BrebLocationCheck._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
