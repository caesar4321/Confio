from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from send.models import SendTransaction
from payments.models import PaymentTransaction
from p2p_exchange.models import P2PTrade
from conversion.models import Conversion
from .models_unified import UnifiedTransactionTable


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
        print(f"Error creating unified transaction from send: {e}")
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
        print(f"Error creating unified transaction from payment: {e}")
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
        print(f"Error creating unified transaction from P2P trade: {e}")
        return None


def create_unified_transaction_from_conversion(conversion):
    """Create or update UnifiedTransactionTable from Conversion"""
    try:
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
                'transaction_hash': conversion.from_transaction_hash or '',
                'error_message': conversion.error_message or '',
                
                # Sender info (the converter)
                'sender_user': conversion.actor_user,
                'sender_business': conversion.actor_business,
                'sender_type': conversion.actor_type,
                'sender_display_name': conversion.actor_display_name,
                'sender_phone': conversion.actor_user.phone_number if conversion.actor_user else '',
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
        print(f"Error creating unified transaction from conversion: {e}")
        return None


# Signal receivers
@receiver(post_save, sender=SendTransaction)
def handle_send_transaction_save(sender, instance, created, **kwargs):
    """Create/update unified transaction when SendTransaction is saved"""
    if instance.deleted_at is None:  # Only process non-deleted transactions
        create_unified_transaction_from_send(instance)


@receiver(post_save, sender=PaymentTransaction)
def handle_payment_transaction_save(sender, instance, created, **kwargs):
    """Create/update unified transaction when PaymentTransaction is saved"""
    if instance.deleted_at is None:  # Only process non-deleted transactions
        create_unified_transaction_from_payment(instance)


@receiver(post_save, sender=P2PTrade)
def handle_p2p_trade_save(sender, instance, created, **kwargs):
    """Create/update unified transaction when P2PTrade is saved"""
    if instance.deleted_at is None:  # Only process non-deleted transactions
        create_unified_transaction_from_p2p_trade(instance)


@receiver(post_save, sender=Conversion)
def handle_conversion_save(sender, instance, created, **kwargs):
    """Create/update unified transaction when Conversion is saved"""
    # Conversions don't have deleted_at, check is_deleted instead
    if not instance.is_deleted:
        create_unified_transaction_from_conversion(instance)


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


# Achievement system signals have been moved to achievements/signals.py
