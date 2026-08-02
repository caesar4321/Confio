"""
Celery tasks for BSC payroll — receipt resolution for payroll payouts
(send/tasks.py shape: the SponsoredBatch row's own receipt task settles the
chain outcome; this task settles the PayrollItem and its run).
"""
import logging
from decimal import Decimal

from celery import shared_task

logger = logging.getLogger(__name__)




def _notify_parties(item) -> None:
    from notifications import utils as notif_utils
    from notifications.models import NotificationType as NotifType

    business = item.run.business
    amount_str = f'{item.net_amount:.2f}'.rstrip('0').rstrip('.')
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
                    f'Pagaste {amount_str} dólares a '
                    f'{item.recipient_user.get_full_name() or "tu empleado"}'
                ),
                data=dict(common),
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
    if item.status != 'SUBMITTED':
        return  # already resolved

    # Isolation (audit 2026-07-31 P2): only THIS item's payout batch settles it.
    if (batch.kind != 'payroll_payout' or batch.source_id != item.id
            or (item.transaction_hash and batch.tx_hash != item.transaction_hash)):
        logger.error('[PAYROLL][BSC] batch %s does not match item %s — refusing to settle', batch.id, item.id)
        return

    if batch.status in ('signed', 'sent'):
        raise self.retry(countdown=15)

    if batch.status == 'confirmed':
        item.status = 'CONFIRMED'
        item.save(update_fields=['status', 'updated_at'])

        business = item.run.business
        payout = (item.blockchain_data or {}).get('bsc_payout') or {}
        business_account = Account.objects.filter(
            bsc_address__iexact=payout.get('business') or '',
            deleted_at__isnull=True).first()
        gross = Decimal(item.net_amount) + Decimal(item.fee_amount or 0)
        _notify_parties(item)
        _settle_run(item.run)
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
    from .models import PayrollItem

    stranded = (PayrollItem.objects
                .filter(status='SUBMITTED', deleted_at__isnull=True)
                .exclude(transaction_hash='')
                .order_by('id')[:200])
    settled = 0
    for item in stranded:
        batch = SponsoredBatch.objects.filter(
            kind='payroll_payout', source_id=item.id,
            status__in=('confirmed', 'reverted', 'dropped', 'reorged',
                        'noop_failed'),
        ).order_by('-id').first()
        if batch is None:
            continue  # still in flight — the receipt worker owns it
        confirm_bsc_payroll_payout.apply_async(args=[item.id, batch.id])
        settled += 1
    if settled:
        logger.info('[PAYROLL][BSC] re-queued %s stranded payout(s)', settled)
    return settled
