import logging
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from blockchain.models import PendingAutoSwap
from users.models import Account


logger = logging.getLogger(__name__)

USDC_MICRO_MULTIPLIER = Decimal('1000000')
CONSUMED_DEPOSIT_RECOVERY_WINDOW = timedelta(minutes=10)


def _fetch_onchain_usdc_micro(address: str):
    """Fetch live USDC balance in micro-units for an address.

    Returns None on failure (caller should treat as "unknown" and proceed
    conservatively rather than skip the swap entirely).
    """
    try:
        from django.conf import settings
        from blockchain.algorand_client import get_algod_client

        asset_id = getattr(settings, 'ALGORAND_USDC_ASSET_ID', None)
        if not asset_id:
            return None
        algod_client = get_algod_client()
        info = algod_client.account_info(address)
        for a in (info.get('assets') or []):
            if a.get('asset-id') == asset_id:
                return int(a.get('amount', 0))
        # Opted in to USDC but zero balance, or not opted in.
        return 0
    except Exception as exc:
        logger.warning(
            "[ensure_pending_usdc_auto_swap] on-chain balance fetch failed for %s: %s",
            address, exc,
        )
        return None


def _find_completed_conversion_before_indexer(deposit, amount_decimal):
    """Find an unlinked swap that already consumed this exact indexed deposit."""
    from conversion.models import Conversion

    candidates = list(
        Conversion.objects.filter(
            actor_user_id=deposit.actor_user_id,
            actor_business_id=deposit.actor_business_id,
            actor_type=deposit.actor_type,
            actor_address=deposit.actor_address,
            conversion_type='usdc_to_cusd',
            from_amount=amount_decimal,
            status='COMPLETED',
            pending_auto_swap__isnull=True,
            created_at__gte=deposit.created_at - CONSUMED_DEPOSIT_RECOVERY_WINDOW,
            created_at__lte=deposit.created_at + CONSUMED_DEPOSIT_RECOVERY_WINDOW,
        )
        .order_by('-completed_at', '-created_at')[:2]
    )
    return candidates[0] if len(candidates) == 1 else None


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

    # Pre-flight: if the swap that consumes this deposit's USDC already
    # submitted before the deposit indexer wrote this row, the USDC is
    # already gone from the wallet. Creating a PENDING PAS for it would
    # leave behind a zombie that re-fires days later (see incident:
    # PendingAutoSwap #50, 2026-05-09, re-attempted 2026-05-15 producing
    # a wrong-amount swap of 426.647684 USDC).
    onchain_micro = _fetch_onchain_usdc_micro(deposit.actor_address)
    if onchain_micro is not None and onchain_micro < amount_micro:
        completed_conversion = _find_completed_conversion_before_indexer(
            deposit,
            amount_decimal,
        )
        if completed_conversion:
            recovered, _ = PendingAutoSwap.objects.update_or_create(
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
                    'status': 'COMPLETED',
                    'error_message': '',
                    'conversion': completed_conversion,
                    'completed_at': completed_conversion.completed_at or timezone.now(),
                },
            )
            logger.info(
                "[ensure_pending_usdc_auto_swap] Recovered deposit %s from completed conversion %s",
                deposit.id,
                completed_conversion.internal_id,
            )
            return recovered

        # Record the deposit as a CANCELLED auto-swap so admins can see
        # we acknowledged it but skipped — don't silently drop.
        cancelled, _ = PendingAutoSwap.objects.update_or_create(
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
                'status': 'CANCELLED',
                'error_message': 'orphan_consumed_before_indexer',
                'conversion': None,
                'completed_at': timezone.now(),
            },
        )
        logger.info(
            "[ensure_pending_usdc_auto_swap] Marking deposit %s (%s USDC) CANCELLED — on-chain has %s micro",
            deposit.id, amount_decimal, onchain_micro,
        )
        return cancelled

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
