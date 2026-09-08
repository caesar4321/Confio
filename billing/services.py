from django.db import transaction
from django.utils import timezone

from .models import (
    BillingInvoice,
    BillingInvoiceStatus,
    BillingObligation,
    BillingPayment,
    BillingPaymentStatus,
    ObligationStatus,
    PaymentAllocationEntry,
    PaymentEffect,
)


class JournalInvariantError(ValueError):
    pass


@transaction.atomic
def post_full_balance_payment(*, billing_payment_id: int, semantic_key: str):
    """Post one confirmed pilot payment into the immutable allocation journal.

    V1 intentionally accepts only exact full-balance invoices and obligations.
    The locks make projection updates deterministic; the semantic key makes a
    finalizer retry return the original effect.
    """
    payment = (
        BillingPayment.objects.select_for_update()
        .select_related('billing_invoice')
        .get(id=billing_payment_id)
    )
    invoice = BillingInvoice.objects.select_for_update().get(
        id=payment.billing_invoice_id)

    existing = PaymentEffect.objects.filter(
        business_id=invoice.business_id, semantic_key=semantic_key).first()
    if existing:
        if existing.billing_payment_id != payment.id:
            raise JournalInvariantError('semantic key belongs to another payment')
        return existing

    if payment.status != BillingPaymentStatus.CONFIRMED:
        raise JournalInvariantError('payment must be confirmed before journal posting')
    if invoice.status not in (
        BillingInvoiceStatus.OPEN,
        BillingInvoiceStatus.PAYMENT_PENDING,
        BillingInvoiceStatus.PAST_DUE,
    ):
        raise JournalInvariantError(f'invoice is not collectible: {invoice.status}')
    if payment.commercial_currency != invoice.currency:
        raise JournalInvariantError('payment and invoice currencies differ')
    if payment.commercial_amount_minor != invoice.amount_remaining_minor:
        raise JournalInvariantError('pilot requires exact invoice full-balance payment')

    links = list(invoice.obligation_links.order_by('allocation_order', 'id'))
    if not links:
        raise JournalInvariantError('invoice has no obligations')
    obligation_ids = sorted(link.obligation_id for link in links)
    obligations = {
        obligation.id: obligation
        for obligation in BillingObligation.objects.select_for_update()
        .filter(id__in=obligation_ids).order_by('id')
    }
    if len(obligations) != len(obligation_ids):
        raise JournalInvariantError('invoice references a missing obligation')

    selected_total = 0
    for link in links:
        obligation = obligations[link.obligation_id]
        if obligation.business_id != invoice.business_id:
            raise JournalInvariantError('cross-tenant obligation link')
        if obligation.subject_id != invoice.subject_id:
            raise JournalInvariantError('cross-subject obligation link')
        if obligation.mode != invoice.subject.mode:
            raise JournalInvariantError('cross-mode obligation link')
        if obligation.currency != invoice.currency:
            raise JournalInvariantError('obligation and invoice currencies differ')
        if obligation.status not in (
            ObligationStatus.OPEN,
            ObligationStatus.PAYMENT_PENDING,
            ObligationStatus.PAST_DUE,
        ):
            raise JournalInvariantError(
                f'obligation is not collectible: {obligation.status}')
        if link.selected_amount_minor != obligation.amount_remaining_minor:
            raise JournalInvariantError('pilot requires exact obligation full balance')
        selected_total += link.selected_amount_minor

    if selected_total != invoice.amount_remaining_minor:
        raise JournalInvariantError('invoice links do not reconcile to amount remaining')

    effect = PaymentEffect.objects.create(
        business_id=invoice.business_id,
        semantic_key=semantic_key,
        effect_type='payment',
        billing_payment=payment,
        commercial_currency=invoice.currency,
        commercial_delta_minor=selected_total,
        provenance={
            'billing_payment_id': payment.public_id,
            'legacy_payment_id': payment.legacy_payment.internal_id,
        },
    )
    PaymentAllocationEntry.objects.bulk_create([
        PaymentAllocationEntry(
            effect=effect,
            obligation_id=link.obligation_id,
            commercial_delta_minor=link.selected_amount_minor,
            allocation_order=link.allocation_order,
            allocation_revision=1,
        )
        for link in links
    ])

    paid_at = payment.confirmed_at or timezone.now()
    for obligation in obligations.values():
        obligation.amount_paid_minor += obligation.amount_remaining_minor
        obligation.amount_remaining_minor = 0
        obligation.status = ObligationStatus.PAID
        obligation.save(update_fields=(
            'amount_paid_minor', 'amount_remaining_minor', 'status', 'updated_at'))

    invoice.amount_paid_minor += invoice.amount_remaining_minor
    invoice.amount_remaining_minor = 0
    invoice.status = BillingInvoiceStatus.PAID
    invoice.paid_at = paid_at
    invoice.version += 1
    invoice.save(update_fields=(
        'amount_paid_minor', 'amount_remaining_minor', 'status', 'paid_at',
        'version', 'updated_at'))
    return effect
