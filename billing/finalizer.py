from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from blockchain.models import PAYMENT_BATCH_KINDS, SponsoredBatch
from payments.models import Invoice, PaymentTransaction

from .models import (
    BillingEvent,
    BillingInvoice,
    BillingInvoiceStatus,
    BillingObligation,
    BillingOutboxMessage,
    BillingPayment,
    BillingPaymentIntent,
    BillingPaymentStatus,
    ObligationStatus,
    SettlementLeg,
)
from .services import post_full_balance_payment
from .institutions import create_payment_applications


class ReceiptPending(Exception):
    pass


class FinalizationRejected(ValueError):
    pass


@dataclass(frozen=True)
class FinalizationResult:
    transitioned: bool
    outcome: str
    payment_internal_id: str = ''
    transaction_hash: str = ''


def _notification_after_commit(payment_id):
    # Lazy import avoids a module cycle with the Celery task entry point.
    from payments.tasks import _send_bsc_payment_notifications

    _send_bsc_payment_notifications(payment_id)


def _lock_billing_context(legacy_payment_id):
    billing_payment_id = (
        BillingPayment.objects.filter(legacy_payment_id=legacy_payment_id)
        .values_list('id', flat=True).first()
    )
    if billing_payment_id is None:
        return None
    billing_payment = BillingPayment.objects.select_for_update().get(
        id=billing_payment_id)
    intent = BillingPaymentIntent.objects.select_for_update().get(
        id=billing_payment.payment_intent_id)
    invoice = BillingInvoice.objects.select_for_update().get(
        id=billing_payment.billing_invoice_id)
    if intent.billing_invoice_id != invoice.id:
        raise FinalizationRejected('billing payment intent belongs to another invoice')
    return billing_payment, intent, invoice


def _append_payment_event(*, billing_payment, invoice, event_type, status,
                          transition_key, error='', settlement_leg=None):
    settlement = {
        'asset': billing_payment.settlement_asset,
        'decimals': billing_payment.settlement_decimals,
        'gross_units': str(billing_payment.gross_units),
        'fee_units': str(billing_payment.fee_units),
        'receiver_net_units': str(billing_payment.receiver_net_units),
        'chain': billing_payment.chain,
        'transaction_hash': billing_payment.transaction_hash,
    }
    if settlement_leg is not None:
        settlement = {
            'id': settlement_leg.public_id,
            'chain': billing_payment.chain,
            'chain_id': settlement_leg.chain_id,
            'contract_version': settlement_leg.contract_version,
            'input_asset': settlement_leg.input_token_symbol,
            'input_decimals': settlement_leg.input_token_decimals,
            'gross_units': str(settlement_leg.gross_units),
            'fee_units': str(settlement_leg.fee_units),
            'input_net_units': str(settlement_leg.receiver_net_units),
            'routed': settlement_leg.routed,
            'output_asset': settlement_leg.output_token_symbol,
            'output_decimals': settlement_leg.output_token_decimals,
            'output_units': str(settlement_leg.output_units),
            'transaction_hash': settlement_leg.transaction_hash,
            'block_number': settlement_leg.block_number,
            'transaction_index': settlement_leg.transaction_index,
            'log_index': settlement_leg.log_index,
        }
    payload = {
        'object': 'event',
        'type': event_type,
        'data': {
            'object': {
                'id': billing_payment.public_id,
                'object': 'payment',
                'status': status,
                'billing_invoice': invoice.public_id,
                'payment_intent': billing_payment.payment_intent.public_id,
                'commercial_amount': {
                    'minor_units': billing_payment.commercial_amount_minor,
                    'currency': billing_payment.commercial_currency,
                },
                'settlement': settlement,
            },
        },
    }
    if error:
        payload['data']['object']['failure_code'] = error
    event, _ = BillingEvent.objects.get_or_create(
        business_id=invoice.business_id,
        transition_key=transition_key,
        defaults={
            'event_type': event_type,
            'mode': invoice.subject.mode,
            'aggregate_type': 'payment',
            'aggregate_id': billing_payment.public_id,
            'aggregate_version': invoice.version,
            'correlation_id': billing_payment.public_id,
            'causation_id': billing_payment.legacy_payment.internal_id,
            'payload': payload,
        },
    )
    BillingOutboxMessage.objects.get_or_create(
        event=event, defaults={'available_at': timezone.now()})
    return event


@transaction.atomic
def finalize_bsc_payment(*, payment_id: int, batch_id: int) -> FinalizationResult:
    """Finalize legacy and billing state from one locked chain-evidence row."""
    # The lock order is shared with every caller: chain evidence, legacy
    # payment, legacy invoice, billing payment/intent/invoice, obligations.
    batch = SponsoredBatch.objects.select_for_update().get(id=batch_id)
    payment = PaymentTransaction.objects.select_for_update().get(id=payment_id)

    if payment.status != 'SUBMITTED':
        return FinalizationResult(
            transitioned=False, outcome=payment.status.lower(),
            payment_internal_id=payment.internal_id,
            transaction_hash=payment.transaction_hash)
    if (batch.kind not in PAYMENT_BATCH_KINDS
            or batch.source_id != payment.id
            or (payment.transaction_hash and batch.tx_hash != payment.transaction_hash)):
        raise FinalizationRejected('batch does not belong to payment')
    if batch.status in ('signed', 'sent'):
        raise ReceiptPending(batch.status)

    legacy_invoice = Invoice.objects.select_for_update().get(id=payment.invoice_id)
    billing_context = _lock_billing_context(payment.id)
    settlement_leg = None
    if billing_context and batch.status == 'confirmed':
        billing_payment = billing_context[0]
        settlement_legs = list(
            SettlementLeg.objects.select_for_update()
            .filter(billing_payment_id=billing_payment.id).order_by('id')[:2]
        )
        if not settlement_legs:
            raise ReceiptPending('settlement_evidence')
        if len(settlement_legs) != 1:
            raise FinalizationRejected('billing payment has ambiguous settlement evidence')
        settlement_leg = settlement_legs[0]
        if (settlement_leg.transaction_hash.lower() != batch.tx_hash.lower()
                or settlement_leg.block_number != batch.block_number
                or settlement_leg.block_hash.lower() != batch.block_hash.lower()):
            raise FinalizationRejected('settlement evidence does not match finalized batch')

    if batch.status != 'confirmed':
        payment.status = 'FAILED'
        payment.error_message = f'batch_{batch.status}'
        payment.save(update_fields=('status', 'error_message', 'updated_at'))
        if billing_context:
            billing_payment, intent, billing_invoice = billing_context
            billing_payment.status = BillingPaymentStatus.FAILED
            billing_payment.save(update_fields=('status', 'updated_at'))
            intent.status = 'failed'
            intent.last_payment_error = payment.error_message
            intent.save(update_fields=('status', 'last_payment_error', 'updated_at'))
            if billing_invoice.status == BillingInvoiceStatus.PAYMENT_PENDING:
                obligation_ids = list(
                    billing_invoice.obligation_links.order_by('obligation_id')
                    .values_list('obligation_id', flat=True)
                )
                locked_obligations = list(
                    BillingObligation.objects.select_for_update()
                    .filter(id__in=obligation_ids).order_by('id')
                )
                billing_invoice.status = BillingInvoiceStatus.OPEN
                billing_invoice.version += 1
                billing_invoice.save(update_fields=('status', 'version', 'updated_at'))
                BillingObligation.objects.filter(
                    id__in=[
                        obligation.id for obligation in locked_obligations
                        if obligation.status == ObligationStatus.PAYMENT_PENDING
                    ],
                ).update(status=ObligationStatus.OPEN, updated_at=timezone.now())
            _append_payment_event(
                billing_payment=billing_payment,
                invoice=billing_invoice,
                event_type='payment.failed',
                status='failed',
                transition_key=f'payment:{billing_payment.id}:failed',
                error=payment.error_message,
            )
        return FinalizationResult(
            transitioned=True, outcome='failed',
            payment_internal_id=payment.internal_id,
            transaction_hash=payment.transaction_hash)

    payment.status = 'CONFIRMED'
    payment.error_message = ''
    payment.save(update_fields=('status', 'error_message', 'updated_at'))
    if legacy_invoice.status != 'PAID':
        legacy_invoice.status = 'PAID'
        legacy_invoice.paid_at = timezone.now()
        legacy_invoice.paid_by_user_id = payment.payer_user_id
        legacy_invoice.paid_by_business_id = payment.payer_business_id
        legacy_invoice.save(update_fields=(
            'status', 'paid_at', 'paid_by_user', 'paid_by_business', 'updated_at'))

    if billing_context:
        billing_payment, intent, billing_invoice = billing_context
        if billing_payment.status != BillingPaymentStatus.PROCESSING:
            raise FinalizationRejected(
                f'billing payment is not processing: {billing_payment.status}')
        if intent.status != 'processing':
            raise FinalizationRejected(f'payment intent is not processing: {intent.status}')
        billing_payment.status = BillingPaymentStatus.CONFIRMED
        billing_payment.transaction_hash = batch.tx_hash
        billing_payment.confirmed_at = timezone.now()
        billing_payment.save(update_fields=(
            'status', 'transaction_hash', 'confirmed_at', 'updated_at'))
        intent.status = 'succeeded'
        intent.last_payment_error = ''
        intent.save(update_fields=('status', 'last_payment_error', 'updated_at'))
        effect = post_full_balance_payment(
            billing_payment_id=billing_payment.id,
            semantic_key=f'payment:{billing_payment.id}:confirmed')
        create_payment_applications(payment=billing_payment, effect=effect)
        billing_invoice.refresh_from_db()
        _append_payment_event(
            billing_payment=billing_payment,
            invoice=billing_invoice,
            event_type='payment.confirmed',
            status='confirmed',
            transition_key=f'payment:{billing_payment.id}:confirmed',
            settlement_leg=settlement_leg,
        )

    transaction.on_commit(
        lambda confirmed_payment_id=payment.id:
        _notification_after_commit(confirmed_payment_id))
    return FinalizationResult(
        transitioned=True, outcome='confirmed',
        payment_internal_id=payment.internal_id,
        transaction_hash=payment.transaction_hash)
