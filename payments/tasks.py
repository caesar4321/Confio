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
from django.utils import timezone

logger = logging.getLogger(__name__)

TOKEN_DISPLAY = {'CUSD_PLUS': 'cUSD+', 'USDT': 'USDT', 'CONFIO': 'CONFIO'}

# Batch kinds this task is allowed to settle (audit 2026-07-31 P2 isolation).
PAY_KINDS = ('pay_cusd_plus', 'pay_usdt', 'pay_confio')




@shared_task(name='payments.confirm_bsc_payment', bind=True, max_retries=20)
def confirm_bsc_payment(self, payment_id: int, batch_id: int):
    from blockchain.models import SponsoredBatch
    from notifications import utils as notif_utils
    from notifications.models import NotificationType as NotifType
    from .models import PaymentTransaction

    try:
        p = PaymentTransaction.objects.select_related(
            'invoice', 'payer_user', 'merchant_business', 'merchant_account',
            'payer_account',
        ).get(id=payment_id)
        batch = SponsoredBatch.objects.get(id=batch_id)
    except (PaymentTransaction.DoesNotExist, SponsoredBatch.DoesNotExist):
        return
    if p.status != 'SUBMITTED':
        return  # already resolved

    # Isolation (audit 2026-07-31 P2).
    if (batch.kind not in PAY_KINDS
            or batch.source_id != p.id
            or (p.transaction_hash and batch.tx_hash != p.transaction_hash)):
        logger.error('[PAY][BSC] batch %s does not match payment %s — refusing to settle', batch.id, p.id)
        return

    if batch.status in ('signed', 'sent'):
        raise self.retry(countdown=15)

    if batch.status != 'confirmed':  # reverted / noop_failed / reorged
        p.status = 'FAILED'
        p.error_message = f'batch_{batch.status}'
        p.save(update_fields=['status', 'error_message', 'updated_at'])
        logger.warning('[PAY][BSC] %s failed: batch %s %s',
                       p.internal_id, batch.id, batch.status)
        return

    # ONE transaction. These were two independent saves, and the retry guard
    # above returns as soon as the payment leaves SUBMITTED — so a worker that
    # died between them left the payment CONFIRMED, the invoice PENDING, and
    # nothing that would ever revisit it. The invoice must become PAID with
    # the payment or not at all.
    from django.db import transaction as _db_tx
    with _db_tx.atomic():
        p.status = 'CONFIRMED'
        p.save(update_fields=['status', 'updated_at'])

        invoice = p.invoice
        if invoice and invoice.status != 'PAID':
            invoice.status = 'PAID'
            invoice.paid_at = timezone.now()
            invoice.paid_by_user = p.payer_user
            invoice.paid_by_business = p.payer_business
            invoice.save(update_fields=[
                'status', 'paid_at', 'paid_by_user', 'paid_by_business', 'updated_at',
            ])

    from .bsc_flow import WAD, payment_fee_wei
    gross = Decimal(p.amount)
    gross_wei = int(gross * WAD)
    # Exact wei parity with the batch that executed (ceiling fee).
    net = (Decimal(gross_wei - payment_fee_wei(gross_wei)) / WAD).quantize(
        Decimal('0.000001'))
    merchant_name = p.merchant_display_name or (
        p.merchant_business.name if p.merchant_business_id else 'Comercio')
    payer_name = p.payer_display_name or 'Cliente'

    token = TOKEN_DISPLAY.get((p.token_type or '').upper(), p.token_type)
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

    logger.info('[PAY][BSC] %s confirmed (%s %s): %s',
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
    from blockchain.models import SponsoredBatch
    from .models import PaymentTransaction

    TERMINAL = ('confirmed', 'reverted', 'dropped', 'reorged', 'noop_failed')

    repaired = requeued = 0
    batches = (SponsoredBatch.objects
               .filter(kind__in=PAY_KINDS, status__in=('sent',) + TERMINAL)
               .exclude(source_id=None).order_by('-id')[:300])
    for batch in batches:
        p = PaymentTransaction.objects.filter(id=batch.source_id).first()
        if p is None:
            continue
        if p.status == 'PENDING_BLOCKCHAIN':
            # Only adopt a batch belonging to the CURRENT preparation. A
            # payment that failed and was legitimately re-prepared goes back
            # to PENDING_BLOCKCHAIN with its updated_at refreshed, while its
            # old terminal batch keeps an earlier created_at — matching on
            # source_id alone let that dead batch hijack the fresh attempt and
            # fail it again, permanently. In the real lost-save case the batch
            # is created after the payment's last save, so this ordering is
            # exactly the discriminator.
            if batch.created_at is None or batch.created_at < p.updated_at:
                logger.info(
                    '[PAY][BSC] batch %s predates payment %s current preparation '
                    '— not adopting', batch.id, p.internal_id)
                continue
            p.transaction_hash = batch.tx_hash
            p.status = 'SUBMITTED'
            p.save(update_fields=['transaction_hash', 'status', 'updated_at'])
            repaired += 1
            logger.warning(
                '[PAY][BSC] repaired %s: batch %s was %s while the payment was '
                'still PENDING_BLOCKCHAIN', p.internal_id, batch.id, batch.status)
        if p.status == 'SUBMITTED' and batch.status in TERMINAL:
            confirm_bsc_payment.apply_async(args=[p.id, batch.id])
            requeued += 1
    if repaired or requeued:
        logger.info('[PAY][BSC] reconcile: %s repaired, %s re-queued',
                    repaired, requeued)
    return {'repaired': repaired, 'requeued': requeued}
