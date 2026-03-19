from decimal import Decimal

from django.utils import timezone

from blockchain.models import PendingAutoSwap
from users.models import Account


USDC_MICRO_MULTIPLIER = Decimal('1000000')


def ensure_pending_usdc_auto_swap(deposit):
    if deposit.status != 'COMPLETED':
        return None
    if Decimal(str(deposit.amount or 0)) < Decimal('1'):
        return None

    account = Account.objects.filter(
        algorand_address=deposit.actor_address,
        deleted_at__isnull=True,
    ).first()
    if not account:
        return None

    amount_decimal = Decimal(str(deposit.amount))
    amount_micro = int((amount_decimal * USDC_MICRO_MULTIPLIER).quantize(Decimal('1')))

    pending, _ = PendingAutoSwap.objects.update_or_create(
        usdc_deposit=deposit,
        defaults={
            'account': account,
            'actor_user': deposit.actor_user,
            'actor_business': deposit.actor_business,
            'actor_type': deposit.actor_type,
            'actor_address': deposit.actor_address,
            'asset_type': 'USDC',
            'amount_micro': amount_micro,
            'amount_decimal': amount_decimal,
            'source_address': deposit.source_address or '',
            'status': 'PENDING',
            'error_message': '',
            'completed_at': None,
        },
    )
    return pending


def attach_conversion_to_pending_auto_swap(pending_auto_swap, conversion):
    if not pending_auto_swap:
        return
    pending_auto_swap.conversion = conversion
    pending_auto_swap.save(update_fields=['conversion', 'updated_at'])


def mark_pending_auto_swap_submitted(conversion):
    pending = PendingAutoSwap.objects.filter(conversion=conversion).first()
    if not pending:
        return
    pending.status = 'SUBMITTED'
    pending.error_message = ''
    pending.save(update_fields=['status', 'error_message', 'updated_at'])


def sync_pending_auto_swap_from_conversion(conversion):
    pending = PendingAutoSwap.objects.filter(conversion=conversion).first()
    if not pending:
        return

    if conversion.status == 'COMPLETED':
        pending.status = 'COMPLETED'
        pending.error_message = ''
        pending.completed_at = conversion.completed_at or timezone.now()
        pending.save(update_fields=['status', 'error_message', 'completed_at', 'updated_at'])
    elif conversion.status == 'FAILED':
        pending.status = 'FAILED'
        pending.error_message = conversion.error_message or ''
        pending.save(update_fields=['status', 'error_message', 'updated_at'])
