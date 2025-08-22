from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import logging

from users.models import Account
from .models import RawBlockchainEvent, Balance, TransactionProcessingLog
from django.conf import settings
from .algorand_client import AlgorandClient
from .models import ProcessedIndexerTransaction, IndexerAssetCursor
from usdc_transactions.models import USDCDeposit
from notifications.utils import create_notification
from notifications.models import NotificationType as NotificationTypeChoices
from send.models import SendTransaction

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
                account = Account.objects.filter(algorand_address=owner).first()
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
        
        from .balance_service import BalanceService
        try:
            cusd = BalanceService.get_balance(account, 'CUSD', force_refresh=True)
            confio = BalanceService.get_balance(account, 'CONFIO', force_refresh=True)
            usdc = BalanceService.get_balance(account, 'USDC', force_refresh=True)

            Balance.objects.update_or_create(
                account=account,
                token='CUSD',
                defaults={'amount': cusd['amount']}
            )
            Balance.objects.update_or_create(
                account=account,
                token='CONFIO',
                defaults={'amount': confio['amount']}
            )
            Balance.objects.update_or_create(
                account=account,
                token='USDC',
                defaults={'amount': usdc['amount']}
            )

            cache_key = f"balances:{account.algorand_address}"
            cache.set(cache_key, {
                'cusd': float(cusd['amount']),
                'confio': float(confio['amount']),
                'usdc': float(usdc['amount']),
                'sui': 0.0,
            }, 30)

        finally:
            try:
                loop.close()
            except Exception:
                pass
            
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
            deleted_at__isnull=True,
            algorand_address__isnull=False
        ).values_list('algorand_address', flat=True)
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
        deleted_at__isnull=True,
        algorand_address__isnull=False
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
        account__deleted_at__isnull=True
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
        accounts = Account.objects.filter(algorand_address=sender_address)
        for account in accounts:
            BalanceService.mark_stale(account)
            marked += 1
    
    # Mark recipient balances as stale
    if recipient_addresses:
        for address in recipient_addresses:
            accounts = Account.objects.filter(algorand_address=address)
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


## Sui epoch tracking removed — fully migrated to Algorand


# =====================
# Algorand Indexer scan
# =====================

def _get_asset_decimals(algod_client, asset_id: int) -> int:
    """Fetch and cache ASA decimals."""
    cache_key = f"algo:asset_decimals:{asset_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        info = algod_client.asset_info(asset_id)
        decimals = int(info.get('params', {}).get('decimals', 0))
        cache.set(cache_key, decimals, 3600)  # 1 hour
        return decimals
    except Exception as e:
        logger.error(f"Failed to fetch asset info for {asset_id}: {e}")
        return 0


def _amount_from_base(amount_base: int, decimals: int) -> Decimal:
    q = Decimal(10) ** Decimal(decimals)
    return (Decimal(amount_base) / q).quantize(Decimal('0.000001'))


@shared_task(name='blockchain.scan_inbound_deposits')
def scan_inbound_deposits():
    """
    Asset-centric scanner:
    - For each relevant asset (USDC, cUSD, CONFIO), sweep transactions from the
      last asset cursor to current round using Indexer search by asset-id.
    - Filter in-memory for our user addresses (receiver or close-to), skipping
      internal Confío-to-Confío sends as deposits.
    - Idempotent via (txid, intra) markers.
    - Create USDCDeposit for USDC; send notifications for all assets.
    """
    try:
        # Load user addresses from cache or DB (Set for O(1) lookups)
        addresses: set[str] = cache.get('user_addresses') or set(
            Account.objects.filter(
                deleted_at__isnull=True,
                algorand_address__isnull=False
            ).values_list('algorand_address', flat=True)
        )
        if not addresses:
            logger.info('No user addresses to scan')
            return {'processed': 0}
        try:
            sample = ', '.join([(a[:12] + '...') for a in list(addresses)[:8]])
            logger.info(f"[IndexerScan] tracking {len(addresses)} addresses: {sample}")
        except Exception:
            pass

        # Build quick lookup Account map
        accounts = Account.objects.filter(deleted_at__isnull=True, algorand_address__in=addresses).select_related('user', 'business')
        addr_to_account = {a.algorand_address: a for a in accounts}

        # Set up clients
        client = AlgorandClient()
        algod_client = client.algod
        indexer_client = client.indexer

        # Asset IDs
        USDC_ID = settings.ALGORAND_USDC_ASSET_ID
        CUSD_ID = settings.ALGORAND_CUSD_ASSET_ID
        CONFIO_ID = settings.ALGORAND_CONFIO_ASSET_ID
        # Decimal cache per asset
        asset_ids = [aid for aid in [USDC_ID, CUSD_ID, CONFIO_ID] if aid]
        decimals_map = {aid: _get_asset_decimals(algod_client, aid) for aid in asset_ids}

        # Health snapshot for bounded windows
        try:
            current_round = indexer_client.health().get('round') or algod_client.status().get('last-round', 0)
        except Exception:
            current_round = algod_client.status().get('last-round', 0)

        processed = 0
        skipped = 0

        # Treat deposits from the sponsor/admin as external deposits, not internal transfers
        sponsor_address = None
        try:
            from algosdk import mnemonic as _mn
            from algosdk import account as _acct
            sponsor_mn = getattr(settings, 'ALGORAND_SPONSOR_MNEMONIC', None)
            if sponsor_mn:
                sponsor_address = _acct.address_from_private_key(_mn.to_private_key(sponsor_mn))
        except Exception:
            sponsor_address = None

        def handle_one(axfer_tx: dict, cround: int, intra: int):
            nonlocal processed, skipped
            inner = axfer_tx.get('asset-transfer-transaction', {})
            receiver = inner.get('receiver')
            close_to = inner.get('close-to') or inner.get('close_to')
            sender = axfer_tx.get('sender')
            xaid = inner.get('asset-id')
            aamt = inner.get('amount', 0)
            txid = axfer_tx.get('id')

            # Determine deposit target (receiver or close-to)
            to_addr = receiver or close_to
            if not to_addr or to_addr not in addresses:
                return
            if sender in addresses and (not sponsor_address or sender != sponsor_address):
                # Internal transfer; treat as non-deposit for inbound notification
                logger.info(
                    f"[IndexerScan] skip internal tx: sender={sender} to={to_addr} sponsor={sponsor_address}"
                )
                skipped += 1
                return
            elif sender in addresses and sponsor_address and sender == sponsor_address:
                logger.info(
                    f"[IndexerScan] sponsor deposit: sender={sender} to={to_addr}"
                )

            # Idempotency check by (txid, intra)
            if ProcessedIndexerTransaction.objects.filter(txid=txid, intra=intra or 0).exists():
                skipped += 1
                return

            # Persist processed marker ASAP
            ProcessedIndexerTransaction.objects.create(
                txid=txid,
                asset_id=xaid,
                sender=sender or '',
                receiver=to_addr or '',
                confirmed_round=cround,
                intra=intra or 0,
            )

            # Convert amount
            dec = int(decimals_map.get(xaid, 0))
            human_amt = _amount_from_base(int(aamt), dec)

            account = addr_to_account.get(to_addr)
            if not account:
                return

            if xaid == USDC_ID:
                # Create DB deposit + notification
                try:
                    if account.account_type == 'personal':
                        actor_type = 'user'
                        kwargs = {'actor_user_id': account.user_id, 'actor_business': None}
                    else:
                        actor_type = 'business'
                        kwargs = {'actor_user': None, 'actor_business_id': account.business_id}

                    deposit = USDCDeposit.objects.create(
                        actor_type=actor_type,
                        actor_display_name=account.display_name,
                        actor_address=to_addr,
                        amount=human_amt,
                        source_address=sender or '',
                        network='ALGORAND',
                        status='COMPLETED',
                        **kwargs,
                    )
                    try:
                        create_notification(
                            user=account.user,
                            account=account,
                            business=account.business if account.account_type == 'business' else None,
                            notification_type=NotificationTypeChoices.USDC_DEPOSIT_COMPLETED,
                            title="Depósito USDC recibido",
                            message=f"Recibiste {human_amt} USDC",
                            data={
                                'transaction_id': str(deposit.deposit_id),
                                'transaction_type': 'deposit',
                                'type': 'deposit',
                                'currency': 'USDC',
                                'amount': str(human_amt),
                                'sender': sender,
                                'receiver': to_addr,
                                'txid': txid,
                                'round': cround,
                            },
                            related_object_type='USDCDeposit',
                            related_object_id=str(deposit.id),
                            action_url=f"confio://transaction/{deposit.deposit_id}",
                        )
                    except Exception as ne:
                        logger.warning(f"Failed to create USDC deposit notification: {ne}")
                except Exception as de:
                    logger.error(f"Failed to create USDCDeposit for {to_addr}: {de}")
            else:
                # cUSD or CONFIO inbound notification
                token_name = 'cUSD' if xaid == CUSD_ID else 'CONFIO'
                try:
                    create_notification(
                        user=account.user,
                        account=account,
                        business=account.business if account.account_type == 'business' else None,
                        notification_type=NotificationTypeChoices.SEND_FROM_EXTERNAL,
                        title=f"Depósito {token_name} recibido",
                        message=f"Recibiste {human_amt} {token_name}",
                        data={
                            'token_type': token_name,
                            'amount': str(human_amt),
                            'sender': sender,
                            'receiver': to_addr,
                            'txid': txid,
                            'round': cround,
                        },
                    )
                except Exception as ne:
                    logger.warning(f"Failed to create inbound {token_name} notification: {ne}")

                # Persist as a SendTransaction (external -> Confío) so unified picks it up via signals
                try:
                    from datetime import datetime, timezone as py_tz
                    created_at = datetime.fromtimestamp(
                        tx.get('round-time', cround) or cround,
                        tz=py_tz.utc,
                    )
                    # Use indexer txid and intra for idempotency;
                    # never use empty string for unique transaction_hash
                    idempotency_key = f"ALG:{txid}:{intra or 0}"
                    send_kwargs = {
                        'sender_user': None,
                        'recipient_user': account.user if account.account_type == 'personal' else None,
                        'sender_business': None,
                        'recipient_business': account.business if account.account_type == 'business' else None,
                        'sender_type': 'external',
                        'recipient_type': 'business' if account.account_type == 'business' else 'user',
                        'sender_display_name': 'Billetera externa',
                        'recipient_display_name': account.display_name,
                        'sender_phone': '',
                        'recipient_phone': getattr(account.user, 'phone_number', '') if account.account_type == 'personal' else '',
                        'sender_address': sender or '',
                        'recipient_address': to_addr or '',
                        'amount': human_amt,
                        'token_type': 'CUSD' if token_name == 'cUSD' else 'CONFIO',
                        'memo': f'Depósito {token_name} recibido',
                        'status': 'CONFIRMED',
                        'transaction_hash': txid or None,
                        'idempotency_key': idempotency_key,
                        'error_message': '',
                        'created_at': created_at,
                    }
                    # Create or update the send transaction based on idempotency
                    # If a row with the same transaction_hash already exists, skip
                    if txid:
                        exists = SendTransaction.all_objects.filter(transaction_hash=txid).exists()
                        if not exists:
                            SendTransaction.all_objects.create(**send_kwargs)
                    else:
                        # No txid (inner txns); fall back to idempotency key uniqueness
                        try:
                            SendTransaction.all_objects.create(**send_kwargs)
                        except Exception:
                            # If race/dup, ignore
                            pass
                except Exception as ue:
                    logger.warning(f"Failed to create SendTransaction for inbound {token_name}: {ue}")

            # Mark balances stale for this recipient
            try:
                mark_transaction_balances_stale.delay(txid, sender_address=None, recipient_addresses=[to_addr])
            except Exception:
                pass
            processed += 1

        # Sweep per asset
        for asset_id in asset_ids:
            # Cursor with small rewind
            cursor, _ = IndexerAssetCursor.objects.get_or_create(asset_id=asset_id)
            # Small rewind to catch recent events and avoid misses
            min_round = max(0, (cursor.last_scanned_round or 0) - 500)
            logger.info(
                f"[IndexerScan] asset={asset_id} window {min_round}->{current_round} addresses={len(addresses)}"
            )
            max_seen_round = cursor.last_scanned_round or 0

            next_token = None
            while True:
                try:
                    resp = indexer_client.search_transactions(
                        asset_id=asset_id,
                        min_round=min_round,
                        max_round=current_round,
                        limit=1000,
                        next_page=next_token,
                    )
                except Exception as e:
                    logger.error(f"Indexer search failed (asset={asset_id}): {e}")
                    break

                txs = resp.get('transactions', []) or []
                next_token = resp.get('next-token')

                for tx in txs:
                    try:
                        if tx.get('tx-type') != 'axfer':
                            continue
                        cround = tx.get('confirmed-round') or 0
                        intra = tx.get('intra-round-offset', 0) or 0
                        max_seen_round = max(max_seen_round, cround)

                        # Top-level axfer
                        handle_one(tx, cround, intra)

                        # Inner transactions
                        for inner_tx in tx.get('inner-txns', []) or []:
                            if inner_tx.get('tx-type') == 'axfer':
                                i_intra = inner_tx.get('intra-round-offset', intra)
                                handle_one(inner_tx, cround, i_intra or intra)
                    except Exception as ie:
                        logger.error(f"Error processing tx in asset sweep: {ie}")

                if not next_token:
                    break

            # Advance cursor only to the maximum round actually seen
            if max_seen_round > (cursor.last_scanned_round or 0):
                cursor.last_scanned_round = max_seen_round
                cursor.save(update_fields=['last_scanned_round', 'updated_at'])

        logger.info(f"Indexer scan complete: processed={processed}, skipped={skipped}")
        return {'processed': processed, 'skipped': skipped}
    except Exception as e:
        logger.error(f"scan_inbound_deposits failed: {e}")
        raise
