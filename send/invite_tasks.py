"""
Celery settlement for BSC invite escrow flows.

Invite CREATE and the invitee CLAIM settle via the batch-level receipt task
alone (the escrow is the on-chain source of truth). RECLAIM needs a domain
task because it flips off-chain state: the inviter's PhoneInvite must only
read 'reclaimed' once the reclaim batch is FINAL — a reverted reclaim (the
invitee claimed first, or a reorg) has to revert to 'pending' so the escrow
stays claimable (audit 2026-07-31 P3).
"""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='send.confirm_bsc_invite_create', bind=True, max_retries=25)
def confirm_bsc_invite_create(self, send_id: int, batch_id: int):
    """Settle the invite's history row from its batch. Mirrors
    send.tasks.confirm_bsc_send, minus the delivery notifications: nothing was
    delivered to anybody yet — the money is sitting in the escrow, and the
    invitee gets told when they join and the sponsor releases it."""
    from blockchain.models import SponsoredBatch

    from .models import SendTransaction

    try:
        s = SendTransaction.objects.get(id=send_id)
        batch = SponsoredBatch.objects.get(id=batch_id)
    except (SendTransaction.DoesNotExist, SponsoredBatch.DoesNotExist):
        return
    if s.status != 'SUBMITTED':
        return  # already resolved

    # Isolation (audit 2026-07-31 P2): only THIS invite's batch may settle it.
    if (batch.kind != 'invite_create'
            or (s.transaction_hash and batch.tx_hash != s.transaction_hash)):
        logger.error('[INVITE][BSC] batch %s does not match invite send %s — refusing to settle',
                     batch.id, s.id)
        return

    if batch.status in ('signed', 'sent'):
        from cusd_plus.tasks import _retry_countdown
        raise self.retry(countdown=_retry_countdown(self.request.retries))

    if batch.status == 'confirmed':
        s.status = 'CONFIRMED'
        s.save(update_fields=['status', 'updated_at'])
        logger.info('[INVITE][BSC] %s escrowed (%s %s): %s',
                    s.internal_id, s.amount, s.token_type, s.transaction_hash)
        return

    # The escrow was never funded. Fail the history row AND drop the PhoneInvite
    # out of 'pending', or the invitee's auto-claim would keep trying to release
    # an escrow slot that does not exist.
    from .models import PhoneInvite
    s.status = 'FAILED'
    s.error_message = f'batch_{batch.status}'
    s.save(update_fields=['status', 'error_message', 'updated_at'])
    PhoneInvite.objects.filter(send_transaction=s, status='pending').update(
        status='reclaimed')
    logger.warning('[INVITE][BSC] %s failed: batch %s %s', s.internal_id, batch.id, batch.status)


@shared_task(name='send.confirm_bsc_invite_reclaim', bind=True, max_retries=20)
def confirm_bsc_invite_reclaim(self, invite_id: int, batch_id: int):
    from blockchain.models import SponsoredBatch

    from .models import PhoneInvite

    try:
        invite = PhoneInvite.objects.get(pk=invite_id)
        batch = SponsoredBatch.objects.get(id=batch_id)
    except (PhoneInvite.DoesNotExist, SponsoredBatch.DoesNotExist):
        return
    if invite.status != 'reclaiming':
        return  # already resolved

    # Isolation (audit P2): only THIS invite's reclaim batch settles it.
    if batch.kind != 'invite_reclaim' or batch.source_id != invite.pk:
        logger.error('[INVITE][BSC] batch %s does not match invite %s — refusing to settle',
                     batch.id, invite.pk)
        return

    if batch.status in ('signed', 'sent'):
        raise self.retry(countdown=15)

    if batch.status == 'confirmed':
        invite.status = 'reclaimed'
        invite.save(update_fields=['status', 'updated_at'])
        if invite.send_transaction_id:
            invite.send_transaction.invitation_reverted = True
            invite.send_transaction.save(update_fields=['invitation_reverted', 'updated_at'])
        logger.info('[INVITE][BSC] invite %s reclaimed: %s', invite.pk, batch.tx_hash)
    else:  # reverted / noop_failed / reorged / dropped
        # The reclaim did NOT take effect — the escrow is still on-chain and
        # claimable, so return the invite to 'pending' (retryable).
        invite.status = 'pending'
        invite.save(update_fields=['status', 'updated_at'])
        logger.warning('[INVITE][BSC] invite %s reclaim failed (batch %s %s) — back to pending',
                       invite.pk, batch.id, batch.status)
