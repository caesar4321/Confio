from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import logging

from users.models import Account
from transactions.models import Transaction
from .models import RawBlockchainEvent, Balance, TransactionProcessingLog
from .sui_client import sui_client

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def process_transaction(self, tx_data):
    """Process a blockchain transaction"""
    try:
        with transaction.atomic():
            # Save raw event
            raw_event, created = RawBlockchainEvent.objects.get_or_create(
                tx_hash=tx_data['digest'],
                defaults={
                    'sender': tx_data.get('transaction', {}).get('data', {}).get('sender', ''),
                    'module': extract_module(tx_data),
                    'function': extract_function(tx_data),
                    'raw_data': tx_data,
                    'block_time': tx_data.get('timestampMs', 0),
                    'epoch': tx_data.get('checkpoint', {}).get('epoch'),
                    'checkpoint': tx_data.get('checkpoint', {}).get('sequenceNumber')
                }
            )
            
            if not created and raw_event.processed:
                logger.info(f"Transaction {tx_data['digest']} already processed")
                return
            
            # Log processing attempt
            log = TransactionProcessingLog.objects.create(
                raw_event=raw_event,
                status='processing'
            )
            
            # Determine transaction type and process
            module = raw_event.module
            if 'cusd' in module.lower():
                handle_cusd_transaction.delay(raw_event.id)
            elif 'pay' in module.lower():
                handle_payment_transaction.delay(raw_event.id)
            elif 'p2p_trade' in module.lower():
                handle_p2p_trade_transaction.delay(raw_event.id)
            elif 'invite_send' in module.lower():
                handle_invitation_transaction.delay(raw_event.id)
            else:
                logger.warning(f"Unknown transaction type: {module}")
                
            # Mark as processed
            raw_event.processed = True
            raw_event.save()
            
            log.status = 'completed'
            log.save()
            
    except Exception as e:
        logger.error(f"Failed to process transaction: {e}")
        if 'log' in locals():
            log.status = 'failed'
            log.error_message = str(e)
            log.attempts += 1
            log.save()
        
        # Retry
        self.retry(countdown=60 * (self.request.retries + 1))


@shared_task
def handle_cusd_transaction(raw_event_id):
    """Process cUSD transfer"""
    try:
        raw_event = RawBlockchainEvent.objects.get(id=raw_event_id)
        tx_data = raw_event.raw_data
        
        # Extract balance changes
        balance_changes = tx_data.get('balanceChanges', [])
        
        for change in balance_changes:
            if 'cusd' in change.get('coinType', '').lower():
                owner = change['owner']['AddressOwner']
                amount = Decimal(change['amount']) / Decimal(10 ** 6)  # cUSD has 6 decimals
                
                # Find user account
                account = Account.objects.filter(sui_address=owner).first()
                if account:
                    # Update balance cache
                    update_user_balances.delay(account.id)
                    
                    # Create transaction record if receiving
                    if amount > 0:
                        Transaction.objects.create(
                            account=account,
                            tx_hash=raw_event.tx_hash,
                            type='received',
                            amount=abs(amount),
                            token='CUSD',
                            status='completed',
                            blockchain_timestamp=raw_event.block_time
                        )
                        
                        # Send notification
                        from notifications.tasks import send_push_notification
                        send_push_notification.delay(
                            account.user.id,
                            f"Recibiste {amount} cUSD",
                            {'type': 'transaction', 'tx_hash': raw_event.tx_hash}
                        )
                        
    except Exception as e:
        logger.error(f"Error handling cUSD transaction: {e}")
        raise


@shared_task
def handle_payment_transaction(raw_event_id):
    """Process payment through Pay contract"""
    # Similar structure - extract payment details and process
    pass


@shared_task
def handle_p2p_trade_transaction(raw_event_id):
    """Process P2P trade events"""
    # Handle trade creation, acceptance, completion, disputes
    pass


@shared_task
def handle_invitation_transaction(raw_event_id):
    """Process invitation events"""
    # Handle invitation creation, claims, reclaims
    pass


@shared_task(bind=True, max_retries=3)
def update_user_balances(self, account_id):
    """Update all token balances for a user"""
    try:
        account = Account.objects.get(id=account_id)
        
        # Use async client in sync context
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Get balances from blockchain
            cusd_balance = loop.run_until_complete(
                sui_client.get_cusd_balance(account.sui_address)
            )
            confio_balance = loop.run_until_complete(
                sui_client.get_confio_balance(account.sui_address)
            )
            sui_balance = loop.run_until_complete(
                sui_client.get_sui_balance(account.sui_address)
            )
            
            # Update database
            Balance.objects.update_or_create(
                account=account,
                token='CUSD',
                defaults={'amount': cusd_balance}
            )
            Balance.objects.update_or_create(
                account=account,
                token='CONFIO',
                defaults={'amount': confio_balance}
            )
            Balance.objects.update_or_create(
                account=account,
                token='SUI',
                defaults={'amount': sui_balance}
            )
            
            # Update cache
            cache_key = f"balances:{account.sui_address}"
            cache.set(cache_key, {
                'cusd': float(cusd_balance),
                'confio': float(confio_balance),
                'sui': float(sui_balance)
            }, 30)
            
        finally:
            loop.close()
            
    except Account.DoesNotExist:
        logger.error(f"Account {account_id} not found")
    except Exception as e:
        logger.error(f"Failed to update balances: {e}")
        self.retry(countdown=60)


@shared_task
def update_address_cache():
    """Update cached user addresses for polling"""
    addresses = set(
        Account.objects.filter(
            is_active=True,
            sui_address__isnull=False
        ).values_list('sui_address', flat=True)
    )
    
    cache.set('user_addresses', addresses, timeout=300)  # 5 minutes
    logger.info(f"Updated {len(addresses)} user addresses in cache")
    
    return len(addresses)


@shared_task
def reconcile_all_balances():
    """
    Reconcile all user balances with blockchain
    Run this periodically (e.g., every hour)
    """
    from .balance_service import BalanceService
    
    # Get all active accounts with stale or old balances
    stale_threshold = timezone.now() - timedelta(hours=1)
    accounts = Account.objects.filter(
        is_active=True,
        sui_address__isnull=False
    ).filter(
        Q(balances__is_stale=True) |
        Q(balances__last_blockchain_check__lt=stale_threshold) |
        Q(balances__last_blockchain_check__isnull=True)
    ).distinct()
    
    success_count = 0
    error_count = 0
    
    for account in accounts:
        try:
            results = BalanceService.reconcile_user_balances(account)
            if all(results.values()):
                success_count += 1
            else:
                error_count += 1
                logger.warning(f"Partial reconciliation failure for {account}: {results}")
        except Exception as e:
            error_count += 1
            logger.error(f"Failed to reconcile balances for {account}: {e}")
    
    logger.info(f"Balance reconciliation complete: {success_count} success, {error_count} errors")
    
    # Alert if too many errors
    if error_count > accounts.count() * 0.1:  # More than 10% failure
        logger.critical(f"High balance reconciliation failure rate: {error_count}/{accounts.count()}")
        # TODO: Send alert to monitoring
    
    return {'success': success_count, 'errors': error_count}


@shared_task
def refresh_stale_balances():
    """
    Refresh balances marked as stale
    Run this more frequently (e.g., every 5 minutes)
    """
    from .balance_service import BalanceService
    
    stale_balances = Balance.objects.filter(
        is_stale=True,
        account__is_active=True
    ).select_related('account')[:100]  # Batch limit
    
    refreshed = 0
    for balance in stale_balances:
        try:
            BalanceService.get_balance(
                balance.account,
                balance.token,
                force_refresh=True
            )
            refreshed += 1
        except Exception as e:
            logger.error(f"Failed to refresh balance {balance}: {e}")
            balance.sync_attempts += 1
            balance.save(update_fields=['sync_attempts'])
    
    logger.info(f"Refreshed {refreshed} stale balances")
    return refreshed


@shared_task
def mark_transaction_balances_stale(tx_hash, sender_address=None, recipient_addresses=None):
    """
    Mark balances as stale after detecting a transaction
    Called by the polling service
    """
    from .balance_service import BalanceService
    
    marked = 0
    
    # Mark sender balance as stale
    if sender_address:
        accounts = Account.objects.filter(sui_address=sender_address)
        for account in accounts:
            BalanceService.mark_stale(account)
            marked += 1
    
    # Mark recipient balances as stale
    if recipient_addresses:
        for address in recipient_addresses:
            accounts = Account.objects.filter(sui_address=address)
            for account in accounts:
                BalanceService.mark_stale(account)
                marked += 1
    
    logger.info(f"Marked {marked} balances as stale for transaction {tx_hash}")
    return marked


# Helper functions
def extract_module(tx_data):
    """Extract module from transaction data"""
    if 'objectChanges' in tx_data:
        for change in tx_data['objectChanges']:
            if change.get('type') == 'created':
                return change.get('objectType', '').split('::')[0]
    return 'unknown'


def extract_function(tx_data):
    """Extract function from transaction data"""
    tx = tx_data.get('transaction', {}).get('data', {}).get('transaction', {})
    if isinstance(tx, dict) and tx.get('kind') == 'ProgrammableTransaction':
        for cmd in tx.get('transactions', []):
            if 'MoveCall' in cmd:
                return cmd['MoveCall'].get('function', 'unknown')
    return 'unknown'


@shared_task
def cleanup_old_events():
    """Clean up old blockchain events"""
    # Keep events for 90 days
    cutoff = timezone.now() - timedelta(days=90)
    deleted_count = RawBlockchainEvent.objects.filter(
        created_at__lt=cutoff,
        processed=True
    ).delete()[0]
    
    logger.info(f"Cleaned up {deleted_count} old blockchain events")
    return deleted_count


@shared_task
def track_epoch_change():
    """
    Monitor and track Sui epoch changes
    Run this every 30 minutes
    """
    from .models import SuiEpoch
    import asyncio
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # Get current epoch info
        epoch_info = loop.run_until_complete(sui_client.get_epoch_info())
        
        current_epoch_num = int(epoch_info['epoch'])
        epoch_start_ms = int(epoch_info['epochStartTimestampMs'])
        
        # Check if this epoch is already tracked
        current_epoch, created = SuiEpoch.objects.get_or_create(
            epoch_number=current_epoch_num,
            defaults={
                'start_timestamp_ms': epoch_start_ms,
                'first_checkpoint': 0,  # Will be updated later
                'is_current': True
            }
        )
        
        if created:
            logger.info(f"New epoch detected: {current_epoch_num}")
            
            # Mark previous epochs as not current
            SuiEpoch.objects.filter(is_current=True).exclude(
                epoch_number=current_epoch_num
            ).update(is_current=False)
            
            # Try to finalize previous epoch
            try:
                previous_epoch = SuiEpoch.objects.filter(
                    epoch_number=current_epoch_num - 1
                ).first()
                
                if previous_epoch and not previous_epoch.end_timestamp_ms:
                    previous_epoch.end_timestamp_ms = epoch_start_ms - 1
                    previous_epoch.save()
                    logger.info(f"Finalized epoch {previous_epoch.epoch_number}")
            except Exception as e:
                logger.error(f"Error finalizing previous epoch: {e}")
        
        # Update current epoch stats
        if epoch_info.get('totalStake'):
            current_epoch.total_stake = int(epoch_info['totalStake'])
        if epoch_info.get('storageFundNonRefundableBalance'):
            current_epoch.storage_fund_balance = int(epoch_info['storageFundNonRefundableBalance'])
        
        current_epoch.save()
        
        return {
            'epoch': current_epoch_num,
            'created': created,
            'start_time': epoch_start_ms
        }
        
    except Exception as e:
        logger.error(f"Failed to track epoch: {e}")
        raise
    finally:
        loop.close()