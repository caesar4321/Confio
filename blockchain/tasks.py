from celery import shared_task
from django.core.cache import cache
from django.db import transaction
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
                    'block_time': tx_data.get('timestampMs', 0)
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