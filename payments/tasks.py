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

TOKEN_DISPLAY = {'CUSD_PLUS': 'cUSD+', 'USDT': 'USDT'}




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
    if (batch.kind not in ('pay_cusd_plus', 'pay_usdt')
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
    try:
        if p.merchant_account_user_id:
            notif_utils.create_notification(
                user=p.merchant_account_user,
                account=p.merchant_account,
                business=p.merchant_business,
                notification_type=NotifType.PAYMENT_RECEIVED,
                title='Pago recibido',
                message=f'Recibiste {amount_str} {token} de {payer_name}',
                data=dict(common),
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
