"""
Celery tasks for BSC invoice payments — the receipt-resolution half of
payments/bsc_flow (mirror of send.tasks.confirm_bsc_send).

confirmed → PaymentTransaction CONFIRMED + invoice PAID + ledger movements
(payer −gross, merchant +net; the 0.9% fee is the difference and lives in
the treasury, not the merchant's ledger) + PAYMENT_SENT/PAYMENT_RECEIVED
pushes (payload parity with blockchain/tasks.confirm_payment_transaction).
reverted/noop_failed → FAILED (funds untouched; the payer retries).
"""
import logging
from decimal import Decimal

from celery import shared_task

logger = logging.getLogger(__name__)

# One shared table (notifications/token_display). The private copy here
# omitted CUSD, so a legacy payment read "Pagaste 5 CUSD a …".
from notifications.token_display import token_label


@shared_task(name='payments.confirm_bsc_payment', bind=True, max_retries=20)
def confirm_bsc_payment(self, payment_id: int, batch_id: int):
    from billing.finalizer import (
        FinalizationRejected,
        ReceiptPending,
        finalize_bsc_payment,
    )
    from blockchain.models import SponsoredBatch
    from .models import Invoice, PaymentTransaction

    try:
        result = finalize_bsc_payment(payment_id=payment_id, batch_id=batch_id)
    except ReceiptPending:
        raise self.retry(countdown=15)
    except FinalizationRejected as exc:
        logger.error('[PAY][BSC] refusing payment %s finalization: %s',
                     payment_id, exc)
        return
    except (PaymentTransaction.DoesNotExist, SponsoredBatch.DoesNotExist,
            Invoice.DoesNotExist):
        return

    if not result.transitioned:
        return
    if result.outcome == 'confirmed':
        logger.info('[PAY][BSC] %s confirmed: %s',
                    result.payment_internal_id, result.transaction_hash)
    else:
        logger.warning('[PAY][BSC] %s failed: batch %s',
                       result.payment_internal_id, batch_id)


def _send_bsc_payment_notifications(payment_id: int):
    """Send user-visible effects after the financial transaction commits."""
    from notifications import utils as notif_utils
    from notifications.models import NotificationType as NotifType
    from .models import PaymentTransaction

    try:
        p = PaymentTransaction.objects.select_related(
            'payer_user', 'merchant_business', 'merchant_account_user',
            'merchant_account', 'payer_account', 'payer_business',
        ).get(id=payment_id, status='CONFIRMED')
    except PaymentTransaction.DoesNotExist:
        return

    from .bsc_flow import WAD, payment_fee_wei
    gross = Decimal(p.amount)
    gross_wei = int(gross * WAD)
    # Exact wei parity with the batch that executed (ceiling fee).
    net = (Decimal(gross_wei - payment_fee_wei(gross_wei)) / WAD).quantize(
        Decimal('0.000001'))
    merchant_name = p.merchant_display_name or (
        p.merchant_business.name if p.merchant_business_id else 'Comercio')
    payer_name = p.payer_display_name or 'Cliente'

    token = token_label(p.token_type)
    amount_str = f'{gross:.2f}'.rstrip('0').rstrip('.')
    common = {
        'transaction_id': str(p.internal_id),
        'internal_id': str(p.internal_id),
        'transaction_hash': p.transaction_hash,
        'amount': amount_str,
        'token_type': p.token_type,
        'sender_name': payer_name,
        'recipient_name': merchant_name,
        'transaction_type': 'payment',
    }
    # The merchant received gross MINUS the 0.9% fee — this module's own
    # docstring says "payer -gross, merchant +net" — but both notifications
    # were built from `amount_str`, the gross. `net` was computed above and
    # then discarded, so every merchant was told they had received 0.9% more
    # than the contract actually transferred to them.
    net_str = f'{net:.2f}'.rstrip('0').rstrip('.')
    merchant_data = dict(common, amount=net_str, gross_amount=amount_str,
                         fee_amount=f'{(gross - net):.6f}')
    try:
        if p.merchant_account_user_id:
            notif_utils.create_notification(
                user=p.merchant_account_user,
                account=p.merchant_account,
                business=p.merchant_business,
                notification_type=NotifType.PAYMENT_RECEIVED,
                title='Pago recibido',
                message=f'Recibiste {net_str} {token} de {payer_name}',
                data=merchant_data,
                related_object_type='PaymentTransaction',
                related_object_id=str(p.internal_id),
            )
        if p.payer_user_id:
            notif_utils.create_notification(
                user=p.payer_user,
                account=p.payer_account,
                business=p.payer_business,
                notification_type=NotifType.PAYMENT_SENT,
                title='Pago enviado',
                message=f'Pagaste {amount_str} {token} a {merchant_name}',
                data=dict(common),
                related_object_type='PaymentTransaction',
                related_object_id=str(p.internal_id),
            )
    except Exception:  # noqa: BLE001
        logger.exception('payment notifications failed for %s', p.internal_id)

    logger.info('[PAY][BSC] %s notifications sent (%s %s): %s',
                p.internal_id, gross, token, p.transaction_hash)


@shared_task(name='payments.reconcile_stranded_bsc_payments')
def reconcile_stranded_bsc_payments():
    """Repair invoices whose batch outlived the request that broadcast it.

    Two gaps, both leaving a merchant paid on chain and an invoice pending:

    - the sponsor marks the batch 'sent' and the process dies before
      payment_tx.save(), so the payment keeps its placeholder hash and its
      PENDING_BLOCKCHAIN status forever. The signed-batch reconciler only
      recovers rows still in 'signed' and its convergence pass is
      presale-only, so nothing else looks at this.
    - the payment reaches SUBMITTED but confirm_bsc_payment is never queued,
      or exhausts its retries while the receipt worker settles later.

    Both are repaired from the batch, which is the durable record: it is
    written before broadcast and carries the real hash.
    """
    from blockchain.models import PAYMENT_BATCH_KINDS, SponsoredBatch
    from django.db import transaction
    from django.db.models import Exists, OuterRef, Q
    from .models import PaymentTransaction

    TERMINAL = ('confirmed', 'reverted', 'dropped', 'reorged', 'noop_failed')
    RECONCILABLE = ('sent',) + TERMINAL

    repaired = requeued = 0
    payment_batches = SponsoredBatch.objects.filter(
        source_id=OuterRef('pk'), kind__in=PAYMENT_BATCH_KINDS)
    # Select the *oldest actionable payments*, not the newest batch rows.
    # A fixed newest-300 batch window permanently starved an old unresolved
    # payment whenever normal traffic kept adding more than 300 newer rows.
    candidates = list(
        PaymentTransaction.objects
        .filter(status__in=('PENDING_BLOCKCHAIN', 'SUBMITTED'))
        .annotate(
            has_live_batch=Exists(payment_batches.filter(
                status__in=('sent', 'confirmed'))),
            has_hash_batch=Exists(payment_batches.filter(
                tx_hash=OuterRef('transaction_hash'), status__in=RECONCILABLE)),
        )
        .filter(
            Q(status='PENDING_BLOCKCHAIN', has_live_batch=True)
            | Q(status='SUBMITTED', has_hash_batch=True)
        )
        .order_by('updated_at', 'id')
        .values_list('id', flat=True)[:300]
    )

    for payment_id in candidates:
        snapshot = PaymentTransaction.objects.filter(id=payment_id).only(
            'status', 'transaction_hash').first()
        if snapshot is None:
            continue
        batch_query = SponsoredBatch.objects.filter(
            source_id=payment_id, kind__in=PAYMENT_BATCH_KINDS)
        if snapshot.status == 'PENDING_BLOCKCHAIN':
            batch = batch_query.filter(status__in=('sent', 'confirmed')).first()
        elif snapshot.status == 'SUBMITTED':
            batch = batch_query.filter(
                tx_hash=snapshot.transaction_hash, status__in=RECONCILABLE).first()
        else:
            continue
        if batch is None:
            continue

        with transaction.atomic():
            # Match the confirmer's lock order and recheck after locking.
            batch = SponsoredBatch.objects.select_for_update().get(id=batch.id)
            p = PaymentTransaction.objects.select_for_update().get(id=payment_id)

            if p.status == 'PENDING_BLOCKCHAIN':
                if (batch.source_id != p.id
                        or batch.kind not in PAYMENT_BATCH_KINDS
                        or batch.status not in ('sent', 'confirmed')):
                    continue
                p.transaction_hash = batch.tx_hash
                p.status = 'SUBMITTED'
                p.save(update_fields=['transaction_hash', 'status', 'updated_at'])
                repaired += 1
                logger.warning(
                    '[PAY][BSC] repaired %s: batch %s was %s while the payment '
                    'was still PENDING_BLOCKCHAIN',
                    p.internal_id, batch.id, batch.status)

            if (p.status == 'SUBMITTED'
                    and batch.source_id == p.id
                    and batch.kind in PAYMENT_BATCH_KINDS
                    and batch.tx_hash == p.transaction_hash
                    and batch.status in RECONCILABLE):
                transaction.on_commit(
                    lambda pid=p.id, bid=batch.id:
                    confirm_bsc_payment.apply_async(args=[pid, bid])
                )
                requeued += 1
    if repaired or requeued:
        logger.info('[PAY][BSC] reconcile: %s repaired, %s re-queued',
                    repaired, requeued)
    return {'repaired': repaired, 'requeued': requeued}
