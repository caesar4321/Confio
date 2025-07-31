from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from .models import USDCDeposit, USDCWithdrawal
from conversion.models import Conversion
from .models_unified import UnifiedUSDCTransactionTable


def create_unified_usdc_transaction_from_deposit(deposit):
    """Create or update UnifiedUSDCTransactionTable from USDCDeposit"""
    try:
        unified, created = UnifiedUSDCTransactionTable.objects.update_or_create(
            usdc_deposit=deposit,
            defaults={
                'transaction_id': deposit.deposit_id,
                'transaction_type': 'deposit',
                
                # Actor info
                'actor_user': deposit.actor_user,
                'actor_business': deposit.actor_business,
                'actor_type': deposit.actor_type,
                'actor_display_name': deposit.actor_display_name,
                'actor_address': deposit.actor_address,
                
                # Transaction details
                'amount': deposit.amount,
                'currency': 'USDC',
                'secondary_amount': None,
                'secondary_currency': '',
                'exchange_rate': None,
                
                # Fees
                'network_fee': 0,  # USDC deposits don't have network_fee field
                'service_fee': 0,  # USDC deposits don't have service_fee field
                
                # Addresses
                'source_address': deposit.source_address,
                'destination_address': deposit.actor_address,
                
                # Transaction tracking
                'transaction_hash': None,  # USDC deposits don't have transaction_hash field
                'block_number': None,  # USDC deposits don't have block_number field
                'network': deposit.network,
                
                # Status
                'status': deposit.status,
                'error_message': deposit.error_message,
                
                # Timestamps
                'created_at': deposit.created_at,
                'transaction_date': deposit.created_at,
                'completed_at': deposit.completed_at,
            }
        )
        return unified
    except Exception as e:
        print(f"Error creating unified USDC transaction from deposit: {e}")
        return None


def create_unified_usdc_transaction_from_withdrawal(withdrawal):
    """Create or update UnifiedUSDCTransactionTable from USDCWithdrawal"""
    try:
        unified, created = UnifiedUSDCTransactionTable.objects.update_or_create(
            usdc_withdrawal=withdrawal,
            defaults={
                'transaction_id': withdrawal.withdrawal_id,
                'transaction_type': 'withdrawal',
                
                # Actor info
                'actor_user': withdrawal.actor_user,
                'actor_business': withdrawal.actor_business,
                'actor_type': withdrawal.actor_type,
                'actor_display_name': withdrawal.actor_display_name,
                'actor_address': withdrawal.actor_address,
                
                # Transaction details
                'amount': withdrawal.amount,
                'currency': 'USDC',
                'secondary_amount': None,
                'secondary_currency': '',
                'exchange_rate': None,
                
                # Fees
                'network_fee': 0,  # USDC withdrawals don't have network_fee field  
                'service_fee': withdrawal.service_fee,
                
                # Addresses
                'source_address': withdrawal.actor_address,
                'destination_address': withdrawal.destination_address,
                
                # Transaction tracking
                'transaction_hash': None,  # USDC withdrawals don't have transaction_hash field
                'block_number': None,  # USDC withdrawals don't have block_number field
                'network': withdrawal.network,
                
                # Status
                'status': withdrawal.status,
                'error_message': withdrawal.error_message,
                
                # Timestamps
                'created_at': withdrawal.created_at,
                'transaction_date': withdrawal.created_at,
                'completed_at': withdrawal.completed_at,
            }
        )
        return unified
    except Exception as e:
        print(f"Error creating unified USDC transaction from withdrawal: {e}")
        return None


def create_unified_usdc_transaction_from_conversion(conversion):
    """Create or update UnifiedUSDCTransactionTable from Conversion (USDC-related only)"""
    # Only process USDC-related conversions
    if conversion.conversion_type not in ['usdc_to_cusd', 'cusd_to_usdc']:
        return None
    
    try:
        # Determine amounts and currencies based on conversion type
        if conversion.conversion_type == 'usdc_to_cusd':
            amount = conversion.from_amount
            currency = 'USDC'
            secondary_amount = conversion.to_amount
            secondary_currency = 'cUSD'
        else:  # cusd_to_usdc
            amount = conversion.to_amount
            currency = 'USDC'
            secondary_amount = conversion.from_amount
            secondary_currency = 'cUSD'
        
        unified, created = UnifiedUSDCTransactionTable.objects.update_or_create(
            conversion=conversion,
            defaults={
                'transaction_id': conversion.conversion_id,
                'transaction_type': 'conversion',
                
                # Actor info
                'actor_user': conversion.actor_user,
                'actor_business': conversion.actor_business,
                'actor_type': conversion.actor_type,
                'actor_display_name': conversion.actor_display_name,
                'actor_address': conversion.actor_address,
                
                # Transaction details
                'amount': amount,
                'currency': currency,
                'secondary_amount': secondary_amount,
                'secondary_currency': secondary_currency,
                'exchange_rate': conversion.exchange_rate,
                
                # Fees
                'network_fee': 0,
                'service_fee': conversion.fee_amount,
                
                # Addresses
                'source_address': conversion.actor_address,
                'destination_address': conversion.actor_address,
                
                # Transaction tracking
                'transaction_hash': conversion.from_transaction_hash,
                'block_number': None,
                'network': 'SUI',
                
                # Status
                'status': conversion.status,
                'error_message': conversion.error_message,
                
                # Timestamps
                'created_at': conversion.created_at,
                'transaction_date': conversion.created_at,
                'completed_at': conversion.completed_at,
            }
        )
        return unified
    except Exception as e:
        print(f"Error creating unified USDC transaction from conversion: {e}")
        return None


# Signal receivers
@receiver(post_save, sender=USDCDeposit)
def handle_usdc_deposit_save(sender, instance, created, **kwargs):
    """Create/update unified USDC transaction when USDCDeposit is saved"""
    create_unified_usdc_transaction_from_deposit(instance)


@receiver(post_save, sender=USDCWithdrawal)
def handle_usdc_withdrawal_save(sender, instance, created, **kwargs):
    """Create/update unified USDC transaction when USDCWithdrawal is saved"""
    create_unified_usdc_transaction_from_withdrawal(instance)


@receiver(post_save, sender=Conversion)
def handle_conversion_save_for_usdc(sender, instance, created, **kwargs):
    """Create/update unified USDC transaction when Conversion is saved"""
    # Only process if not deleted and is USDC-related
    if not instance.is_deleted:
        create_unified_usdc_transaction_from_conversion(instance)


# Handle conversion soft deletes
@receiver(post_save, sender=Conversion)
def handle_conversion_soft_delete_for_usdc(sender, instance, **kwargs):
    """Handle soft delete of Conversion for USDC transactions"""
    if instance.is_deleted:
        # Delete the unified USDC transaction if it exists
        UnifiedUSDCTransactionTable.objects.filter(conversion=instance).delete()