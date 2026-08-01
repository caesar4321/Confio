"""
Celery tasks for BSC sends — the receipt-resolution half of send/bsc_flow.

confirm_bsc_send follows the SponsoredBatch row (whose own receipt task
handles revert and the 7702 silent no-op) and settles the SendTransaction:
CONFIRMED → SEND_SENT/SEND_RECEIVED notifications
pushes (payload parity with the Algorand sweeper in blockchain/tasks.py);
reverted/noop_failed → FAILED (funds untouched; the client retries).
"""
import logging

from celery import shared_task
from django.utils import timezone

# Register the invite reclaim confirm task at worker startup — Celery
# autodiscovers <app>.tasks, so it would otherwise never import invite_tasks
# and the worker would reject 'send.confirm_bsc_invite_reclaim'.
from send.invite_tasks import confirm_bsc_invite_reclaim  # noqa: F401

logger = logging.getLogger(__name__)

TOKEN_DISPLAY = {'CUSD_PLUS': 'cUSD+', 'USDT': 'USDT', 'CONFIO': 'CONFIO'}


def _account_for_bsc_address(addr: str):
    from users.models import Account
    if not addr:
        return None
    return Account.objects.filter(bsc_address__iexact=addr).first()




def _notify_send_parties(s) -> None:
    from notifications import utils as notif_utils
    from notifications.models import NotificationType as NotifType

    token = TOKEN_DISPLAY.get((s.token_type or '').upper(), s.token_type)
    amount_str = f'{s.amount:.2f}'.rstrip('0').rstrip('.')
    sender_name = s.sender_display_name or 'Contacto'
    recipient_name = (
        s.recipient_display_name
        or (s.recipient_phone if s.recipient_phone else None)
        or (s.recipient_address[:6] + '...' + s.recipient_address[-4:]
            if s.recipient_address else 'Contacto')
    )
    common = {
        'transaction_id': str(s.internal_id),
        'internal_id': str(s.internal_id),
        'transaction_hash': s.transaction_hash,
        'amount': amount_str,
        'token_type': s.token_type,
        'sender_name': sender_name,
        'recipient_name': recipient_name,
        'sender_phone': s.sender_phone or '',
        'recipient_phone': s.recipient_phone or '',
        'memo': s.memo or '',
        'transaction_type': 'send',
    }
    try:
        if s.recipient_user_id:
            notif_utils.create_notification(
                user=s.recipient_user,
                account=None,
                business=s.recipient_business,
                notification_type=NotifType.SEND_RECEIVED,
                title='Dinero recibido',
                message=f'Recibiste {amount_str} {token} de {sender_name}',
                data=dict(common),
                related_object_type='SendTransaction',
                related_object_id=str(s.internal_id),
                action_url=f'confio://send/{s.internal_id}',
            )
        if s.sender_user_id:
            notif_utils.create_notification(
                user=s.sender_user,
                account=None,
                business=s.sender_business,
                notification_type=NotifType.SEND_SENT,
                title='Dinero enviado',
                message=f'Enviaste {amount_str} {token} a {recipient_name}',
                data=dict(common),
                related_object_type='SendTransaction',
                related_object_id=str(s.internal_id),
                action_url=f'confio://send/{s.internal_id}',
            )
    except Exception:  # noqa: BLE001
        logger.exception('send notifications failed for %s', s.internal_id)


@shared_task(name='send.confirm_bsc_send', bind=True, max_retries=20)
def confirm_bsc_send(self, send_id: int, batch_id: int):
    from blockchain.models import SponsoredBatch
    from .models import SendTransaction

    try:
        s = SendTransaction.objects.get(id=send_id)
        batch = SponsoredBatch.objects.get(id=batch_id)
    except (SendTransaction.DoesNotExist, SponsoredBatch.DoesNotExist):
        return
    if s.status != 'SUBMITTED':
        return  # already resolved

    # Isolation (audit 2026-07-31 P2): this batch must actually be THIS
    # send's batch — right flow, right source row, right hash — before it
    # can settle the row. Blocks a mis-scheduled/duplicate task settling a
    # row with someone else's batch.
    if (batch.kind not in ('send_cusd_plus', 'send_redeem', 'send_usdt')
            or batch.source_id != s.id
            or (s.transaction_hash and batch.tx_hash != s.transaction_hash)):
        logger.error('[SEND][BSC] batch %s does not match send %s — refusing to settle', batch.id, s.id)
        return

    if batch.status in ('signed', 'sent'):
        raise self.retry(countdown=15)

    if batch.status == 'confirmed':
        s.status = 'CONFIRMED'
        s.save(update_fields=['status', 'updated_at'])
        # unified row updates via the post_save signal
        token = TOKEN_DISPLAY.get((s.token_type or '').upper(), s.token_type)
        _notify_send_parties(s)
        logger.info('[SEND][BSC] %s confirmed (%s %s): %s',
                    s.internal_id, s.amount, token, s.transaction_hash)
    else:  # reverted / noop_failed
        s.status = 'FAILED'
        s.error_message = f'batch_{batch.status}'
        s.save(update_fields=['status', 'error_message', 'updated_at'])
        logger.warning('[SEND][BSC] %s failed: batch %s %s',
                       s.internal_id, batch.id, batch.status)
