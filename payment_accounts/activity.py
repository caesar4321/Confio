"""One wallet activity item per local transfer; provider legs remain audit data."""
from decimal import Decimal
import logging
import re

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import InfiniaJourney, MoneyFlow, PaymentBridgeTransfer

logger = logging.getLogger(__name__)


def local_mint_journey_id(request_id):
    match = re.fullmatch(r'local-mint-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:_r[1-9])?_a[01]', request_id or '')
    return match[1] if match else None


def mint_request_id(j):
    """Transport retries retain identity; only proven non-execution advances it."""
    from blockchain.models import SponsoredBatch
    for retry in range(10):
        prefix = f'local-mint-{j.internal_id}' + (f'_r{retry}' if retry else '')
        states = list(SponsoredBatch.objects.filter(user=j.confio_account.user,
            user_bsc_address__iexact=j.wallet_address,
            client_request_id__in=[prefix + '_a0', prefix + '_a1']).values_list('status', flat=True))
        if not states or any(s not in ['reverted', 'noop_failed'] for s in states):
            return prefix
    raise ValueError('Local mint retry requires review')


def _link_mint(j):
    """Explicit, signed request identity, never an amount-only heuristic."""
    from blockchain.models import SponsoredBatch
    from conversion.models import Conversion
    if j.direction != 'to_wallet' or not j.bridge_id or j.bridge.status != 'delivered':
        return
    if j.wallet_conversion_id and j.wallet_conversion.status != 'FAILED':
        return
    hashes = SponsoredBatch.objects.filter(user=j.confio_account.user,
        user_bsc_address__iexact=j.wallet_address,
        client_request_id__in=[f'local-mint-{j.internal_id}' + (f'_r{r}' if r else '') + f'_a{a}'
                              for r in range(10) for a in range(2)],
        kind__in=['mint_cusd', 'subscribe'], status__in=['signed', 'sent', 'confirmed']
    ).values_list('tx_hash', flat=True)
    candidates = Conversion.objects.filter(to_transaction_hash__in=hashes,
        user_bsc_address__iexact=j.wallet_address, is_deleted=False,
        conversion_type__in=['usdt_to_cusd', 'to_savings'],
        gross_amount_exact=Decimal(j.bridge.actual_out_units) / Decimal(10**18)
    ).exclude(status='FAILED')
    candidates = candidates.filter(actor_business=j.confio_account.business) if j.confio_account.account_type == 'business' else candidates.filter(actor_user=j.confio_account.user, actor_business__isnull=True)
    rows = list(candidates[:2])
    if len(rows) == 1:
        InfiniaJourney.objects.filter(pk=j.pk).update(wallet_conversion=rows[0])
        j.wallet_conversion = rows[0]


def display_stage(j):
    if j.direction == 'to_bank' and j.bridge_id and j.bridge.status == 'refunded':
        return 'refunded'
    if j.direction == 'to_wallet' and j.stage == 'completed':
        if not j.wallet_conversion_id or j.wallet_conversion.status != 'COMPLETED':
            return 'awaiting_wallet_conversion'
    return j.stage


def arrival_owned(tx_hash, wallet):
    if not tx_hash:
        return False
    return (InfiniaJourney.objects.filter(direction='to_wallet', wallet_address__iexact=wallet,
        bridge__destination_tx_hash__iexact=tx_hash, bridge__status='delivered').exists()
        or InfiniaJourney.objects.filter(direction='to_bank', wallet_address__iexact=wallet,
            bridge__status__in=['refunded', 'needs_review'],
            bridge__binding__settlement_evidence__status='refund',
            bridge__binding__settlement_evidence__token_id='BSC:USDT',
            bridge__binding__settlement_evidence__recipient__iexact=wallet,
            bridge__binding__settlement_evidence__transaction_hashes__contains=[tx_hash.lower()]).exists())


def _retarget_notice(notice, j, label):
    notice.data = dict(notice.data, local_transfer_id=str(j.internal_id),
        pending_auto_mint=False, corrected_to_local_transfer=True)
    notice.title, notice.message = label, 'Consulta el estado de tu transferencia.'
    notice.notification_type = 'LOCAL_TRANSFER_UPDATED'
    notice.action_url = f'confio://local-transfer/{j.internal_id}'
    notice.related_object_type, notice.related_object_id = 'InfiniaJourney', str(j.internal_id)
    notice.save()


def _push_notice(pk):
    from notifications.models import Notification
    from notifications.fcm_service import send_push_notification
    try:
        send_push_notification(Notification.objects.get(pk=pk))
    except Exception:
        logger.exception('Local transfer push failed for notification %s', pk)


@transaction.atomic
def sync_activity(journey_id, *, notify=True):
    from conversion.models import Conversion
    from send.models import SendTransaction
    from notifications.models import Notification
    from users.models_unified import UnifiedTransactionTable
    j = InfiniaJourney.objects.select_for_update(of=('self',)).select_related(
        'confio_account__user', 'confio_account__business', 'money_flow', 'bridge',
        'wallet_conversion').get(pk=journey_id)
    _link_mint(j)
    incoming = j.direction == 'to_wallet'
    bridge = j.bridge
    # A quote or unsigned instruction has not changed the wallet.
    if not incoming and (not bridge or not bridge.source_tx_hash):
        return None
    owner = j.confio_account
    business = owner.business if owner.account_type == 'business' else None
    stage = display_stage(j)
    amount = j.money_flow.source_amount if not incoming else Decimal(0)
    token = 'CUSD_BSC'
    if incoming and j.wallet_conversion_id and j.wallet_conversion.status == 'COMPLETED':
        conversion = j.wallet_conversion
        amount = conversion.net_amount_exact if conversion.net_amount_exact is not None else conversion.to_amount
        token = 'CUSD_PLUS' if conversion.conversion_type == 'to_savings' else 'CUSD_BSC'
    status = 'CONFIRMED' if stage == 'completed' else 'FAILED' if stage in ['failed', 'refunded'] else 'PENDING'
    label = 'Ingreso por cuenta local' if incoming else 'Envío reembolsado' if stage == 'refunded' else 'Envío a banco o billetera'
    destination = j.destination_snapshot.get('display_label', '')
    row, created = UnifiedTransactionTable.objects.update_or_create(local_money_flow=j.money_flow, defaults={
        'transaction_type': 'local_transfer', 'amount': str(amount or 0), 'token_type': token,
        'amount_denomination': 'USD_VALUE' if token == 'CUSD_PLUS' else 'TOKEN_UNITS',
        'status': status, 'description': label, 'transaction_date': j.created_at,
        'sender_user': None if incoming or business else owner.user,
        'sender_business': None if incoming else business,
        'sender_type': 'external' if incoming else 'business' if business else 'user',
        'sender_display_name': 'Cuenta local' if incoming else owner.display_name or '',
        'sender_address': '' if incoming else j.wallet_address,
        'counterparty_user': owner.user if incoming and not business else None,
        'counterparty_business': business if incoming else None,
        'counterparty_type': ('business' if business else 'user') if incoming else 'external',
        'counterparty_display_name': owner.display_name or '' if incoming else destination,
        'to_address': j.wallet_address if incoming else '',
    })
    if created:
        # Wallet queries sort by created_at, so a historical backfill must not
        # move an old transfer to the top of today's activity.
        UnifiedTransactionTable.objects.filter(pk=row.pk).update(created_at=j.created_at)
        row.created_at = j.created_at
    tx_hash = bridge.destination_tx_hash if incoming and bridge else bridge.source_tx_hash if bridge else ''
    receipt_hashes = [tx_hash] if tx_hash else []
    # A verified partial refund remains needs_review, but is still a return
    # belonging to this transfer, not an unrelated external deposit.
    if bridge and not incoming and bridge.status in ['refunded', 'needs_review'] and (
            bridge.binding.get('settlement_evidence', {}).get('status') == 'refund'):
        receipt_hashes += bridge.binding.get('settlement_evidence', {}).get('transaction_hashes', [])
    if receipt_hashes:
        receipts = SendTransaction.all_objects.filter(transaction_hash__in=receipt_hashes,
            recipient_address__iexact=j.wallet_address, sender_type='external', token_type='USDT')
        UnifiedTransactionTable.objects.filter(send_transaction__in=receipts).update(deleted_at=timezone.now())
        receipts.filter(deleted_at__isnull=True).update(deleted_at=timezone.now())
        # Existing scanner notices become transfer notices, keeping their audit data.
        for notice in Notification.objects.filter(data__tx_hash__in=receipt_hashes,
                data__recipient_address__iexact=j.wallet_address,
                notification_type__in=['SEND_FROM_EXTERNAL', 'CONVERSION_COMPLETED']):
            _retarget_notice(notice, j, label)
    if incoming and j.wallet_conversion_id:
        # The mint scanner can beat best-effort conversion history creation.
        # Only the explicitly linked mint hash and zero-address mint receipts
        # belong to this parent; ordinary token transfers remain visible.
        mint_hash = j.wallet_conversion.to_transaction_hash
        mint_receipts = SendTransaction.all_objects.filter(
            transaction_hash__iexact=mint_hash, recipient_address__iexact=j.wallet_address,
            sender_type='external', sender_address__in=['', '0x' + '0' * 40],
            token_type__in=['CUSD_PLUS', 'CUSD_BSC', 'CUSD'])
        UnifiedTransactionTable.objects.filter(send_transaction__in=mint_receipts).update(deleted_at=timezone.now())
        mint_receipts.filter(deleted_at__isnull=True).update(deleted_at=timezone.now())
        for notice in Notification.objects.filter(user=owner.user, data__tx_hash=mint_hash,
                notification_type='SEND_RECEIVED', data__recipient_address__iexact=j.wallet_address):
            _retarget_notice(notice, j, label)
    conversions = Conversion.objects.none()
    if not incoming and tx_hash:
        conversions = Conversion.objects.filter(to_transaction_hash__iexact=tx_hash,
            user_bsc_address__iexact=j.wallet_address, conversion_type__in=['cusd_to_usdt', 'from_savings'])
    elif j.wallet_conversion_id:
        conversions = Conversion.objects.filter(pk=j.wallet_conversion_id)
    UnifiedTransactionTable.objects.filter(conversion__in=conversions).update(deleted_at=timezone.now())
    # Persist one notification per public state. No duplicate on repeated polling.
    from notifications.utils import create_notification
    key = f'local-transfer:{j.internal_id}:{stage}'
    if not Notification.objects.filter(user=owner.user, data__event_key=key).exists():
        notice = create_notification(user=owner.user, account=owner, business=business,
            notification_type='LOCAL_TRANSFER_UPDATED', title=label,
            message=('Transferencia completada.' if stage == 'completed' else
                     'El puente devolvió los fondos. Consulta el importe y la moneda recibidos.' if stage == 'refunded' else
                     'No se completó. Consulta el estado antes de intentarlo de nuevo.' if stage in ['failed', 'needs_review']
                     else 'Tu transferencia está en proceso.'),
            data={'event_key': key, 'local_transfer_id': str(j.internal_id), 'stage': stage},
            send_push=False,
            action_url=f'confio://local-transfer/{j.internal_id}',
            related_object_type='InfiniaJourney', related_object_id=str(j.internal_id))
        if notify:
            transaction.on_commit(lambda: _push_notice(notice.pk))
    return row


def _refresh(ids):
    for pk in ids:
        try:
            sync_activity(pk)
        except Exception:
            logger.exception('Local transfer activity refresh failed for %s', pk)


def refresh_stale_activity(limit=100):
    """Repair missed post-commit callbacks, including terminal journeys."""
    from django.db.models import F, Q
    rows = InfiniaJourney.objects.filter(
        Q(direction='to_wallet') | (Q(bridge__isnull=False) & ~Q(bridge__source_tx_hash=''))
    ).filter(
        Q(money_flow__unified_transaction__isnull=True)
        | Q(updated_at__gt=F('money_flow__unified_transaction__updated_at'))
        | Q(bridge__updated_at__gt=F('money_flow__unified_transaction__updated_at'))
        | Q(wallet_conversion__updated_at__gt=F('money_flow__unified_transaction__updated_at'))
        | (Q(direction='to_wallet', bridge__status='delivered')
           & (Q(wallet_conversion__isnull=True) | Q(wallet_conversion__status='FAILED')))
    ).order_by(F('money_flow__unified_transaction__updated_at').asc(nulls_first=True), 'pk')
    _refresh(list(rows.values_list('pk', flat=True)[:limit]))


@receiver(post_save, sender=InfiniaJourney)
@receiver(post_save, sender=MoneyFlow)
@receiver(post_save, sender=PaymentBridgeTransfer)
def journey_changed(sender, instance, **kwargs):
    query = InfiniaJourney.objects.filter(**(
        {'pk': instance.pk} if sender is InfiniaJourney else
        {'money_flow': instance} if sender is MoneyFlow else {'bridge': instance}))
    ids = list(query.values_list('pk', flat=True))
    transaction.on_commit(lambda: _refresh(ids))


@receiver(post_save, sender='conversion.Conversion')
def conversion_changed(sender, instance, **kwargs):
    ids = list(InfiniaJourney.objects.filter(wallet_conversion=instance).values_list('pk', flat=True))
    if instance.to_transaction_hash:
        ids += list(InfiniaJourney.objects.filter(direction='to_bank',
            bridge__source_tx_hash__iexact=instance.to_transaction_hash).values_list('pk', flat=True))
        from blockchain.models import SponsoredBatch
        for request_id in SponsoredBatch.objects.filter(tx_hash__iexact=instance.to_transaction_hash).values_list('client_request_id', flat=True):
            journey_id = local_mint_journey_id(request_id)
            if journey_id:
                ids += list(InfiniaJourney.objects.filter(internal_id=journey_id).values_list('pk', flat=True))
    transaction.on_commit(lambda: _refresh(ids))
