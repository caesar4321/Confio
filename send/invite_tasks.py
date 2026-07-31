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


@shared_task(name='send.confirm_bsc_invite_reclaim', bind=True, max_retries=20)
def confirm_bsc_invite_reclaim(self, invite_id: int, batch_id: int):
    from cusd_plus.models import SponsoredBatch

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
        logger.info('[INVITE][BSC] invite %s reclaimed: %s', invite.pk, batch.tx_hash)
    else:  # reverted / noop_failed / reorged / dropped
        # The reclaim did NOT take effect — the escrow is still on-chain and
        # claimable, so return the invite to 'pending' (retryable).
        invite.status = 'pending'
        invite.save(update_fields=['status', 'updated_at'])
        logger.warning('[INVITE][BSC] invite %s reclaim failed (batch %s %s) — back to pending',
                       invite.pk, batch.id, batch.status)
