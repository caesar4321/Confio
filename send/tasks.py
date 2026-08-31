"""
Celery tasks for BSC sends — the receipt-resolution half of send/bsc_flow.

confirm_bsc_send follows the SponsoredBatch row (whose own receipt task
handles revert and the 7702 silent no-op) and settles the SendTransaction:
CONFIRMED → SEND_SENT/SEND_RECEIVED notifications
pushes (payload parity with the Algorand sweeper in blockchain/tasks.py);
reverted/noop_failed → FAILED (funds untouched; the client retries).
"""
import json
import logging

from celery import shared_task
from django.utils import timezone

# Register the invite reclaim confirm task at worker startup — Celery
# autodiscovers <app>.tasks, so it would otherwise never import invite_tasks
# and the worker would reject 'send.confirm_bsc_invite_reclaim'.
from send.invite_tasks import (  # noqa: F401
    confirm_bsc_invite_claim, confirm_bsc_invite_create, confirm_bsc_invite_reclaim,
    reconcile_bsc_invites, retry_bsc_invite_claim,
)

logger = logging.getLogger(__name__)

# One shared table (notifications/token_display). The private copy here
# omitted CUSD, so a legacy send read "Enviaste 5 CUSD a …".
from notifications.token_display import token_label


def _account_for_bsc_address(addr: str):
    from users.models import Account
    if not addr:
        return None
    return Account.objects.filter(bsc_address__iexact=addr).first()




def _notify_send_parties(s) -> None:
    from notifications import utils as notif_utils
    from notifications.models import NotificationType as NotifType
    from users.phone_utils import to_international

    token = token_label(s.token_type)
    amount_str = f'{s.amount:.2f}'.rstrip('0').rstrip('.')
    # The stored columns hold LOCAL digits; a client can neither display nor
    # re-send to those. Send the full international number.
    sender_phone = to_international(s.sender_phone, s.sender_user if s.sender_user_id else None)
    recipient_phone = to_international(
        s.recipient_phone, s.recipient_user if s.recipient_user_id else None)
    sender_name = s.sender_display_name or 'Contacto'
    recipient_name = (
        s.recipient_display_name
        or (recipient_phone if recipient_phone else None)
        or (s.recipient_address[:6] + '...' + s.recipient_address[-4:]
            if s.recipient_address else 'Contacto')
    )
    # ONLY the external side's address travels. An external counterparty has
    # no name and no phone, so the address is the only thing identifying it —
    # but a Confío counterparty already has both, and shipping its address
    # anyway would (a) trip the app's "an address and no phone" heuristic and
    # relabel a real user as "Billetera externa" on business notifications,
    # which carry no phones by design, and (b) hand every employee the
    # personal wallet address that the phone rule below deliberately withholds.
    # An invitation is recipient_type='external' too, but its address is the
    # ESCROW app, not a counterparty — and the client suppresses the expiry
    # warning and the reclaim button whenever is_external_address is set, so
    # calling an invite external would cost the inviter their money back.
    external_sender = (s.sender_type or '') == 'external'
    external_recipient = (s.recipient_type or '') == 'external' and not s.is_invitation
    fee_bps = None
    if s.fee_amount and s.fee_amount > 0:
        try:
            receipt = json.loads(s.bsc_calls_json or '{}').get('receipt') or {}
            parsed_fee_bps = int(receipt.get('fee_bps') or 0)
            fee_bps = parsed_fee_bps if parsed_fee_bps > 0 else None
        except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
            pass
    common = {
        'transaction_id': str(s.internal_id),
        'internal_id': str(s.internal_id),
        'transaction_hash': s.transaction_hash,
        'amount': amount_str,
        'token_type': s.token_type,
        # Exact contract receipt accounting. Transaction detail must not
        # rediscover a rate (or call a stale notification "free") when the
        # finalized SendTransaction already knows gross/fee/net.
        'fee_amount': str(s.fee_amount or ''),
        **({'fee_bps': str(fee_bps)} if fee_bps is not None else {}),
        'net_amount': str(s.net_amount if s.net_amount is not None else s.amount),
        'sender_name': sender_name,
        'recipient_name': recipient_name,
        # Stated, not inferred: the client should never have to guess which
        # side is external from which fields happen to be populated.
        'is_external_address': external_sender or external_recipient,
        **({'sender_address': s.sender_address or ''} if external_sender else {}),
        **({'recipient_address': s.recipient_address or ''} if external_recipient else {}),
        'memo': s.memo or '',
        'transaction_type': 'send',
    }

    def payload(business):
        """A notification attached to a business is pushed to EVERY employee
        (notifications/fcm_service.py) and its whole `data` blob is readable
        by all of them. Personal phone numbers are not business data, so they
        travel only on the personal notifications."""
        data = dict(common)
        if business is None:
            data['sender_phone'] = sender_phone
            data['recipient_phone'] = recipient_phone
        return data

    try:
        if s.recipient_user_id:
            notif_utils.create_notification(
                user=s.recipient_user,
                account=None,
                business=s.recipient_business,
                notification_type=NotifType.SEND_RECEIVED,
                title='Dinero recibido',
                message=f'Recibiste {amount_str} {token} de {sender_name}',
                data=payload(s.recipient_business),
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
                data=payload(s.sender_business),
                related_object_type='SendTransaction',
                related_object_id=str(s.internal_id),
                action_url=f'confio://send/{s.internal_id}',
            )
    except Exception:  # noqa: BLE001
        logger.exception('send notifications failed for %s', s.internal_id)


@shared_task(name='send.confirm_bsc_send', bind=True, max_retries=25)
def confirm_bsc_send(self, send_id: int, batch_id: int):
    from blockchain.models import SponsoredBatch
    from .kinds import BSC_SEND_KINDS
    from .models import SendTransaction

    try:
        s = SendTransaction.objects.get(id=send_id)
        batch = SponsoredBatch.objects.get(id=batch_id)
    except (SendTransaction.DoesNotExist, SponsoredBatch.DoesNotExist):
        return
    # Isolation (audit 2026-07-31 P2): this batch must actually be THIS
    # send's batch — right flow, right source row, right hash — before it
    # can settle the row. Blocks a mis-scheduled/duplicate task settling a
    # row with someone else's batch.
    if (batch.kind not in BSC_SEND_KINDS
            or batch.source_id != s.id
            or (s.transaction_hash
                and batch.tx_hash.lower() != s.transaction_hash.lower())):
        logger.error('[SEND][BSC] batch %s does not match send %s — refusing to settle', batch.id, s.id)
        return

    # Crash convergence: the durable batch can exist before submit_bsc_send
    # writes the domain hash/status. Adopt only this isolated batch; a
    # conditional UPDATE prevents overwriting any concurrently advanced row.
    if s.status == 'PENDING' and not s.transaction_hash:
        adopted = SendTransaction.objects.filter(
            pk=s.pk, status='PENDING', transaction_hash='',
        ).update(
            transaction_hash=batch.tx_hash,
            status='SUBMITTED',
            updated_at=timezone.now(),
        )
        if adopted:
            s.transaction_hash = batch.tx_hash
            s.status = 'SUBMITTED'
    if s.status != 'SUBMITTED':
        return  # already resolved or concurrently advanced

    if batch.status in ('signed', 'sent'):
        # Fast early, slow tail (cusd_plus.tasks._retry_countdown): BSC
        # finality lands ~1s after mining, so the first checks should be
        # seconds apart. A flat 15s here is what kept the user staring at
        # 'Confirmando…' long after the chain had already committed.
        from cusd_plus.tasks import _retry_countdown
        raise self.retry(countdown=_retry_countdown(self.request.retries))

    if batch.status == 'confirmed':
        s.status = 'CONFIRMED'
        s.save(update_fields=['status', 'updated_at'])
        # unified row updates via the post_save signal
        token = token_label(s.token_type)
        _notify_send_parties(s)
        logger.info('[SEND][BSC] %s confirmed (%s %s): %s',
                    s.internal_id, s.amount, token, s.transaction_hash)
    else:  # reverted / noop_failed
        s.status = 'FAILED'
        s.error_message = f'batch_{batch.status}'
        s.save(update_fields=['status', 'error_message', 'updated_at'])
        logger.warning('[SEND][BSC] %s failed: batch %s %s',
                       s.internal_id, batch.id, batch.status)
