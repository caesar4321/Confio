from __future__ import annotations

from decimal import Decimal

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from conversion.models import Conversion
from notifications.models import NotificationType as NotificationTypeChoices
from notifications.utils import create_notification
from ramps.models import RampTransaction
from usdc_transactions.models import GuardarianTransaction, USDCDeposit, USDCWithdrawal
from achievements.models import UserReferral
from users.funnel import emit_event
from users.models_unified import UnifiedTransactionTable
from users.utils import touch_user_activity
from send.models import PhoneInvite


def _safe_related(instance, attr_name: str):
    try:
        return getattr(instance, attr_name)
    except Exception:
        return None


def _map_guardarian_status(status: str | None) -> str:
    normalized = (status or '').lower()
    if normalized in {'failed', 'refunded', 'expired'}:
        return 'FAILED'
    if normalized == 'hold':
        return 'AML_REVIEW'
    if normalized == 'finished':
        return 'COMPLETED'
    return 'PROCESSING' if normalized in {'confirmed', 'exchanging', 'sending'} else 'PENDING'


def _derive_guardarian_ramp_outcome(guardarian_tx: GuardarianTransaction) -> tuple[str, str, timezone.datetime | None]:
    provider_status = _map_guardarian_status(guardarian_tx.status)
    provider_status_raw = (guardarian_tx.status or '').lower()
    direction = 'off_ramp' if guardarian_tx.transaction_type == 'sell' else 'on_ramp'
    deposit = guardarian_tx.onchain_deposit
    withdrawal = guardarian_tx.onchain_withdrawal
    conversion = None
    if deposit:
        conversion = _safe_related(deposit, 'ramp_transaction')
        conversion = getattr(conversion, 'conversion', None) if conversion else None
    elif withdrawal:
        conversion = _safe_related(withdrawal, 'ramp_transaction')
        conversion = getattr(conversion, 'conversion', None) if conversion else None

    if direction == 'on_ramp':
        if conversion and conversion.status == 'FAILED':
            return 'FAILED', 'deposit_confirmed_conversion_failed', None
        if conversion and conversion.status == 'COMPLETED':
            return 'COMPLETED', 'conversion_completed', timezone.now()
        if deposit and deposit.status == 'COMPLETED':
            if provider_status == 'FAILED':
                return 'FAILED', 'provider_failed_after_deposit', None
            return 'PROCESSING', 'deposit_confirmed_conversion_pending', None
        if provider_status == 'COMPLETED':
            return 'AML_REVIEW', 'provider_finished_missing_blockchain_match', None
    else:
        if withdrawal and withdrawal.status == 'COMPLETED':
            if provider_status == 'FAILED':
                detail = 'provider_refunded' if provider_status_raw == 'refunded' else 'withdrawal_confirmed_provider_failed'
                return 'FAILED', detail, None
            if provider_status == 'COMPLETED':
                return 'COMPLETED', 'payout_completed', timezone.now()
            if provider_status == 'AML_REVIEW':
                return 'AML_REVIEW', 'provider_aml_review', None
            return 'PROCESSING', 'withdrawal_confirmed_provider_pending', None
        if provider_status == 'COMPLETED':
            return 'AML_REVIEW', 'provider_finished_missing_blockchain_match', None

    if provider_status == 'AML_REVIEW':
        return 'AML_REVIEW', 'provider_aml_review', None
    if provider_status == 'FAILED':
        if provider_status_raw == 'refunded':
            return 'FAILED', 'provider_refunded', None
        if provider_status_raw == 'expired':
            return 'FAILED', 'provider_expired', None
        return 'FAILED', 'provider_failed_pre_blockchain', None
    if provider_status == 'COMPLETED':
        return 'COMPLETED', 'provider_completed', timezone.now()
    if provider_status == 'PROCESSING':
        return 'PROCESSING', f'provider_{provider_status_raw or "processing"}', None
    return 'PENDING', f'provider_{provider_status_raw or "pending"}', None


def _get_guardarian_actor(guardarian_tx: GuardarianTransaction) -> tuple[str, str, object | None, object | None]:
    actor_user = guardarian_tx.user
    actor_business = None
    actor_type = 'user'
    actor_display_name = ''

    if actor_user:
        actor_display_name = f'{actor_user.first_name} {actor_user.last_name}'.strip() or actor_user.username or ''

    return actor_type, actor_display_name, actor_user, actor_business


def _derive_actor_address(ramp_tx: RampTransaction) -> str:
    if ramp_tx.conversion_id and ramp_tx.conversion:
        return ramp_tx.conversion.actor_address or ''
    if ramp_tx.usdc_deposit_id and ramp_tx.usdc_deposit:
        return ramp_tx.usdc_deposit.actor_address or ''
    if ramp_tx.usdc_withdrawal_id and ramp_tx.usdc_withdrawal:
        return ramp_tx.usdc_withdrawal.actor_address or ''
    return ramp_tx.actor_address or ''


def _derive_final_amount(ramp_tx: RampTransaction) -> tuple[Decimal | None, str]:
    if ramp_tx.conversion_id and ramp_tx.conversion:
        if ramp_tx.direction == 'on_ramp':
            return ramp_tx.conversion.to_amount, 'CUSD'
        return ramp_tx.conversion.from_amount, 'CUSD'

    if ramp_tx.crypto_amount_actual is not None:
        return ramp_tx.crypto_amount_actual, 'CUSD'
    if ramp_tx.crypto_amount_estimated is not None:
        return ramp_tx.crypto_amount_estimated, 'CUSD'
    return None, ramp_tx.final_currency or 'CUSD'


def _classify_first_deposit_source(user_id: int | None) -> str:
    if not user_id:
        return 'organic'

    if PhoneInvite.objects.filter(
        claimed_by_id=user_id,
        status='claimed',
    ).exists():
        return 'send_invite'

    if UserReferral.objects.filter(
        referred_user_id=user_id,
    ).exclude(status='inactive').exists():
        return 'referral_link'

    return 'organic'


def sync_ramp_transaction_from_guardarian(guardarian_tx: GuardarianTransaction) -> RampTransaction:
    actor_type, actor_display_name, actor_user, actor_business = _get_guardarian_actor(guardarian_tx)
    direction = 'off_ramp' if guardarian_tx.transaction_type == 'sell' else 'on_ramp'
    final_amount = guardarian_tx.to_amount_actual if direction == 'on_ramp' else guardarian_tx.from_amount
    final_currency = 'CUSD'
    ramp_status, status_detail, completed_at = _derive_guardarian_ramp_outcome(guardarian_tx)

    defaults = {
        'provider': 'guardarian',
        'direction': direction,
        'status': ramp_status,
        'provider_order_id': guardarian_tx.guardarian_id,
        'external_id': guardarian_tx.external_id or '',
        'actor_user': actor_user,
        'actor_business': actor_business,
        'actor_type': actor_type,
        'actor_display_name': actor_display_name,
        'actor_address': (
            guardarian_tx.onchain_deposit.actor_address
            if guardarian_tx.onchain_deposit_id
            else guardarian_tx.onchain_withdrawal.actor_address
            if guardarian_tx.onchain_withdrawal_id
            else ''
        ),
        'fiat_currency': guardarian_tx.from_currency if direction == 'on_ramp' else guardarian_tx.to_currency,
        'fiat_amount': guardarian_tx.from_amount if direction == 'on_ramp' else None,
        'crypto_currency': guardarian_tx.to_currency if direction == 'on_ramp' else guardarian_tx.from_currency,
        'crypto_amount_estimated': guardarian_tx.to_amount_estimated if direction == 'on_ramp' else None,
        'crypto_amount_actual': guardarian_tx.to_amount_actual if direction == 'on_ramp' else guardarian_tx.from_amount,
        'final_currency': final_currency,
        'final_amount': final_amount,
        'status_detail': status_detail if not guardarian_tx.status_details else f'{status_detail}: {guardarian_tx.status_details}',
        'metadata': {
            'guardarian_status': guardarian_tx.status,
            'network': guardarian_tx.network,
        },
        'guardarian_transaction': guardarian_tx,
        'usdc_deposit': guardarian_tx.onchain_deposit,
        'usdc_withdrawal': guardarian_tx.onchain_withdrawal,
        'completed_at': completed_at,
    }

    ramp_tx, _ = RampTransaction.objects.update_or_create(
        guardarian_transaction=guardarian_tx,
        defaults=defaults,
    )
    return ramp_tx


def sync_unified_transaction_from_ramp(ramp_tx: RampTransaction) -> UnifiedTransactionTable:
    actor_address = _derive_actor_address(ramp_tx)
    final_amount, final_currency = _derive_final_amount(ramp_tx)
    status = ramp_tx.status
    if status == 'PROCESSING':
        unified_status = 'PENDING'
    elif status == 'COMPLETED':
        unified_status = 'CONFIRMED'
    elif status == 'FAILED':
        unified_status = 'FAILED'
    elif status == 'AML_REVIEW':
        unified_status = 'AML_REVIEW'
    else:
        unified_status = 'PENDING'

    provider_name = ramp_tx.get_provider_display()
    is_on_ramp = ramp_tx.direction == 'on_ramp'

    defaults = {
        'transaction_type': 'ramp',
        'amount': str(final_amount if final_amount is not None else ramp_tx.fiat_amount or Decimal('0')),
        'token_type': (final_currency or 'CUSD').upper(),
        'status': unified_status,
        'transaction_hash': '',
        'error_message': ramp_tx.status_detail or '',
        'sender_user': None if is_on_ramp else ramp_tx.actor_user,
        'sender_business': None if is_on_ramp else ramp_tx.actor_business,
        'sender_type': 'external' if is_on_ramp else ramp_tx.actor_type,
        'sender_display_name': provider_name if is_on_ramp else (ramp_tx.actor_display_name or ''),
        'sender_phone': '',
        'sender_address': '' if is_on_ramp else actor_address,
        'counterparty_user': ramp_tx.actor_user if is_on_ramp else None,
        'counterparty_business': ramp_tx.actor_business if is_on_ramp else None,
        'counterparty_type': ramp_tx.actor_type if is_on_ramp else 'external',
        'counterparty_display_name': (ramp_tx.actor_display_name or '') if is_on_ramp else provider_name,
        'counterparty_phone': None,
        'counterparty_address': actor_address if is_on_ramp else '',
        'description': 'Recarga' if is_on_ramp else 'Retiro',
        'from_address': '' if is_on_ramp else actor_address,
        'to_address': actor_address if is_on_ramp else '',
        'transaction_date': ramp_tx.created_at,
        'deleted_at': None,
        'ramp_transaction': ramp_tx,
    }

    unified, _ = UnifiedTransactionTable.objects.update_or_create(
        ramp_transaction=ramp_tx,
        defaults=defaults,
    )
    return unified


def _notify_ramp_status(ramp_tx: RampTransaction, *, created: bool, previous_status: str | None):
    if not ramp_tx.actor_user_id:
        return

    is_on_ramp = ramp_tx.direction == 'on_ramp'
    label = 'recarga' if is_on_ramp else 'retiro'
    fiat_amount_display = str(ramp_tx.fiat_amount) if ramp_tx.fiat_amount is not None else ''
    fiat_currency_display = (ramp_tx.fiat_currency or '').strip()
    wallet_amount = ramp_tx.final_amount or ramp_tx.crypto_amount_actual or ramp_tx.crypto_amount_estimated
    wallet_amount_display = str(wallet_amount) if wallet_amount is not None else ''
    wallet_currency_display = (ramp_tx.final_currency or 'CUSD').strip()
    amount_display = fiat_amount_display if is_on_ramp and fiat_amount_display else wallet_amount_display
    token_display = fiat_currency_display if is_on_ramp and fiat_currency_display else wallet_currency_display

    notification_type = None
    title = None
    message = None

    if created and ramp_tx.status in {'PENDING', 'PROCESSING'}:
        notification_type = NotificationTypeChoices.RAMP_PENDING
        title = 'Operación en proceso'
        message = f'Tu {label} está en proceso.'
    elif previous_status != ramp_tx.status and ramp_tx.status == 'PROCESSING' and previous_status == 'PENDING':
        notification_type = NotificationTypeChoices.RAMP_PROCESSING
        title = 'Pago recibido'
        message = f'Recibimos tu pago de {amount_display} {token_display}. Tu {label} se acreditará en breve.' if is_on_ramp else f'Recibimos tu solicitud de {label}. Se acreditará en breve.'
    elif previous_status != ramp_tx.status and ramp_tx.status == 'COMPLETED':
        notification_type = NotificationTypeChoices.RAMP_COMPLETED
        title = 'Operación completada'
        message = f'Tu {label} de {amount_display} {token_display} se completó.'.strip()
    elif previous_status != ramp_tx.status and ramp_tx.status in {'FAILED', 'AML_REVIEW'}:
        notification_type = NotificationTypeChoices.RAMP_FAILED
        title = 'Operación con problema'
        message = (
            f'Tu {label} requiere revisión.'
            if ramp_tx.status == 'AML_REVIEW'
            else f'No pudimos completar tu {label}.'
        )

    if not notification_type:
        return

    create_notification(
        user=ramp_tx.actor_user,
        business=ramp_tx.actor_business,
        notification_type=notification_type,
        title=title,
        message=message,
        data={
            'transaction_type': 'ramp',
            'direction': ramp_tx.direction,
            'provider': ramp_tx.provider,
            'amount': amount_display,
            'token_type': token_display,
            'currency': token_display,
            'ramp_fiat_amount': fiat_amount_display,
            'ramp_fiat_currency': fiat_currency_display,
            'wallet_amount': wallet_amount_display,
            'wallet_currency': wallet_currency_display,
            'internal_id': str(ramp_tx.internal_id),
        },
        related_object_type='RampTransaction',
        related_object_id=str(ramp_tx.internal_id),
        action_url=f'confio://transaction/{ramp_tx.internal_id}',
    )


@receiver(pre_save, sender=RampTransaction)
def cache_previous_ramp_status(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_status = None  # pylint: disable=protected-access
        return
    try:
        previous = sender.objects.get(pk=instance.pk)
        instance._previous_status = previous.status  # pylint: disable=protected-access
    except sender.DoesNotExist:
        instance._previous_status = None  # pylint: disable=protected-access


@receiver(post_save, sender=GuardarianTransaction)
def handle_guardarian_transaction_save(sender, instance, **kwargs):
    ramp_tx = sync_ramp_transaction_from_guardarian(instance)
    if ramp_tx.actor_user_id:
        touch_user_activity(ramp_tx.actor_user_id)


@receiver(post_save, sender=RampTransaction)
def handle_ramp_transaction_save(sender, instance, created, **kwargs):
    sync_unified_transaction_from_ramp(instance)
    previous_status = getattr(instance, '_previous_status', None)
    _notify_ramp_status(instance, created=created, previous_status=previous_status)

    # Emit the first successful on-ramp completion for this user.
    # This captures the `claim -> first_deposit` funnel milestone without
    # coupling to a specific provider implementation path.
    if (
        instance.actor_user_id
        and instance.direction == 'on_ramp'
        and instance.status == 'COMPLETED'
        and previous_status != 'COMPLETED'
    ):
        prior_completed_exists = RampTransaction.objects.filter(
            actor_user_id=instance.actor_user_id,
            direction='on_ramp',
            status='COMPLETED',
        ).exclude(pk=instance.pk).exists()

        if not prior_completed_exists:
            amount_value = (
                instance.final_amount
                or instance.crypto_amount_actual
                or instance.crypto_amount_estimated
            )
            source_type = _classify_first_deposit_source(instance.actor_user_id)
            # Platform is not stored on RampTransaction (server-issued provider record);
            # derive it from the user's most recent funnel event that carried a known
            # platform value (signup_completed, referral_attached, etc.). This keeps the
            # F4 first_deposit event segmentable by iOS/Android without a schema migration.
            derived_platform = ''
            try:
                from users.models_analytics import FunnelEvent
                last_known = (
                    FunnelEvent.objects
                    .filter(user_id=instance.actor_user_id)
                    .exclude(platform='')
                    .order_by('-created_at')
                    .values_list('platform', flat=True)
                    .first()
                )
                if last_known:
                    derived_platform = last_known
            except Exception:
                # Instrumentation must never break the deposit path.
                derived_platform = ''
            emit_event(
                'first_deposit',
                user=instance.actor_user,
                country=instance.country_code or getattr(instance.actor_user, 'phone_country', '') or '',
                platform=derived_platform,
                source_type=source_type,
                channel='koywe' if instance.provider == 'KOYWE' else (instance.provider or '').lower(),
                properties={
                    'provider': instance.provider,
                    'internal_id': str(instance.internal_id),
                    'fiat_currency': instance.fiat_currency or '',
                    'fiat_amount': str(instance.fiat_amount) if instance.fiat_amount is not None else '',
                    'final_currency': instance.final_currency or '',
                    'final_amount': str(amount_value) if amount_value is not None else '',
                },
            )


@receiver(post_save, sender=USDCDeposit)
def handle_ramp_deposit_link(sender, instance, **kwargs):
    guardarian_tx = _safe_related(instance, 'guardarian_source')
    if not guardarian_tx:
        return
    ramp_tx = sync_ramp_transaction_from_guardarian(guardarian_tx)
    if (
        ramp_tx.usdc_deposit_id != instance.id
        or ramp_tx.actor_address != (instance.actor_address or '')
        or ramp_tx.status_detail != 'deposit_confirmed_conversion_pending'
    ):
        ramp_tx.usdc_deposit = instance
        ramp_tx.actor_address = instance.actor_address or ramp_tx.actor_address
        ramp_tx.status = 'PROCESSING'
        ramp_tx.status_detail = 'deposit_confirmed_conversion_pending'
        ramp_tx.save(update_fields=['usdc_deposit', 'actor_address', 'status', 'status_detail', 'updated_at'])


@receiver(post_save, sender=USDCWithdrawal)
def handle_ramp_withdrawal_link(sender, instance, **kwargs):
    guardarian_tx = _safe_related(instance, 'guardarian_dest')
    if not guardarian_tx:
        return
    ramp_tx = sync_ramp_transaction_from_guardarian(guardarian_tx)
    if (
        ramp_tx.usdc_withdrawal_id != instance.id
        or ramp_tx.actor_address != (instance.actor_address or '')
        or ramp_tx.status_detail != 'withdrawal_confirmed_provider_pending'
    ):
        ramp_tx.usdc_withdrawal = instance
        ramp_tx.actor_address = instance.actor_address or ramp_tx.actor_address
        ramp_tx.status = 'PROCESSING'
        ramp_tx.status_detail = 'withdrawal_confirmed_provider_pending'
        ramp_tx.save(update_fields=['usdc_withdrawal', 'actor_address', 'status', 'status_detail', 'updated_at'])


@receiver(post_save, sender=Conversion)
def handle_ramp_conversion_link(sender, instance, **kwargs):
    # Conversion auto-linking is intentionally conservative. Only attach if the conversion
    # is already explicitly linked to a ramp transaction.
    ramp_tx = _safe_related(instance, 'ramp_transaction')
    if not ramp_tx:
        return
    ramp_tx.conversion = instance
    ramp_tx.actor_address = instance.actor_address or ramp_tx.actor_address
    ramp_tx.final_amount, ramp_tx.final_currency = _derive_final_amount(ramp_tx)
    if ramp_tx.provider == 'koywe':
        # Koywe lifecycle is authoritative via the webhook / poller path
        # (sync_koywe_ramp_transaction_from_order). The internal conversion
        # completing only means the cUSD<->USDC swap settled, not that Koywe
        # delivered fiat, so leave status/status_detail/completed_at alone.
        ramp_tx.save(
            update_fields=[
                'conversion',
                'actor_address',
                'final_amount',
                'final_currency',
                'updated_at',
            ]
        )
        return
    if instance.status == 'COMPLETED':
        ramp_tx.status = 'COMPLETED'
        ramp_tx.status_detail = 'conversion_completed'
        if not ramp_tx.completed_at:
            ramp_tx.completed_at = timezone.now()
    elif instance.status == 'FAILED':
        ramp_tx.status = 'FAILED'
        ramp_tx.status_detail = 'deposit_confirmed_conversion_failed'
        ramp_tx.completed_at = None
    else:
        ramp_tx.status = 'PROCESSING'
        ramp_tx.status_detail = 'deposit_confirmed_conversion_pending'
        ramp_tx.completed_at = None
    ramp_tx.save(update_fields=['conversion', 'actor_address', 'final_amount', 'final_currency', 'status', 'status_detail', 'completed_at', 'updated_at'])
