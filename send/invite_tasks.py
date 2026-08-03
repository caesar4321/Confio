"""
Celery settlement for BSC invite escrow flows.

Nothing here trusts a broadcast. Every leg — create, claim, reclaim — leaves
its PhoneInvite in an in-flight state and a task settles it from the chain,
because the failure that costs real money is booking an outcome that never
happened: a create that never funded but reads 'pending', a dropped claim that
reads 'claimed' (the invitee has nothing and the inviter can no longer
reclaim), a reverted reclaim that reads 'reclaimed'.

Every transition is a compare-and-set on the status the task expects to find.
Read-then-save loses races that CAS wins, and in a claim/reclaim race the loser
would otherwise overwrite the winner's verdict (audit 2026-07-31 P3, Codex
audit 2026-08-02).
"""
import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(name='send.confirm_bsc_invite_create', bind=True, max_retries=25)
def confirm_bsc_invite_create(self, invite_id: int, batch_id: int):
    """Settle a create from its batch: 'creating' → 'pending' (escrow funded)
    or 'failed'. Keyed by the INVITE pk — the same source_id the batch carries,
    so cusd_plus.reconcile_signed_batches can re-enqueue this task for a create
    whose process died before it scheduled anything.

    Mirrors send.tasks.confirm_bsc_send, minus the delivery notifications:
    nothing has been delivered to anybody yet — the money is in the escrow, and
    the invitee is told when they join and the sponsor releases it."""
    from blockchain.models import SponsoredBatch

    from .models import PhoneInvite, SendTransaction

    try:
        invite = PhoneInvite.objects.select_related('send_transaction').get(pk=invite_id)
        batch = SponsoredBatch.objects.get(id=batch_id)
    except (PhoneInvite.DoesNotExist, SponsoredBatch.DoesNotExist):
        return
    if invite.status != 'creating':
        return  # already resolved

    s = invite.send_transaction
    # Isolation (audit 2026-07-31 P2): only THIS invite's batch may settle it.
    if (batch.kind != 'invite_create'
            or batch.source_id != invite.pk
            or (s is not None and s.transaction_hash
                and batch.tx_hash != s.transaction_hash)):
        logger.error('[INVITE][BSC] batch %s does not match invite %s — refusing to settle',
                     batch.id, invite.pk)
        return

    if batch.status in ('signed', 'sent'):
        from cusd_plus.tasks import _retry_countdown
        raise self.retry(countdown=_retry_countdown(self.request.retries))

    if batch.status == 'confirmed':
        # The contract starts its 7-day window when the create MINES, so the
        # off-chain clock is set here too. Dating it from the broadcast showed
        # the inviter a reclaim button the escrow then rejected as 'not
        # expired' (Codex follow-up audit 2026-08-02 P2).
        from datetime import timedelta

        from django.utils import timezone
        expires_at = timezone.now() + timedelta(days=7)
        if not PhoneInvite.objects.filter(pk=invite.pk, status='creating').update(
                status='pending', expires_at=expires_at):
            return
        if s is not None:
            # save(), not update(): the unified history row is maintained by a
            # post_save signal that a queryset update does not fire, so history
            # would sit on 'SUBMITTED' forever.
            s.status = 'CONFIRMED'
            s.invitation_expires_at = expires_at
            s.save(update_fields=['status', 'invitation_expires_at', 'updated_at'])
        logger.info('[INVITE][BSC] invite %s escrowed (%s %s): %s',
                    invite.pk, invite.amount, invite.token_type, batch.tx_hash)
        # The invitee may have verified their phone WHILE this was in flight,
        # in which case their auto-claim ran against an unfunded slot and gave
        # up. Nothing else would ever retry, and the money would sit here until
        # expiry — so close that window now that the escrow is real.
        _claim_if_recipient_already_joined(invite)
        return

    # The escrow was never funded. Fail the history row and mark the invite
    # 'failed', or the auto-claim keeps trying to release a slot that is not
    # there. NOT 'reclaimed' — nothing was ever returned, and calling it that
    # would tell the inviter their money came back.
    if not PhoneInvite.objects.filter(pk=invite.pk, status='creating').update(
            status='failed'):
        return
    if s is not None:
        s.status = 'FAILED'
        s.error_message = f'batch_{batch.status}'
        s.save(update_fields=['status', 'error_message', 'updated_at'])
    logger.warning('[INVITE][BSC] invite %s failed: batch %s %s',
                   invite.pk, batch.id, batch.status)


def _claim_if_recipient_already_joined(invite) -> None:
    """Best-effort: release a just-funded escrow to an invitee who verified
    while the create was still in flight."""
    from users.models import User

    from .invite_bsc_flow import claim_for_recipient

    try:
        # EXACTLY one, never .first(). phone_key has no unique index in any
        # migration, so on a duplicate .first() would pick an arbitrary account
        # and the sponsor would release someone else's money to them. If the
        # phone is ambiguous, do nothing — the invite stays claimable, and the
        # ordinary verification-time auto-claim (which is handed a specific
        # user) settles it.
        matches = list(User.objects.filter(phone_key=invite.phone_key)[:2])
        if len(matches) != 1:
            return
        recipient = matches[0]
        if recipient.pk == invite.inviter_user_id:
            return
        invite.refresh_from_db()
        res = claim_for_recipient(invite, recipient)
        if not res.get('success'):
            logger.info('[INVITE][BSC] post-create claim skipped %s: %s',
                        invite.pk, res.get('error'))
            # Same bounded retry the verification-time auto-claim gets — this
            # path was still one-shot, so a busy sponsor here left the money
            # escrowed until expiry (Codex follow-up audit P2).
            from .invite_bsc_flow import _retry_claim_later
            _retry_claim_later(invite, recipient, res.get('error'))
    except Exception:  # noqa: BLE001 — settlement must not fail on this
        logger.exception('[INVITE][BSC] post-create claim errored %s', invite.pk)


@shared_task(name='send.retry_bsc_invite_claim', bind=True, max_retries=12)
def retry_bsc_invite_claim(self, invite_id: int, recipient_user_id: int):
    """Re-attempt an auto-claim that failed on a transient condition.

    Backs off up to ~2h, which comfortably outlasts a busy sponsor or a create
    still waiting to mine. Giving up is safe: the money stays escrowed and the
    inviter can still reclaim it after the 7-day window."""
    from users.models import User

    from .invite_bsc_flow import claim_for_recipient
    from .models import PhoneInvite

    try:
        invite = PhoneInvite.objects.get(pk=invite_id, rail='bsc')
        recipient = User.objects.get(pk=recipient_user_id)
    except (PhoneInvite.DoesNotExist, User.DoesNotExist):
        return
    if invite.status != 'pending':
        return  # claimed, reclaimed, or in flight — nothing to retry

    res = claim_for_recipient(invite, recipient)
    if res.get('success'):
        logger.info('[INVITE][BSC] retried claim succeeded for invite %s', invite_id)
        return
    error = res.get('error')
    from .invite_bsc_flow import _RETRYABLE_CLAIM_ERRORS
    if error not in _RETRYABLE_CLAIM_ERRORS:
        logger.info('[INVITE][BSC] claim retry abandoned for invite %s: %s',
                    invite_id, error)
        return
    raise self.retry(countdown=min(60 * (2 ** self.request.retries), 1800))


@shared_task(name='send.confirm_bsc_invite_claim', bind=True, max_retries=25)
def confirm_bsc_invite_claim(self, invite_id: int, tx_hash: str):
    """Settle a claim from its FINALIZED receipt: 'claiming' → 'claimed', or
    back to 'pending' if it reverted or provably never landed.

    The claim is a plain KMS transaction, not a sponsored batch, so there is no
    SponsoredBatch row to follow — the chain is the only evidence. Until it
    speaks the invite stays 'claiming', which is what keeps a reclaim from
    being prepared against a slot that is already being released.

    Two rules this enforces that a bare receipt check did not (Codex follow-up
    audit 2026-08-02 P1):

      * FINALITY. Settling on the first receipt lets a reorg leave the DB
        'claimed' while the escrow is still funded — the invitee has nothing
        and the inviter can no longer reclaim. Same finality instrument the
        sponsored-batch receipt task uses: BSC's finalized tag (BEP-126), with
        the confirmation-depth heuristic only as a fallback for a node that
        will not serve it.

      * ABSENCE IS NOT PROOF. "No receipt for a while" used to be read as
        'dropped', which could return the row to 'pending' minutes before the
        claim actually mined — two settlements of one escrow slot. A claim is
        only released when the node does not know the transaction AT ALL.
    """
    from cusd_plus.sponsor_7702 import _rpc
    from cusd_plus.tasks import (
        _finality_depth, _finalized_block_number, _retry_countdown,
    )

    from .models import PhoneInvite

    try:
        invite = PhoneInvite.objects.select_related('send_transaction').get(pk=invite_id)
    except PhoneInvite.DoesNotExist:
        return
    if invite.status != 'claiming':
        return  # already resolved

    def _release(reason: str) -> None:
        PhoneInvite.objects.filter(pk=invite.pk, status='claiming').update(
            status='pending', claimed_by=None, claimed_txid='')
        logger.warning('[INVITE][BSC] claim %s %s — invite %s back to pending',
                       tx_hash, reason, invite.pk)

    try:
        receipt = _rpc('eth_getTransactionReceipt', [tx_hash])
    except Exception as exc:  # noqa: BLE001 — never guess; try again
        logger.warning('[INVITE][BSC] claim receipt lookup failed %s: %s', tx_hash, exc)
        raise self.retry(countdown=15)

    if receipt is None:
        # Mempool or gone? Only the second is safe to act on, and only once the
        # retry budget is spent. Anything still known to a node may yet mine.
        try:
            known = _rpc('eth_getTransactionByHash', [tx_hash])
        except Exception:  # noqa: BLE001
            known = True  # unknown-unknown: assume it may land, keep waiting
        try:
            raise self.retry(countdown=_retry_countdown(self.request.retries))
        except self.MaxRetriesExceededError:
            if known is None:
                _release('is unknown to the chain')
            else:
                # Still out there. Leave it 'claiming' for the reconciler
                # rather than freeing a slot a mining claim is about to take.
                logger.warning('[INVITE][BSC] claim %s still unresolved — leaving invite %s claiming',
                               tx_hash, invite.pk)
            return

    if int(str(receipt.get('status') or '0x0'), 16) != 1:
        _release('reverted')
        return

    # Finality, then canonicality — a receipt from an orphaned block is not a
    # settlement.
    try:
        blk_num = int(receipt.get('blockNumber'), 16)
        blk_hash = (receipt.get('blockHash') or '').lower()
    except Exception as exc:  # noqa: BLE001
        logger.warning('[INVITE][BSC] claim finality read failed %s: %s', tx_hash, exc)
        raise self.retry(countdown=_retry_countdown(self.request.retries))

    finalized = _finalized_block_number()
    if finalized is not None:
        if blk_num > finalized:
            raise self.retry(countdown=_retry_countdown(self.request.retries))
    else:
        try:
            head = int(_rpc('eth_blockNumber', []), 16)
        except Exception as exc:  # noqa: BLE001
            logger.warning('[INVITE][BSC] claim head read failed %s: %s', tx_hash, exc)
            raise self.retry(countdown=_retry_countdown(self.request.retries))
        if head - blk_num < _finality_depth():
            raise self.retry(countdown=_retry_countdown(self.request.retries))

    canonical = _rpc('eth_getBlockByNumber', [hex(blk_num), False])
    if not canonical or (canonical.get('hash') or '').lower() != blk_hash:
        # Reorged out of that block. Re-run: the next pass reads the receipt
        # again and settles the new block, or finds it orphaned.
        raise self.retry(countdown=_retry_countdown(self.request.retries))

    from django.utils import timezone
    if not PhoneInvite.objects.filter(pk=invite.pk, status='claiming').update(
            status='claimed', claimed_at=timezone.now(), claimed_txid=tx_hash):
        return
    # Mirror onto the history row, or the inviter keeps seeing an expiry
    # warning and a reclaim button for money that is already the invitee's.
    # save() so the unified-row post_save signal fires.
    stx = invite.send_transaction
    if stx is not None:
        stx.invitation_claimed = True
        stx.save(update_fields=['invitation_claimed', 'updated_at'])
    logger.info('[INVITE][BSC] invite %s claimed: %s', invite.pk, tx_hash)


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

    # CAS, not save(): `invite` was read before the checks above, and a claim
    # confirmer can have terminalised it meanwhile. An unconditional save would
    # write this task's stale verdict over the newer one — in a claim/reclaim
    # race that means telling the inviter their money came back while the
    # invitee is holding it (Codex audit 2026-08-02 P1).
    if batch.status == 'confirmed':
        if not PhoneInvite.objects.filter(pk=invite.pk, status='reclaiming').update(
                status='reclaimed'):
            logger.info('[INVITE][BSC] invite %s advanced elsewhere — not marking reclaimed',
                        invite.pk)
            return
        send_tx = getattr(invite, 'send_transaction', None)
        if send_tx is not None:
            send_tx.invitation_reverted = True
            send_tx.save(update_fields=['invitation_reverted', 'updated_at'])
        logger.info('[INVITE][BSC] invite %s reclaimed: %s', invite.pk, batch.tx_hash)
    else:  # reverted / noop_failed / reorged / dropped
        # The reclaim did NOT take effect — the escrow is still on-chain and
        # claimable, so return the invite to 'pending' (retryable).
        if not PhoneInvite.objects.filter(pk=invite.pk, status='reclaiming').update(
                status='pending'):
            return
        logger.warning('[INVITE][BSC] invite %s reclaim failed (batch %s %s) — back to pending',
                       invite.pk, batch.id, batch.status)


@shared_task(name='send.reconcile_bsc_invites')
def reconcile_bsc_invites():
    """Converge invites stuck in an in-flight state against the chain.

    Every leg takes its row before broadcasting, which is what makes the flow
    safe under concurrency — but it also means a process that dies between the
    take and the enqueue leaves a row nobody is watching. cusd_plus's
    reconcile_signed_batches only rescues batches still in 'signed'; a batch
    that reached 'sent', or a domain confirmer whose retry budget ran out, or a
    claim (which has no batch row at all), had no second chance. Funded escrow
    could sit in 'creating' or 'claiming' forever (Codex follow-up audit
    2026-08-02 P1).

    This is the second chance. It never decides an outcome itself — it either
    re-drives the confirmer that owns the row, or releases a row that provably
    never reached the chain.
    """
    from datetime import timedelta

    from django.utils import timezone

    from blockchain.models import SponsoredBatch

    from .models import PhoneInvite

    grace = int(getattr(settings, 'BSC_INVITE_RECONCILE_GRACE_MIN', 5))
    cutoff = timezone.now() - timedelta(minutes=grace)
    out = {'redriven': 0, 'released': 0}

    # ── create / reclaim: both own a SponsoredBatch ──────────────────────
    for status, kind, task in (
        ('creating', 'invite_create', confirm_bsc_invite_create),
        ('reclaiming', 'invite_reclaim', confirm_bsc_invite_reclaim),
    ):
        stuck = PhoneInvite.objects.filter(
            rail='bsc', status=status, updated_at__lt=cutoff,
            deleted_at__isnull=True).order_by('pk')[:100]
        for inv in stuck:
            batch = SponsoredBatch.objects.filter(
                kind=kind, source_id=inv.pk).order_by('-id').first()
            if batch is None:
                # send_sponsored_batch writes its row BEFORE broadcasting, so
                # no row means nothing was ever signed. Safe to hand back.
                _release_stuck(inv, status)
                out['released'] += 1
                continue
            if batch.status in ('signed', 'sent'):
                # Still in flight — reconcile_signed_batches and the receipt
                # task own it. Re-driving now would just add noise.
                continue
            # Terminal batch, non-terminal row: the domain confirm never ran or
            # never finished. It is idempotent and re-checks identity itself.
            task.apply_async(args=[inv.pk, batch.id], countdown=5)
            out['redriven'] += 1

    # ── claim: a plain KMS tx, so the invite row IS the record ───────────
    stuck_claims = PhoneInvite.objects.filter(
        rail='bsc', status='claiming', updated_at__lt=cutoff,
        deleted_at__isnull=True).order_by('pk')[:100]
    for inv in stuck_claims:
        if not inv.claimed_txid:
            # The hash is written immediately after signing and before
            # broadcasting, so no hash means nothing was signed.
            _release_stuck(inv, 'claiming')
            out['released'] += 1
            continue
        confirm_bsc_invite_claim.apply_async(
            args=[inv.pk, inv.claimed_txid], countdown=5)
        out['redriven'] += 1

    if out['redriven'] or out['released']:
        logger.info('[INVITE][BSC] reconcile: %s re-driven, %s released',
                    out['redriven'], out['released'])
    return out


# Where an in-flight state goes back to when nothing ever reached the chain.
_RELEASE_TARGET = {'creating': 'draft', 'claiming': 'pending', 'reclaiming': 'pending'}


def _release_stuck(invite, status: str) -> None:
    """CAS a stuck row back to its resting state. Guarded on the status we
    read, so a confirmer that settled it in the meantime keeps its verdict."""
    from .models import PhoneInvite, SendTransaction

    target = _RELEASE_TARGET[status]
    fields = {'status': target}
    if status == 'claiming':
        fields.update(claimed_by=None, claimed_txid='')
    if not PhoneInvite.objects.filter(pk=invite.pk, status=status).update(**fields):
        return
    logger.warning('[INVITE][BSC] reconcile: invite %s had no chain record — %s → %s',
                   invite.pk, status, target)
    if status == 'creating' and invite.send_transaction_id:
        stx = SendTransaction.objects.filter(
            pk=invite.send_transaction_id, status='SUBMITTED').first()
        if stx is not None:
            # save() so the unified history row follows.
            stx.status = 'PENDING'
            stx.save(update_fields=['status', 'updated_at'])
