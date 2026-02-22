import logging
from decimal import Decimal

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from send.models import SendTransaction
from payments.models import PaymentTransaction
from p2p_exchange.models import P2PTrade
from conversion.models import Conversion
from .models_unified import UnifiedTransactionTable
from payroll.models import PayrollRecipient, PayrollItem, PayrollRun
from users.models_employee import BusinessEmployee
from users.models import Account
from achievements.signals import _award_referral_pair
from achievements.services.referral_rewards import (
    EventContext,
    sync_referral_reward_for_event,
)
from django.db import transaction

logger = logging.getLogger(__name__)


def create_unified_transaction_from_send(send_transaction):
    """Create or update UnifiedTransactionTable from SendTransaction"""
    try:
        unified, created = UnifiedTransactionTable.objects.update_or_create(
            send_transaction=send_transaction,
            defaults={
                'transaction_type': 'send',
                'amount': send_transaction.amount,
                'token_type': (send_transaction.token_type or '').upper(),
                'status': send_transaction.status,
                'transaction_hash': send_transaction.transaction_hash or '',
                'error_message': send_transaction.error_message or '',
                
                # Sender info
                'sender_user': send_transaction.sender_user,
                'sender_business': send_transaction.sender_business,
                'sender_type': send_transaction.sender_type,
                'sender_display_name': send_transaction.sender_display_name,
                'sender_phone': send_transaction.sender_phone or '',
                'sender_address': send_transaction.sender_address,
                
                # Counterparty info
                'counterparty_user': send_transaction.recipient_user,
                'counterparty_business': send_transaction.recipient_business,
                'counterparty_type': send_transaction.recipient_type,
                'counterparty_display_name': send_transaction.recipient_display_name,
                'counterparty_phone': send_transaction.recipient_phone,
                'counterparty_address': send_transaction.recipient_address,
                
                # Additional fields
                'description': 'Transferencia',
                'from_address': send_transaction.sender_address,
                'to_address': send_transaction.recipient_address,
                
                # Invitation fields
                'is_invitation': send_transaction.is_invitation,
                'invitation_claimed': send_transaction.invitation_claimed,
                'invitation_reverted': send_transaction.invitation_reverted,
                'invitation_expires_at': send_transaction.invitation_expires_at,
                
                # Timestamps
                'transaction_date': send_transaction.created_at,
                'deleted_at': send_transaction.deleted_at,
            }
        )
        return unified
    except Exception as e:
        logger.exception("Error creating unified transaction from send %s", send_transaction.id)
        return None


def create_unified_transaction_from_payment(payment_transaction):
    """Create or update UnifiedTransactionTable from PaymentTransaction"""
    try:
        # Get invoice description if available
        description = 'Pago'
        if payment_transaction.invoice:
            description = payment_transaction.invoice.description or 'Pago'
        
        unified, created = UnifiedTransactionTable.objects.update_or_create(
            payment_transaction=payment_transaction,
            defaults={
                'transaction_type': 'payment',
                'amount': payment_transaction.amount,
                # Normalize to uppercase to align with filters and choices
                'token_type': (payment_transaction.token_type or '').upper(),
                'status': 'CONFIRMED' if payment_transaction.status == 'PAID' else payment_transaction.status,
                'transaction_hash': payment_transaction.transaction_hash or '',
                'error_message': payment_transaction.error_message or '',
                
                # Sender info (payer)
                'sender_user': payment_transaction.payer_user,
                'sender_business': payment_transaction.payer_business,
                'sender_type': payment_transaction.payer_type,
                'sender_display_name': payment_transaction.payer_display_name,
                'sender_phone': payment_transaction.payer_phone or '',
                'sender_address': payment_transaction.payer_address,
                
                # Counterparty info (merchant)
                'counterparty_user': payment_transaction.merchant_account_user,
                'counterparty_business': payment_transaction.merchant_business,
                'counterparty_type': payment_transaction.merchant_type,
                'counterparty_display_name': payment_transaction.merchant_display_name,
                'counterparty_phone': None,
                'counterparty_address': payment_transaction.merchant_address,
                
                # Additional fields
                'description': description,
                'invoice_id': str(payment_transaction.invoice_id) if payment_transaction.invoice_id else None,
                'payment_reference_id': payment_transaction.id,
                'from_address': payment_transaction.payer_address,
                'to_address': payment_transaction.merchant_address,
                
                # Timestamps
                'transaction_date': payment_transaction.created_at,
                'deleted_at': payment_transaction.deleted_at,
            }
        )
        return unified
    except Exception as e:
        logger.exception("Error creating unified transaction from payment %s", payment_transaction.id)
        return None


def create_unified_transaction_from_p2p_trade(p2p_trade):
    """Create or update UnifiedTransactionTable from P2PTrade"""
    # Only create unified transaction when trade is settled
    if p2p_trade.status not in ['CRYPTO_RELEASED', 'COMPLETED']:
        # Delete if exists and status changed
        UnifiedTransactionTable.objects.filter(p2p_trade=p2p_trade).delete()
        return None
    try:
        # Get offer details
        offer = p2p_trade.offer
        # Normalize token type to match UnifiedTransactionTable choices (CUSD, CONFIO, USDC)
        token_type = (offer.token_type if offer and offer.token_type else 'CUSD').upper()
        
        # Determine sender/counterparty based on trade type
        # In P2P trades, the crypto sender is always the "sender" in unified transactions
        if offer and offer.exchange_type == 'BUY':
            # BUY offer: buyer wants to buy crypto, so seller sends crypto
            sender_user = p2p_trade.seller_user
            sender_business = p2p_trade.seller_business
            counterparty_user = p2p_trade.buyer_user
            counterparty_business = p2p_trade.buyer_business
        else:
            # SELL offer: seller wants to sell crypto, so seller sends crypto
            sender_user = p2p_trade.seller_user
            sender_business = p2p_trade.seller_business
            counterparty_user = p2p_trade.buyer_user
            counterparty_business = p2p_trade.buyer_business
        
        # Build display names
        sender_display_name = ''
        if sender_business:
            sender_display_name = sender_business.name
        elif sender_user:
            sender_display_name = f"{sender_user.first_name} {sender_user.last_name}".strip() or sender_user.username
        
        counterparty_display_name = ''
        if counterparty_business:
            counterparty_display_name = counterparty_business.name
        elif counterparty_user:
            counterparty_display_name = f"{counterparty_user.first_name} {counterparty_user.last_name}".strip() or counterparty_user.username
        
        description = f"Intercambio P2P: {p2p_trade.crypto_amount} {token_type} por {p2p_trade.fiat_amount} {p2p_trade.currency_code}"
        
        # Attempt to include blockchain tx hash from escrow release when available
        release_tx = ''
        try:
            if hasattr(p2p_trade, 'escrow') and p2p_trade.escrow and p2p_trade.escrow.release_transaction_hash:
                release_tx = p2p_trade.escrow.release_transaction_hash
        except Exception:
            release_tx = ''

        unified, created = UnifiedTransactionTable.objects.update_or_create(
            p2p_trade=p2p_trade,
            defaults={
                'transaction_type': 'exchange',
                'amount': str(p2p_trade.crypto_amount),
                'token_type': token_type,
                'status': 'CONFIRMED',  # P2P trades are confirmed when they appear
                'transaction_hash': release_tx or '',
                'error_message': '',
                
                # Sender info
                'sender_user': sender_user,
                'sender_business': sender_business,
                'sender_type': 'business' if sender_business else 'user',
                'sender_display_name': sender_display_name,
                'sender_phone': sender_user.phone_number if sender_user else '',
                'sender_address': '',
                
                # Counterparty info
                'counterparty_user': counterparty_user,
                'counterparty_business': counterparty_business,
                'counterparty_type': 'business' if counterparty_business else 'user',
                'counterparty_display_name': counterparty_display_name,
                'counterparty_phone': counterparty_user.phone_number if counterparty_user else '',
                'counterparty_address': '',
                
                # Additional fields
                'description': description,
                'from_address': '',
                'to_address': '',
                
                # Timestamps - use completed_at if available, otherwise updated_at
                'transaction_date': p2p_trade.completed_at or p2p_trade.updated_at,
                'deleted_at': p2p_trade.deleted_at,
            }
        )
        
        # Update created_at to match when the trade was settled
        if created and (p2p_trade.completed_at or p2p_trade.updated_at):
            UnifiedTransactionTable.objects.filter(id=unified.id).update(
                created_at=p2p_trade.completed_at or p2p_trade.updated_at
            )
        
        return unified
    except Exception as e:
        logger.exception("Error creating unified transaction from P2P trade %s", p2p_trade.id)
        return None


def create_unified_transaction_from_conversion(conversion):
    """Create or update UnifiedTransactionTable from Conversion"""
    try:
        # Defensive refresh: If hashes are missing, ensure we have the latest DB state
        # This handles cases where update_fields might have been used or race conditions occurred
        if not conversion.from_transaction_hash and not conversion.to_transaction_hash:
            try:
                conversion.refresh_from_db(fields=['from_transaction_hash', 'to_transaction_hash'])
            except Exception:
                pass

        # Determine token type based on conversion type
        if conversion.conversion_type == 'usdc_to_cusd':
            token_type = 'USDC'
            description = f"Conversión: {conversion.from_amount} USDC → {conversion.to_amount} cUSD"
        else:
            token_type = 'cUSD'
            description = f"Conversión: {conversion.from_amount} cUSD → {conversion.to_amount} USDC"
        
        # Map status
        status = 'CONFIRMED' if conversion.status == 'COMPLETED' else conversion.status
        if conversion.status == 'PROCESSING':
            status = 'SPONSORING'
        
        unified, created = UnifiedTransactionTable.objects.update_or_create(
            conversion=conversion,
            defaults={
                'transaction_type': 'conversion',
                'amount': str(conversion.from_amount),
                'token_type': token_type,
                'status': status,
                'transaction_hash': conversion.from_transaction_hash or conversion.to_transaction_hash or '',
                'error_message': conversion.error_message or '',
                
                # Sender info (the converter)
                'sender_user': conversion.actor_user,
                'sender_business': conversion.actor_business,
                'sender_type': conversion.actor_type,
                'sender_display_name': conversion.actor_display_name,
                'sender_phone': (conversion.actor_user.phone_number or '') if conversion.actor_user else '',
                'sender_address': conversion.actor_address,
                
                # No real counterparty for conversions (self-transaction)
                'counterparty_user': None,
                'counterparty_business': None,
                'counterparty_type': 'user',
                'counterparty_display_name': 'Confío System',
                'counterparty_phone': None,
                'counterparty_address': '0x0',
                
                # Additional fields
                'description': description,
                'from_address': conversion.actor_address,
                'to_address': conversion.actor_address,
                
                # Timestamps
                'transaction_date': conversion.created_at,
                'deleted_at': conversion.deleted_at if hasattr(conversion, 'deleted_at') else None,
            }
        )
        return unified
    except Exception as e:
        logger.exception("Error creating unified transaction from conversion %s", conversion.id)
        return None


def create_unified_transaction_from_payroll(payroll_item):
    """Create or update UnifiedTransactionTable from PayrollItem"""
    # Only create unified transaction when payroll is confirmed
    if payroll_item.status not in ['CONFIRMED', 'SUBMITTED']:
        return None
    try:
        # Get business and recipient info
        business = payroll_item.run.business
        recipient_user = payroll_item.recipient_user
        recipient_account = payroll_item.recipient_account
        
        # Get business account address (business accounts are stored in Account table)
        business_address = ''
        try:
            from users.models import Account
            business_account = Account.objects.filter(
                business=business,
                account_type='business',
                deleted_at__isnull=True
            ).first()
            if business_account:
                business_address = business_account.algorand_address or ''
        except Exception as e:
            logger.warning(f"Could not get business address for payroll item {payroll_item.id}: {e}")
        
        # Build display names
        business_name = business.name if business else 'Negocio'
        recipient_name = f"{recipient_user.first_name} {recipient_user.last_name}".strip() or recipient_user.username if recipient_user else 'Empleado'
        
        description = f"Pago de nómina: {payroll_item.net_amount} {payroll_item.token_type}"
        
        # Normalize token type
        token_type = (payroll_item.token_type or 'CUSD').upper()
        
        unified, created = UnifiedTransactionTable.objects.update_or_create(
            payroll_item=payroll_item,
            defaults={
                'transaction_type': 'payroll',
                'amount': str(payroll_item.net_amount),
                'token_type': token_type,
                'status': payroll_item.status,
                'transaction_hash': payroll_item.transaction_hash or '',
                'error_message': payroll_item.error_message or '',
                
                # Sender info (business)
                'sender_user': None,
                'sender_business': business,
                'sender_type': 'business',
                'sender_display_name': business_name,
                'sender_phone': '',
                'sender_address': business_address,
                
                # Counterparty info (recipient)
                'counterparty_user': recipient_user,
                'counterparty_business': None,
                'counterparty_type': 'user',
                'counterparty_display_name': recipient_name,
                'counterparty_phone': recipient_user.phone_number if recipient_user else '',
                'counterparty_address': recipient_account.algorand_address if recipient_account else '',
                
                # Additional fields
                'description': description,
                'from_address': business_address or '',
                'to_address': recipient_account.algorand_address or '' if recipient_account else '',
                
                # Timestamps
                'transaction_date': payroll_item.executed_at or payroll_item.updated_at,
                'deleted_at': payroll_item.deleted_at,
            }
        )
        return unified
    except Exception as e:
        logger.exception("Error creating unified transaction from payroll item %s", payroll_item.id)
        return None


# Signal receivers
@receiver(post_save, sender=SendTransaction)
def handle_send_transaction_save(sender, instance, created, **kwargs):
    """Create/update unified transaction when SendTransaction is saved"""
    if instance.deleted_at is None:  # Only process non-deleted transactions
        create_unified_transaction_from_send(instance)
        # Award referral on first successful send by referred user
        try:
            # Consider only successful/confimed sends
            if str(instance.status).upper() in ['CONFIRMED', 'COMPLETED', 'SUCCESS']:
                if instance.sender_user_id:
                    pass
                    # _award_referral_pair(instance.sender_user)
                    # sync_referral_reward_for_event(
                    #     instance.sender_user,
                    #     EventContext(
                    #         event="send",
                    #         amount=Decimal(instance.amount),
                    #         metadata={
                    #             "send_id": instance.id,
                    #             "transaction_hash": instance.transaction_hash or "",
                    #         },
                    #     ),
                    # )
                if instance.recipient_user_id:
                    pass
                    # _award_referral_pair(instance.recipient_user)
        except Exception as exc:
            logger.exception("Error processing referral reward for send %s", instance.id)


@receiver(post_save, sender=PaymentTransaction)
def handle_payment_transaction_save(sender, instance, created, **kwargs):
    """Create/update unified transaction when PaymentTransaction is saved"""
    if instance.deleted_at is None:  # Only process non-deleted transactions
        create_unified_transaction_from_payment(instance)
        # Award referral on first successful merchant payment by referred user
        try:
            # Treat PAID/CONFIRMED as success
            status = str(instance.status).upper()
            if status in ['PAID', 'CONFIRMED']:
                if instance.payer_user_id:
                    pass
                    # _award_referral_pair(instance.payer_user)
                    # sync_referral_reward_for_event(
                    #     instance.payer_user,
                    #     EventContext(
                    #         event="payment",
                    #         amount=Decimal(instance.amount),
                    #         metadata={
                    #             "payment_id": instance.id,
                    #             "invoice_id": instance.invoice_id if instance.invoice_id else None,
                    #         },
                    #     ),
                    # )
        except Exception as exc:
            logger.exception("Error processing referral reward for payment %s", instance.id)


@receiver(post_save, sender=P2PTrade)
def handle_p2p_trade_save(sender, instance, created, **kwargs):
    """Create/update unified transaction when P2PTrade is saved"""
    if instance.deleted_at is None:  # Only process non-deleted transactions
        create_unified_transaction_from_p2p_trade(instance)
        try:
            status = str(instance.status).upper()
            if status in ['CRYPTO_RELEASED', 'COMPLETED']:
                if instance.buyer_user_id:
                    pass
                    # sync_referral_reward_for_event(
                    #     instance.buyer_user,
                    #     EventContext(
                    #         event="p2p_trade",
                    #         amount=Decimal(instance.crypto_amount),
                    #         metadata={
                    #             "trade_id": instance.id,
                    #             "role": "buyer",
                    #         },
                    #     ),
                    # )
                if instance.seller_user_id:
                    pass
                    # sync_referral_reward_for_event(
                    #     instance.seller_user,
                    #     EventContext(
                    #         event="p2p_trade",
                    #         amount=Decimal(instance.crypto_amount),
                    #         metadata={
                    #             "trade_id": instance.id,
                    #             "role": "seller",
                    #         },
                    #     ),
                    # )
        except Exception as exc:
            logger.exception("Error processing referral reward for p2p trade %s", instance.id)


@receiver(post_save, sender=Conversion)
def handle_conversion_save(sender, instance, created, **kwargs):
    """Create/update unified transaction when Conversion is saved"""
    # Conversions don't have deleted_at, check is_deleted instead
    if not instance.is_deleted:
        create_unified_transaction_from_conversion(instance)
        try:
            if (
                instance.conversion_type == 'usdc_to_cusd'
                and instance.status == 'COMPLETED'
                and instance.actor_user_id
            ):
                sync_referral_reward_for_event(
                    instance.actor_user,
                    EventContext(
                        event="conversion_usdc_to_cusd",
                        amount=Decimal(instance.from_amount),
                        metadata={
                            "conversion_id": str(instance.internal_id),
                        },
                    ),
                )
        except Exception as exc:
            logger.exception("Error processing referral reward for conversion %s", instance.id)


@receiver(post_save, sender=PayrollItem)
def handle_payroll_item_save(sender, instance, created, **kwargs):
    """Create/update unified transaction and send notification when PayrollItem is confirmed"""
    if instance.deleted_at is None:  # Only process non-deleted transactions
        # Create unified transaction for CONFIRMED or SUBMITTED status
        if instance.status in ['CONFIRMED', 'SUBMITTED']:
            create_unified_transaction_from_payroll(instance)
            
            # Send notification to recipient when confirmed
            if instance.status == 'CONFIRMED':
                try:
                    from notifications import utils as notif_utils
                    from notifications.models import NotificationType as NotificationTypeChoices
                    
                    business = instance.run.business
                    recipient_user = instance.recipient_user
                    recipient_account = instance.recipient_account
                    
                    # Normalize token type for display
                    token_type = (instance.token_type or 'CUSD').upper()
                    display_token = 'cUSD' if token_type == 'CUSD' else token_type
                    
                    # Create notification for recipient
                    notif_utils.create_notification(
                        user=recipient_user,
                        account=recipient_account,
                        business=None,
                        notification_type=NotificationTypeChoices.PAYROLL_RECEIVED,
                        title="Pago de nómina recibido",
                        message=f"Recibiste {instance.net_amount} {display_token} de {business.name}",
                        data={
                            'transaction_id': instance.internal_id,
                            'transaction_hash': instance.transaction_hash,
                            'transaction_type': 'payroll',
                            'amount': str(instance.net_amount),
                            'token_type': token_type,
                            'business_name': business.name,
                            'status': 'completed',
                        },
                        related_object_type='PayrollItem',
                        related_object_id=str(instance.id),
                        action_url=f"confio://transaction/{instance.internal_id}",
                    )
                    
                    # Create notification for business owner
                    # Get business account
                    business_account = Account.objects.filter(
                        business=business,
                        account_type='business',
                        deleted_at__isnull=True
                    ).first()
                    
                    if business_account:
                        recipient_name = f"{recipient_user.first_name} {recipient_user.last_name}".strip() or recipient_user.username
                        notif_utils.create_notification(
                            user=business_account.user,
                            account=business_account,
                            business=business,
                            notification_type=NotificationTypeChoices.PAYROLL_SENT,
                            title="Nómina enviada",
                            message=f"Enviaste {instance.net_amount} {display_token} a {recipient_name}",
                            data={
                                'transaction_id': instance.internal_id,
                                'transaction_hash': instance.transaction_hash,
                                'transaction_type': 'payroll',
                                'amount': str(instance.net_amount),
                                'token_type': token_type,
                                'recipient_name': recipient_name,
                                'recipient_username': recipient_user.username if recipient_user else '',
                                'recipient_phone': recipient_user.phone_number if recipient_user else '',
                                'recipient_phone_country': recipient_user.phone_country if recipient_user else '',
                                'business_name': business.name if business else 'Empresa',
                                'status': 'completed',
                            },
                            related_object_type='PayrollItem',
                            related_object_id=str(instance.id),
                            action_url=f"confio://transaction/{instance.internal_id}",
                        )
                except Exception as e:
                    logger.warning(f"Failed to create payroll notification for item {instance.internal_id}: {e}")

    # Always sync parent PayrollRun status based on child items
    try:
        sync_payroll_run_status(instance.run_id)
    except Exception as e:
        logger.warning(f"Failed to sync payroll run status for item {instance.internal_id}: {e}")


# Handle soft deletes
@receiver(post_save, sender=SendTransaction)
def handle_send_transaction_soft_delete(sender, instance, **kwargs):
    """Handle soft delete of SendTransaction"""
    if instance.deleted_at is not None:
        UnifiedTransactionTable.objects.filter(send_transaction=instance).update(
            deleted_at=instance.deleted_at
        )


@receiver(post_save, sender=PaymentTransaction)
def handle_payment_transaction_soft_delete(sender, instance, **kwargs):
    """Handle soft delete of PaymentTransaction"""
    if instance.deleted_at is not None:
        UnifiedTransactionTable.objects.filter(payment_transaction=instance).update(
            deleted_at=instance.deleted_at
        )


@receiver(post_save, sender=P2PTrade)
def handle_p2p_trade_soft_delete(sender, instance, **kwargs):
    """Handle soft delete of P2PTrade"""
    if instance.deleted_at is not None:
        UnifiedTransactionTable.objects.filter(p2p_trade=instance).update(
            deleted_at=instance.deleted_at
        )


@receiver(post_save, sender=Conversion)
def handle_conversion_soft_delete(sender, instance, **kwargs):
    """Handle soft delete of Conversion"""
    if instance.is_deleted:
        UnifiedTransactionTable.objects.filter(conversion=instance).update(
            deleted_at=timezone.now()
        )


@receiver(post_save, sender=PayrollItem)
def handle_payroll_item_soft_delete(sender, instance, **kwargs):
    """Handle soft delete of PayrollItem"""
    if instance.deleted_at is not None:
        UnifiedTransactionTable.objects.filter(payroll_item=instance).update(
            deleted_at=instance.deleted_at
        )
    try:
        sync_payroll_run_status(instance.run_id)
    except Exception as e:
        logger.warning(f"Failed to sync payroll run after delete for item {instance.internal_id}: {e}")


def sync_payroll_run_status(run_id: int):
    """
    Update PayrollRun.status based on its items.
    - COMPLETED: all non-deleted items are CONFIRMED
    - PARTIAL: at least one CONFIRMED/SUBMITTED/PREPARED but not all confirmed
    - READY: all items still PENDING
    - CANCELLED: all items are FAILED or CANCELLED
    """
    run = PayrollRun.objects.filter(id=run_id).first()
    if not run:
        return

    items = list(run.items.filter(deleted_at__isnull=True).values_list('status', flat=True))
    if not items:
        return

    statuses = set(items)
    new_status = run.status

    if statuses == {'CONFIRMED'}:
        new_status = 'COMPLETED'
    elif statuses.issubset({'PENDING'}):
        new_status = 'READY'
    elif statuses.issubset({'FAILED', 'CANCELLED'}):
        new_status = 'CANCELLED'
    elif statuses.intersection({'CONFIRMED', 'SUBMITTED', 'PREPARED'}):
        new_status = 'PARTIAL'

    if new_status != run.status:
        run.status = new_status
        run.save(update_fields=['status', 'updated_at'])


# Achievement system signals have been moved to achievements/signals.py
