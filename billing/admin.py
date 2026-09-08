from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from .institutions import apply_payment
from .models import (
    BillingObligation,
    BillingPayment,
    BillingSchedule,
    CipSandboxApplicationReceipt,
    CipSandboxMember,
    InstitutionApplication,
    InstitutionConnection,
    ObligationSubject,
    PaymentEffect, PaymentAllocationEntry, SettlementLeg,
)


class ReadOnlyBillingAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class PaymentEffectAdmin(ReadOnlyBillingAdmin):
    list_display = ('public_id', 'business', 'billing_payment', 'effect_type',
                    'commercial_delta_minor', 'commercial_currency', 'created_at')
    search_fields = ('public_id', 'semantic_key', 'billing_payment__public_id')
    list_filter = ('effect_type', 'business')


class PaymentAllocationEntryAdmin(ReadOnlyBillingAdmin):
    list_display = ('id', 'effect', 'obligation', 'commercial_delta_minor', 'allocation_revision')
    search_fields = ('effect__public_id', 'obligation__public_id')


class SettlementLegAdmin(ReadOnlyBillingAdmin):
    list_display = ('public_id', 'billing_payment', 'chain_id', 'transaction_hash',
                    'input_token_symbol', 'gross_units', 'fee_units', 'receiver_net_units')
    search_fields = ('public_id', 'billing_payment__public_id', 'transaction_hash')


class ObligationSubjectAdmin(ReadOnlyBillingAdmin):
    list_display = ('public_id', 'business', 'masked_reference', 'status', 'confio_user')
    list_filter = ('status', 'subject_type', 'business')
    search_fields = ('public_id', 'external_id', 'masked_reference')
    readonly_fields = ('public_id', 'created_at', 'updated_at')


class BillingScheduleAdmin(ReadOnlyBillingAdmin):
    list_display = ('public_id', 'business', 'subject', 'amount_minor', 'currency',
                    'status', 'next_period_start')
    list_filter = ('status', 'currency', 'business')
    search_fields = ('public_id', 'external_reference', 'subject__external_id')
    readonly_fields = ('public_id', 'generated_periods', 'created_at', 'updated_at')


class BillingObligationAdmin(ReadOnlyBillingAdmin):
    list_display = ('public_id', 'business', 'subject', 'period_key',
                    'amount_remaining_minor', 'currency', 'status', 'due_at')
    list_filter = ('status', 'currency', 'business')
    search_fields = ('public_id', 'external_reference', 'subject__external_id')
    readonly_fields = ('public_id', 'amount_paid_minor', 'created_at', 'updated_at')


class BillingPaymentAdmin(ReadOnlyBillingAdmin):
    list_display = ('public_id', 'billing_invoice', 'commercial_amount_minor',
                    'commercial_currency', 'settlement_asset', 'status', 'confirmed_at')
    list_filter = ('status', 'commercial_currency', 'settlement_asset')
    search_fields = ('public_id', 'transaction_hash', 'legacy_payment__internal_id')
    readonly_fields = tuple(field.name for field in BillingPayment._meta.fields)

    def has_add_permission(self, request):
        return False


class InstitutionConnectionAdmin(admin.ModelAdmin):
    list_display = ('public_id', 'business', 'provider', 'mode', 'status', 'live_approved')
    list_filter = ('provider', 'mode', 'status', 'live_approved')
    search_fields = ('public_id', 'business__name', 'provider')
    readonly_fields = ('public_id', 'created_at', 'updated_at')


class InstitutionApplicationAdmin(ReadOnlyBillingAdmin):
    list_display = ('public_id', 'connection', 'billing_payment', 'status',
                    'attempts', 'returned_status', 'updated_at')
    list_filter = ('status', 'connection__provider', 'connection__mode')
    search_fields = ('public_id', 'idempotency_key', 'billing_payment__public_id')
    readonly_fields = ('public_id', 'idempotency_key', 'payload_snapshot',
                       'payment_confirmed_at', 'created_at', 'updated_at')
    actions = ('apply_selected_now', 'queue_selected_for_retry')

    @admin.action(description='Apply selected institution updates now', permissions=['change'])
    def apply_selected_now(self, request, queryset):
        if not self.has_change_permission(request):
            raise PermissionDenied
        applied = 0
        for application_id in queryset.values_list('id', flat=True):
            if apply_payment(application_id) == 'acknowledged':
                applied += 1
                self.log_change(request, self.model.objects.get(pk=application_id),
                                'Requested institution application; acknowledged.')
        self.message_user(request, f'{applied} application(s) acknowledged.', messages.SUCCESS)

    @admin.action(description='Queue selected failed/mismatched updates for retry', permissions=['change'])
    def queue_selected_for_retry(self, request, queryset):
        if not self.has_change_permission(request):
            raise PermissionDenied
        count = 0
        for application in queryset.filter(status__in=('rejected', 'mismatch', 'manual_review')):
            changed = self.model.objects.filter(
                pk=application.pk, status=application.status, leased_at__isnull=True,
            ).update(status='application_pending', available_at=timezone.now(),
                     updated_at=timezone.now())
            if changed:
                self.log_change(request, application, 'Queued institution application retry.')
                count += changed
        self.message_user(request, f'{count} application(s) queued.', messages.SUCCESS)


class CipSandboxMemberAdmin(admin.ModelAdmin):
    list_display = ('public_id', 'member_number', 'subject', 'habilidad',
                    'paid_through', 'version', 'updated_at')
    list_filter = ('habilidad', 'connection')
    search_fields = ('public_id', 'member_number', 'subject__external_id')
    readonly_fields = ('public_id', 'version', 'created_at', 'updated_at')


class CipSandboxApplicationReceiptAdmin(ReadOnlyBillingAdmin):
    list_display = ('public_id', 'member', 'outcome', 'idempotency_key', 'created_at')
    list_filter = ('outcome', 'connection')
    search_fields = ('public_id', 'idempotency_key', 'member__member_number')
    readonly_fields = tuple(
        field.name for field in CipSandboxApplicationReceipt._meta.fields)

    def has_add_permission(self, request):
        return False
