"""
Celery tasks for BSC payroll — receipt resolution for payroll payouts
(send/tasks.py shape: the SponsoredBatch row's own receipt task settles the
chain outcome; this task settles the PayrollItem and its run).
"""
import logging
from decimal import Decimal

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)




def _notify_parties(item) -> None:
    from notifications import utils as notif_utils
    from notifications.models import NotificationType as NotifType

    business = item.run.business
    # Each side is told its own number, matching the ledger row: the employee
    # what landed in their wallet (the settled figure, which for a redeemed
    # payout can sit below the nominal wage), the business what the run cost
    # them (gross, fee included). One shared figure told both of them
    # something false.
    received = item.settled_amount if item.settled_amount is not None else item.net_amount
    gross = Decimal(item.gross_amount or 0) or (
        Decimal(item.net_amount or 0) + Decimal(item.fee_amount or 0))
    amount_str = f'{received:.2f}'.rstrip('0').rstrip('.')
    gross_str = f'{gross:.2f}'.rstrip('0').rstrip('.')
    common = {
        'transaction_id': str(item.internal_id),
        'internal_id': str(item.internal_id),
        'transaction_hash': item.transaction_hash,
        'amount': amount_str,
        'token_type': item.token_type,
        'transaction_type': 'payroll',
        'business_name': business.name,
    }
    try:
        notif_utils.create_notification(
            user=item.recipient_user,
            account=None,
            business=None,
            notification_type=NotifType.PAYROLL_RECEIVED,
            title='Pago de nómina recibido',
            message=f'{business.name} te pagó {amount_str} dólares',
            data=dict(common),
            related_object_type='PayrollItem',
            related_object_id=str(item.internal_id),
        )
        if item.executed_by_user_id:
            notif_utils.create_notification(
                user=item.executed_by_user,
                account=None,
                business=business,
                notification_type=NotifType.PAYROLL_SENT,
                title='Nómina pagada',
                message=(
                    f'Pagaste {gross_str} dólares a '
                    f'{item.recipient_user.get_full_name() or "tu empleado"}'
                ),
                data=dict(common, amount=gross_str, received_amount=amount_str),
                related_object_type='PayrollItem',
                related_object_id=str(item.internal_id),
            )
    except Exception:  # noqa: BLE001
        logger.exception('payroll notifications failed for %s', item.internal_id)


def _settle_run(run) -> None:
    """DRAFT/READY → PARTIAL → COMPLETED as items resolve."""
    statuses = set(run.items.filter(deleted_at__isnull=True).values_list('status', flat=True))
    # COMPLETED means every listed wage was PAID. Treating CANCELLED as
    # settled reported a finished payroll while a named employee got nothing —
    # and it disagreed with the general status synchroniser, which requires
    # {'CONFIRMED'} alone and which this function overrides by running last.
    # A run that ends with cancellations is PARTIAL: something was left undone
    # and the business should see that.
    if statuses and statuses == {'CONFIRMED'}:
        run.status = 'COMPLETED'
    elif statuses and statuses <= {'CONFIRMED', 'CANCELLED'}:
        run.status = 'PARTIAL'
    elif 'CONFIRMED' in statuses:
        run.status = 'PARTIAL'
    else:
        return
    run.save(update_fields=['status', 'updated_at'])


def _decode_settled_amount(tx_hash: str, item):
    """PaidOut.usdtOut when the payout redeemed, else the nominal net.

    PaidOut(address business, address recipient, bytes32 itemId, address
    signer, uint8 asset, uint256 netAmount, uint256 feeAmount, bool
    redeemedToUsdt, uint256 usdtOut) — only business/recipient/itemId are
    indexed, so SIX values sit in `data` in that order, 32 bytes each:
    signer · asset · netAmount · feeAmount · redeemedToUsdt · usdtOut.

    Two version-pinned things, both silent when wrong:
     - v2 inserted `asset` ahead of the amounts (2026-08-02), changing the
       topic hash AND every offset after it.
     - `signer` is NOT indexed. The v1 decoder's comment said "four remaining
       values" and read from word 2, one short — so it took feeShares as the
       redeem flag (`== 1` essentially never true) and quietly recorded the
       nominal wage for every redeemed payout instead of the real usdtOut.
       Offsets here are counted off the ABI, not the sentence.

    An enum is `uint8` in the event signature; `Asset` would hash to a
    different topic entirely.

    Returns net_amount unchanged when the payout was in cUSD+ shares (no
    slippage there) or when the log cannot be read: never guess a number
    lower than what we promised without evidence for it.
    """
    from decimal import Decimal
    nominal = Decimal(str(item.net_amount or 0))
    try:
        from cusd_plus.tasks import _rpc
        from django.conf import settings
        from eth_hash.auto import keccak

        vault = (getattr(settings, 'BSC_PAYROLL_VAULT_ADDRESS', '') or '').lower()
        topic = '0x' + keccak(
            b'PaidOut(address,address,bytes32,address,uint8,uint256,uint256,bool,uint256)'
        ).hex()
        receipt = _rpc('eth_getTransactionReceipt', [tx_hash]) or {}
        for log in receipt.get('logs') or []:
            if (log.get('address') or '').lower() != vault:
                continue
            if not log.get('topics') or log['topics'][0].lower() != topic:
                continue
            data = (log.get('data') or '0x')[2:]
            if len(data) < 6 * 64:
                break
            # Legacy ABI names: the last two words now mean routedToCusd and
            # routedOut for the cUSD+ compatibility branch.
            routed = int(data[4 * 64:5 * 64], 16) == 1
            routed_out = int(data[5 * 64:6 * 64], 16)
            if not routed:
                return nominal  # paid in shares — nominal is what moved
            settled = (Decimal(routed_out) / Decimal(10) ** 18).quantize(Decimal('0.000001'))
            if settled != nominal:
                logger.info(
                    '[PAYROLL][BSC] %s settled at %s cUSD against a nominal %s '
                    '(internal-route slippage)', item.internal_id, settled, nominal)
            return settled
        logger.warning('[PAYROLL][BSC] no PaidOut log for %s — recording the nominal amount',
                       item.internal_id)
    except Exception:  # noqa: BLE001 — settlement must not fail on a decode
        logger.exception('[PAYROLL][BSC] PaidOut decode failed for %s', item.internal_id)
    return nominal


@shared_task(name='payroll.confirm_bsc_payroll_payout', bind=True, max_retries=20)
def confirm_bsc_payroll_payout(self, item_id: int, batch_id: int):
    from blockchain.models import SponsoredBatch
    from users.models import Account
    from .models import PayrollItem

    try:
        item = PayrollItem.objects.select_related(
            'run__business', 'recipient_user', 'recipient_account',
            'executed_by_user').get(id=item_id)
        batch = SponsoredBatch.objects.get(id=batch_id)
    except (PayrollItem.DoesNotExist, SponsoredBatch.DoesNotExist):
        return
    # Isolation (audit 2026-07-31 P2): only THIS item's payout batch settles it.
    if (batch.kind != 'payroll_payout' or batch.source_id != item.id
            or (item.transaction_hash
                and batch.tx_hash.lower() != item.transaction_hash.lower())):
        logger.error('[PAYROLL][BSC] batch %s does not match item %s — refusing to settle', batch.id, item.id)
        return

    # Crash convergence: the KMS-signed batch is durable before the domain
    # item is stamped. Adopt that isolated batch if the process died in the
    # post-broadcast window, using recipient data stored at prepare time.
    if item.status == 'PREPARED' and not item.transaction_hash:
        payout = (item.blockchain_data or {}).get('bsc_payout') or {}
        recipient = (payout.get('recipient') or '').lower()
        adopted = PayrollItem.objects.filter(
            pk=item.pk, status='PREPARED', transaction_hash='',
        ).update(
            transaction_hash=batch.tx_hash,
            status='SUBMITTED',
            executed_by_user_id=batch.user_id,
            executed_at=batch.created_at,
            recipient_address=recipient,
            updated_at=timezone.now(),
        )
        if adopted:
            item.transaction_hash = batch.tx_hash
            item.status = 'SUBMITTED'
            item.executed_by_user_id = batch.user_id
            item.executed_at = batch.created_at
            item.recipient_address = recipient
    if item.status != 'SUBMITTED':
        return  # already resolved or concurrently advanced

    if batch.status in ('signed', 'sent'):
        raise self.retry(countdown=15)

    if batch.status == 'confirmed':
        item.status = 'CONFIRMED'
        # Read what was ACTUALLY delivered off the chain instead of assuming
        # the nominal wage. An Ondo-ineligible recipient is paid by redeeming
        # shares to USDT with a 99.5% floor, so a 1000 wage can settle as 995
        # — and the ledger and the push both used to claim the full 1000.
        item.settled_amount = _decode_settled_amount(batch.tx_hash, item)
        item.save(update_fields=['status', 'settled_amount', 'updated_at'])

        business = item.run.business
        payout = (item.blockchain_data or {}).get('bsc_payout') or {}
        business_account = Account.objects.filter(
            bsc_address__iexact=payout.get('business') or '',
            deleted_at__isnull=True).first()
        gross = Decimal(item.net_amount) + Decimal(item.fee_amount or 0)
        # NOT _notify_parties(item): the PayrollItem post_save signal
        # (users/signals.py) already notified both sides on the save above,
        # with the same per-side amounts. Calling this too sent a SECOND pair
        # claiming different figures — the employee was told both "recibiste
        # 100.00" and "te pagó 98.60" for one wage. One sender, one number.
        _settle_run(item.run)
        # The escrow just shrank by net+fee; drop the cached read so the
        # payroll hub shows the post-payout float rather than the pre-payout
        # one for another half minute.
        try:
            from .bsc_flow import invalidate_escrow
            invalidate_escrow(payout.get('business') or '')
        except Exception:  # noqa: BLE001
            pass
        logger.info('[PAYROLL][BSC] %s confirmed: %s', item.internal_id,
                    item.transaction_hash)
    else:  # reverted / noop_failed
        item.status = 'FAILED'
        item.error_message = f'batch_{batch.status}'
        item.save(update_fields=['status', 'error_message', 'updated_at'])
        logger.warning('[PAYROLL][BSC] %s failed: batch %s %s',
                       item.internal_id, batch.id, batch.status)


@shared_task(name='payroll.reconcile_stranded_bsc_payroll')
def reconcile_stranded_bsc_payroll():
    """Settle payouts whose confirmer gave up before the chain answered.

    confirm_bsc_payroll_payout retries 20 times; the independent receipt
    worker retries 40 and can terminalise a batch long after. Once the payroll
    task has exhausted, nothing re-reads that batch: a wage that actually paid
    stays SUBMITTED forever, its run stuck at PARTIAL, with no ledger row and
    no notification. This is the convergence pass that was missing — it re-runs
    the confirmer, which is idempotent and re-verifies kind/source_id/tx_hash
    itself, so a duplicate delivery is a no-op.
    """
    from blockchain.models import SponsoredBatch
    from django.db import models
    from .models import PayrollItem

    batch_statuses = (
        'signed', 'sent', 'confirmed', 'reverted', 'dropped', 'reorged',
        'noop_failed',
    )
    has_batch = SponsoredBatch.objects.filter(
        kind='payroll_payout',
        source_id=models.OuterRef('pk'),
        status__in=batch_statuses,
    )
    # PREPARED is normally a large queue of unpaid wages. Filter by durable
    # batch existence BEFORE the limit so ordinary rows cannot starve a later
    # crash-stranded broadcast forever.
    stranded = (PayrollItem.objects
                .filter(status__in=('PREPARED', 'SUBMITTED'), deleted_at__isnull=True)
                .annotate(has_recovery_batch=models.Exists(has_batch))
                .filter(has_recovery_batch=True)
                .order_by('id')[:200])
    settled = 0
    for item in stranded:
        batch = SponsoredBatch.objects.filter(
            kind='payroll_payout', source_id=item.id,
            status__in=batch_statuses,
        ).order_by('-id').first()
        if batch is None:
            continue  # still in flight — the receipt worker owns it
        if batch.status in ('signed', 'sent'):
            from cusd_plus.tasks import check_sponsored_batch_receipt
            check_sponsored_batch_receipt.apply_async(
                args=[batch.id], countdown=3,
            )
        confirm_bsc_payroll_payout.apply_async(
            args=[item.id, batch.id], countdown=5,
        )
        settled += 1
    if settled:
        logger.info('[PAYROLL][BSC] re-queued %s stranded payout(s)', settled)
    return settled


@shared_task(name='payroll.refresh_payroll_chain_caches')
def refresh_payroll_chain_caches(business_addr: str):
    """Drop the cached escrow and delegate reads once an admin batch has had
    time to land.

    submit_bsc_payroll_admin invalidates at BROADCAST, which is too early:
    the very next screen refresh re-reads pre-transaction chain state and
    caches it again for the full TTL, so a business that just funded the
    vault or revoked a delegate sees the old answer for another 30 seconds
    and reasonably concludes the operation did nothing. This second pass runs
    after the transaction has had time to confirm.
    """
    from .bsc_flow import invalidate_delegates, invalidate_escrow

    if not business_addr:
        return
    invalidate_escrow(business_addr)
    invalidate_delegates(business_addr)
