"""
Celery tasks for BSC payroll — receipt resolution for payroll payouts
(send/tasks.py shape: the SponsoredBatch row's own receipt task settles the
chain outcome; this task settles the PayrollItem and its run).
"""
import logging
from decimal import Decimal

from celery import shared_task

logger = logging.getLogger(__name__)


def _movement(account, movement_type, title, amount_usd, tx_hash, reference):
    from cusd_plus.models import CusdPlusMovement
    if account is None:
        return
    try:
        CusdPlusMovement.objects.get_or_create(
            reference=reference,
            defaults={
                'account': account,
                'movement_type': movement_type,
                'title': title,
                'amount_usd': amount_usd,
                'tx_hash': tx_hash or '',
            },
        )
    except Exception:  # noqa: BLE001 — ledger failure must not fail the payout
        logger.exception('payroll movement write failed for %s', reference)


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
    if statuses and statuses <= {'CONFIRMED', 'CANCELLED'}:
        run.status = 'COMPLETED'
    elif 'CONFIRMED' in statuses:
        run.status = 'PARTIAL'
    else:
        return
    run.save(update_fields=['status', 'updated_at'])


@shared_task(name='payroll.confirm_bsc_payroll_payout', bind=True, max_retries=20)
def confirm_bsc_payroll_payout(self, item_id: int, batch_id: int):
    from cusd_plus.models import SponsoredBatch
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
        _movement(
            business_account, 'payroll',
            f'Nómina a {item.recipient_user.get_full_name() or "empleado"}',
            -gross, item.transaction_hash, f'payroll_item:{item.id}:out',
        )
        _movement(
            item.recipient_account, 'payroll',
            f'Nómina de {business.name}',
            Decimal(item.net_amount), item.transaction_hash,
            f'payroll_item:{item.id}:in',
        )
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
