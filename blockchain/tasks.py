from celery import shared_task
from django.core.cache import cache
from django.db import transaction, connection
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import logging
from functools import wraps

from users.models import Account
from users.models_unified import UnifiedTransactionTable
from .models import Balance
from django.conf import settings
from .algorand_client import AlgorandClient
from .models import ProcessedIndexerTransaction, IndexerAssetCursor
from usdc_transactions.models import USDCDeposit
from notifications import utils as notif_utils
from notifications.models import NotificationType as NotificationTypeChoices
from send.models import SendTransaction
from payments.models import PaymentTransaction
from presale.models import PresalePurchase
from conversion.models import Conversion
from p2p_exchange.models import P2PEscrow, P2PTrade
from send.models import SendTransaction
from notifications.models import NotificationType as NotifType

logger = logging.getLogger(__name__)


def ensure_db_connection_closed(func):
    """Decorator to ensure database connections are properly closed after task execution"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            # Explicitly close database connections to prevent accumulation
            connection.close()
    return wrapper


"""
Legacy Sui transaction handlers (process_transaction, handle_cusd_transaction, etc.)
have been removed. Algorand deposits are handled by scan_inbound_deposits below.
"""


@shared_task(bind=True, max_retries=3)
@ensure_db_connection_closed
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
@ensure_db_connection_closed
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
@ensure_db_connection_closed
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
@ensure_db_connection_closed
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
@ensure_db_connection_closed
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


# Removed old Sui event helpers and cleanup task


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
@ensure_db_connection_closed
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
    # Prevent overlapping runs (in case of slow scans or multiple workers)
    from django.core.cache import cache as _cache
    _lock_key = 'locks:scan_inbound_deposits'
    # Fail-safe TTL; lock is explicitly released in finally
    if not _cache.add(_lock_key, '1', timeout=60):
        logger.info('[IndexerScan] Skipping run: another scan_inbound_deposits is active')
        return {'skipped': True, 'reason': 'locked'}

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

            # Ignore zero-amount asset transfers (opt-ins, no-op clawbacks)
            try:
                if int(aamt or 0) <= 0:
                    skipped += 1
                    return
            except Exception:
                pass

            # Determine deposit target (receiver or close-to)
            to_addr = receiver or close_to
            if not to_addr or to_addr not in addresses:
                return
            confio_sender = sender in addresses
            sponsor_sender = sponsor_address and sender == sponsor_address

            if confio_sender and not sponsor_sender:
                # Internal transfer; treat as non-deposit for inbound notification
                logger.info(
                    f"[IndexerScan] skip internal tx: sender={sender} to={to_addr} sponsor={sponsor_address}"
                )
                skipped += 1
                return
            elif sponsor_sender:
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
                        notif_utils.create_notification(
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
                    notif_utils.create_notification(
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

            # Advance cursor to the furthest boundary scanned. Even if there
            # were no transactions for this asset in the window, we mark the
            # cursor up to current_round so lag reflects real-time progress.
            new_round = max(max_seen_round, current_round)
            if new_round > (cursor.last_scanned_round or 0):
                cursor.last_scanned_round = new_round
                cursor.save(update_fields=['last_scanned_round', 'updated_at'])

        logger.info(f"Indexer scan complete: processed={processed}, skipped={skipped}")
        return {'processed': processed, 'skipped': skipped}
    except Exception as e:
        logger.error(f"scan_inbound_deposits failed: {e}")
        raise
    finally:
        try:
            _cache.delete(_lock_key)
        except Exception:
            pass


# ================================
# Outbound confirmation (algod poll)
# ================================

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=5, retry_kwargs={"max_retries": 6})
@ensure_db_connection_closed
def confirm_payment_transaction(self, payment_id: str, txid: str):
    """
    Poll algod for a submitted payment transaction until confirmed, then
    update DB state and send notifications. On transient errors, Celery
    auto‑retries with exponential backoff.

    Args:
        payment_id: PaymentTransaction.payment_transaction_id
        txid: Algorand transaction id for the submitted group
    """
    try:
        client = AlgorandClient()
        algod_client = client.algod

        delays = [0.5, 1, 2, 4, 6, 8, 10]
        confirmed_round = 0
        pool_error = None

        for d in delays:
            try:
                info = algod_client.pending_transaction_info(txid)
            except Exception as e:
                logger.warning(f"pending_transaction_info error for {txid}: {e}")
                info = {}

            confirmed_round = int(info.get('confirmed-round') or 0)
            pool_error = info.get('pool-error') or info.get('pool_error')

            if confirmed_round > 0:
                break
            if pool_error:
                break

            try:
                import time
                time.sleep(d)
            except Exception:
                pass

        try:
            payment_tx: PaymentTransaction = PaymentTransaction.objects.select_related(
                'invoice', 'payer_user', 'payer_business', 'merchant_business', 'merchant_account'
            ).get(payment_transaction_id=payment_id)
        except PaymentTransaction.DoesNotExist:
            logger.error(f"PaymentTransaction {payment_id} not found for confirmation")
            return {'status': 'missing'}

        if pool_error:
            payment_tx.status = 'FAILED'
            payment_tx.error_message = str(pool_error)
            payment_tx.save(update_fields=['status', 'error_message', 'updated_at'])
            logger.error(f"Payment {payment_id} failed in pool: {pool_error}")
            return {'status': 'failed', 'pool_error': pool_error}

        if confirmed_round > 0:
            payment_tx.status = 'CONFIRMED'
            payment_tx.save(update_fields=['status', 'updated_at'])

            if payment_tx.invoice and payment_tx.invoice.status != 'PAID':
                from django.utils import timezone as dj_tz
                invoice = payment_tx.invoice
                invoice.status = 'PAID'
                invoice.paid_at = dj_tz.now()
                invoice.paid_by_user = payment_tx.payer_user
                invoice.paid_by_business = payment_tx.payer_business
                invoice.save(update_fields=['status', 'paid_at', 'paid_by_user', 'paid_by_business', 'updated_at'])

            amount_str = str(payment_tx.amount)
            token = payment_tx.token_type
            display_token = 'cUSD' if str(token).upper() == 'CUSD' else str(token)
            # Derive friendly, privacy-safe display names
            def full_name(u):
                try:
                    name = f"{(u.first_name or '').strip()} {(u.last_name or '').strip()}".strip()
                    return name or None
                except Exception:
                    return None
            payer_name = (
                payment_tx.payer_display_name
                or (full_name(payment_tx.payer_user) if payment_tx.payer_user else None)
                or (payment_tx.payer_phone if getattr(payment_tx, 'payer_phone', '') else None)
                or (f"{(payment_tx.payer_address or '')[:6]}...{(payment_tx.payer_address or '')[-4:]}" if getattr(payment_tx, 'payer_address', '') else 'Usuario')
            )
            merchant_name = (
                payment_tx.merchant_display_name
                or (payment_tx.merchant_business.name if payment_tx.merchant_business else None)
                or (f"{(payment_tx.merchant_address or '')[:6]}...{(payment_tx.merchant_address or '')[-4:]}" if getattr(payment_tx, 'merchant_address', '') else 'Comercio')
            )

            try:
                merchant_acct = payment_tx.merchant_account
                notif_utils.create_notification(
                    user=payment_tx.merchant_account_user,
                    account=merchant_acct,
                    business=payment_tx.merchant_business,
                    notification_type=NotificationTypeChoices.PAYMENT_RECEIVED,
                    title="Pago recibido",
                    message=f"Recibiste {amount_str} {display_token} de {payer_name}",
                    data={
                        'transaction_id': payment_tx.payment_transaction_id,
                        'transaction_hash': payment_tx.transaction_hash,
                        'amount': amount_str,
                        'token_type': token,
                    },
                    related_object_type='PaymentTransaction',
                    related_object_id=str(payment_tx.id),
                    action_url=f"confio://transaction/{payment_tx.payment_transaction_id}",
                )
            except Exception as e:
                logger.warning(f"Could not create merchant notification for {payment_id}: {e}")

            try:
                notif_utils.create_notification(
                    user=payment_tx.payer_user,
                    account=payment_tx.payer_account,
                    business=payment_tx.payer_business,
                    notification_type=NotificationTypeChoices.PAYMENT_SENT,
                    title="Pago enviado",
                    message=f"Pagaste {amount_str} {display_token} a {merchant_name}",
                    data={
                        'transaction_id': payment_tx.payment_transaction_id,
                        'transaction_hash': payment_tx.transaction_hash,
                        'amount': amount_str,
                        'token_type': token,
                    },
                    related_object_type='PaymentTransaction',
                    related_object_id=str(payment_tx.id),
                    action_url=f"confio://transaction/{payment_tx.payment_transaction_id}",
                )
            except Exception as e:
                logger.warning(f"Could not create payer notification for {payment_id}: {e}")

            # Do not send an extra 'invoice paid' notification; 'Pago recibido' is sufficient.

            logger.info(f"Payment {payment_id} confirmed in round {confirmed_round}")
            return {'status': 'confirmed', 'round': confirmed_round}

        # Not confirmed yet: keep polling via Celery retry
        raise Exception(f"Tx {txid} not yet confirmed; scheduling retry")
    except Exception as e:
        # Allow Celery autoretry to handle transient issues
        logger.warning(f"confirm_payment_transaction error: {e}")
        raise


@shared_task(name='blockchain.scan_outbound_confirmations')
@ensure_db_connection_closed
def scan_outbound_confirmations(max_batch: int = 50):
    """
    Worker-side autonomous scanner for any SUBMITTED outbound txns.
    - Confirms PaymentTransaction and SendTransaction by polling algod.
    - Avoids reliance on direct enqueue from API path.
    """
    # Prevent overlapping runs
    from django.core.cache import cache as _cache
    _lock_key = 'locks:scan_outbound_confirmations'
    if not _cache.add(_lock_key, '1', timeout=30):
        logger.info('[OutboundScan] Skipping run: another scan_outbound_confirmations is active')
        return {'skipped': True, 'reason': 'locked'}

    try:
        client = AlgorandClient()
        algod_client = client.algod

        processed = 0

        # Helper: confirm a txid
        def check_tx(txid: str) -> tuple[int, str]:
            try:
                info = algod_client.pending_transaction_info(txid)
            except Exception as e:
                logger.warning(f"pending_transaction_info error for {txid}: {e}")
                return 0, ''
            cr = int(info.get('confirmed-round') or 0)
            pe = info.get('pool-error') or info.get('pool_error') or ''
            return cr, pe

        # Payments
        pay_qs = PaymentTransaction.objects.filter(status='SUBMITTED').exclude(transaction_hash__isnull=True).exclude(transaction_hash='')[:max_batch]
        for p in pay_qs:
            cr, pe = check_tx(p.transaction_hash)
            if pe:
                p.status = 'FAILED'
                p.error_message = str(pe)
                p.save(update_fields=['status', 'error_message', 'updated_at'])
                processed += 1
                continue
            if cr > 0:
                # Reuse logic from confirm_payment_transaction
                try:
                    confirm_payment_transaction.run(p.payment_transaction_id, p.transaction_hash)
                except Exception:
                    # Fallback to inline minimal update
                    p.status = 'CONFIRMED'
                    p.save(update_fields=['status', 'updated_at'])
                processed += 1

        # Sends
        send_qs = SendTransaction.objects.filter(status='SUBMITTED').exclude(transaction_hash__isnull=True).exclude(transaction_hash='')[:max_batch]
        for s in send_qs:
            cr, pe = check_tx(s.transaction_hash or '')
            if pe:
                s.status = 'FAILED'
                s.error_message = str(pe)
                s.save(update_fields=['status', 'error_message', 'updated_at'])
                processed += 1
                continue
            if cr > 0:
                s.status = 'CONFIRMED'
                s.save(update_fields=['status', 'updated_at'])
                # Notifications (best-effort)
                try:
                    amount_str = str(s.amount)
                    token = s.token_type
                    display_token = 'cUSD' if str(token).upper() == 'CUSD' else str(token)
                    def full_name_user(u):
                        try:
                            nm = f"{(u.first_name or '').strip()} {(u.last_name or '').strip()}".strip()
                            return nm or None
                        except Exception:
                            return None
                    sender_name = (
                        s.sender_display_name
                        or (full_name_user(s.sender_user) if s.sender_user_id else None)
                        or (s.sender_phone if getattr(s, 'sender_phone', '') else None)
                        or (s.sender_address[:6] + '...' + s.sender_address[-4:] if s.sender_address else 'Usuario')
                    )
                    recipient_name = (
                        s.recipient_display_name
                        or (full_name_user(s.recipient_user) if s.recipient_user_id else None)
                        or (s.recipient_phone if getattr(s, 'recipient_phone', '') else None)
                        or (s.recipient_address[:6] + '...' + s.recipient_address[-4:] if s.recipient_address else 'Contacto')
                    )
                    # Recipient notification
                    if s.recipient_user_id:
                        notif_utils.create_notification(
                            user=s.recipient_user,
                            account=None,
                            business=s.recipient_business,
                            notification_type=NotifType.SEND_RECEIVED,
                            title="Dinero recibido",
                            message=f"Recibiste {amount_str} {display_token} de {sender_name}",
                            data={
                                'transaction_hash': s.transaction_hash,
                                'amount': amount_str,
                                'token_type': token,
                            },
                            related_object_type='SendTransaction',
                            related_object_id=str(s.id),
                            action_url=f"confio://send/{s.id}",
                        )
                    # Sender notification
                    if s.sender_user_id:
                        notif_utils.create_notification(
                            user=s.sender_user,
                            account=None,
                            business=s.sender_business,
                            notification_type=NotifType.SEND_SENT,
                            title="Dinero enviado",
                            message=f"Enviaste {amount_str} {display_token} a {recipient_name}",
                            data={
                                'transaction_hash': s.transaction_hash,
                                'amount': amount_str,
                                'token_type': token,
                            },
                            related_object_type='SendTransaction',
                            related_object_id=str(s.id),
                            action_url=f"confio://send/{s.id}",
                        )
                except Exception as ne:
                    logger.warning(f"Notification error for SendTransaction {s.id}: {ne}")
                processed += 1


# P2P open_dispute confirmation task moved to bottom of file

        # P2P Escrow creations (escrowed funds)
        escrows = P2PEscrow.objects.filter(
            is_escrowed=False,
            escrow_transaction_hash__isnull=False,
        ).exclude(escrow_transaction_hash='')[:max_batch]
        for e in escrows:
            cr, pe = check_tx(e.escrow_transaction_hash)
            if pe:
                # No explicit failure field; log and continue
                logger.warning(f"P2P escrow tx pool error for trade {getattr(e.trade, 'id', None)}: {pe}")
                processed += 1
                continue
            if cr > 0:
                try:
                    from django.utils import timezone as dj_tz
                    e.is_escrowed = True
                    if not e.escrowed_at:
                        e.escrowed_at = dj_tz.now()
                    e.save(update_fields=['is_escrowed', 'escrowed_at', 'updated_at'])
                except Exception as ue:
                    logger.warning(f"Failed to mark P2P escrow confirmed for trade {getattr(e.trade, 'id', None)}: {ue}")
                processed += 1

        # Presale purchases
        presale_qs = PresalePurchase.objects.filter(status='processing').exclude(transaction_hash__isnull=True).exclude(transaction_hash='')[:max_batch]
        for p in presale_qs:
            cr, pe = check_tx(p.transaction_hash)
            if pe:
                # Mark failed and continue
                try:
                    p.status = 'failed'
                    p.save(update_fields=['status'])
                except Exception:
                    pass
                processed += 1
                continue
            if cr > 0:
                # Mark confirmed, set completed_at, send notification, mark balances stale
                try:
                    from django.utils import timezone as dj_tz
                    p.status = 'completed'
                    if not p.completed_at:
                        p.completed_at = dj_tz.now()
                    p.save(update_fields=['status', 'completed_at'])

                    # Update user's phase limit tally
                    try:
                        from presale.models import UserPresaleLimit
                        upl, _ = UserPresaleLimit.objects.get_or_create(user=p.user, phase=p.phase)
                        upl.total_purchased = (upl.total_purchased or Decimal('0')) + (p.cusd_amount or Decimal('0'))
                        upl.last_purchase_at = dj_tz.now()
                        upl.save(update_fields=['total_purchased', 'last_purchase_at'])
                    except Exception as le:
                        logger.warning(f"Failed updating presale user limit for {p.user_id}: {le}")

                    # Refresh phase stats (best-effort)
                    try:
                        if hasattr(p.phase, 'stats') and p.phase.stats_id:
                            p.phase.stats.update_stats()
                    except Exception:
                        pass

                    # Notification (user-facing in Spanish; use "Preventa")
                    try:
                        amount_str = str(p.confio_amount)
                        notif_utils.create_notification(
                            user=p.user,
                            account=None,
                            business=None,
                            notification_type=NotifType.PRESALE_PURCHASE_CONFIRMED,
                            title="Preventa completada",
                            message=f"Tu compra de Preventa ({amount_str} CONFIO) fue confirmada",
                            data={
                                'transaction_hash': p.transaction_hash,
                                'confio_amount': str(p.confio_amount),
                                'cusd_amount': str(p.cusd_amount),
                                'phase': getattr(p.phase, 'phase_number', None),
                            },
                            related_object_type='PresalePurchase',
                            related_object_id=str(p.id),
                            action_url=f"confio://presale/{p.id}",
                        )
                    except Exception as ne:
                        logger.warning(f"Notification error for PresalePurchase {p.id}: {ne}")

                    # Record unified transaction for transaction history
                    try:
                        presale_identifier = f"presale_purchase:{p.id}"
                        user_display = p.user.get_full_name() or p.user.username or p.user.email or 'Tú'
                        amount_str = format(p.confio_amount.normalize(), 'f')
                        sender_display = "Confío Preventa"
                        vault_address = getattr(settings, 'ALGORAND_PRESALE_VAULT_ADDRESS', '') or 'ConfioPresaleVault'
                        user_address = p.from_address or ''
                        description = f"Compra de preventa Fase {getattr(p.phase, 'phase_number', '')}".strip()

                        UnifiedTransactionTable.objects.update_or_create(
                            transaction_type='presale',
                            payment_reference_id=presale_identifier,
                            defaults={
                                'amount': amount_str,
                                'token_type': 'CONFIO',
                                'status': 'CONFIRMED',
                                'transaction_hash': p.transaction_hash or '',
                                'error_message': '',
                                'sender_user': None,
                                'sender_business': None,
                                'sender_type': 'external',
                                'sender_display_name': sender_display,
                                'sender_phone': '',
                                'sender_address': vault_address,
                                'counterparty_user': p.user,
                                'counterparty_business': None,
                                'counterparty_type': 'user',
                                'counterparty_display_name': user_display,
                                'counterparty_phone': '',
                                'counterparty_address': user_address,
                                'description': description,
                                'invoice_id': None,
                                'payment_reference_id': presale_identifier,
                                'payment_transaction_id': None,
                                'from_address': vault_address,
                                'to_address': user_address,
                                'is_invitation': False,
                                'invitation_claimed': False,
                                'invitation_reverted': False,
                                'invitation_expires_at': None,
                                'transaction_date': p.completed_at or dj_tz.now(),
                            },
                        )
                    except Exception as ue:
                        logger.warning(f"Failed to record unified presale transaction for {p.id}: {ue}")

                    # Mark balances stale for quick refresh
                    try:
                        mark_transaction_balances_stale.delay(
                            p.transaction_hash,
                            sender_address=p.from_address,
                            recipient_addresses=[]
                        )
                    except Exception:
                        pass
                except Exception as ue:
                    logger.warning(f"Failed to mark PresalePurchase {p.id} confirmed: {ue}")
                processed += 1

        # P2P releases (normal release or refund/dispute)
        releases = P2PEscrow.objects.filter(
            is_released=False,
            release_transaction_hash__isnull=False,
        ).exclude(release_transaction_hash='')[:max_batch]
        for e in releases:
            cr, pe = check_tx(e.release_transaction_hash)
            if pe:
                logger.warning(f"P2P release tx pool error for trade {getattr(e.trade, 'id', None)}: {pe}")
                processed += 1
                continue
            if cr > 0:
                try:
                    from django.utils import timezone as dj_tz
                    tr = e.trade
                    # Mark escrow released
                    e.is_released = True
                    if not e.release_amount:
                        e.release_amount = e.escrow_amount
                    if not e.release_type:
                        e.release_type = 'NORMAL'
                    e.released_at = dj_tz.now()
                    e.save(update_fields=['is_released', 'release_amount', 'release_type', 'released_at', 'updated_at'])

                    # Update trade status and send notifications depending on release_type
                    if tr:
                        from notifications.utils import create_p2p_notification
                        from notifications.models import NotificationType as NotificationTypeChoices
                        buyer_user = tr.buyer_user if tr.buyer_user else (tr.buyer_business.accounts.first().user if tr.buyer_business else None)
                        seller_user = tr.seller_user if tr.seller_user else (tr.seller_business.accounts.first().user if tr.seller_business else None)

                        if e.release_type == 'NORMAL':
                            # Buyer received crypto
                            try:
                                tr.status = 'CRYPTO_RELEASED'
                                tr.completed_at = dj_tz.now()
                                tr.save(update_fields=['status', 'completed_at', 'updated_at'])
                            except Exception:
                                pass
                            try:
                                base = {
                                    'amount': str(tr.crypto_amount),
                                    'token_type': tr.offer.token_type if tr.offer else 'CUSD',
                                    'trade_id': str(tr.id),
                                    'fiat_amount': str(tr.fiat_amount),
                                    'fiat_currency': tr.offer.currency_code if tr.offer else '',
                                    'payment_method': tr.payment_method.name if getattr(tr, 'payment_method', None) else '',
                                }
                                if buyer_user:
                                    create_p2p_notification(
                                        notification_type=NotificationTypeChoices.P2P_CRYPTO_RELEASED,
                                        user=buyer_user,
                                        business=tr.buyer_business,
                                        trade_id=str(tr.id),
                                        amount=str(tr.crypto_amount),
                                        token_type=base['token_type'],
                                        counterparty_name=tr.seller_display_name,
                                        additional_data=base,
                                    )
                                if seller_user:
                                    create_p2p_notification(
                                        notification_type=NotificationTypeChoices.P2P_CRYPTO_RELEASED,
                                        user=seller_user,
                                        business=tr.seller_business,
                                        trade_id=str(tr.id),
                                        amount=str(tr.crypto_amount),
                                        token_type=base['token_type'],
                                        counterparty_name=tr.buyer_display_name,
                                        additional_data=base,
                                    )
                            except Exception as ne:
                                logger.warning(f"P2P NORMAL release notification error for trade {getattr(tr, 'id', None)}: {ne}")

                        elif e.release_type == 'REFUND':
                            # Trade cancelled/refunded to buyer
                            try:
                                tr.status = 'CANCELLED'
                                tr.save(update_fields=['status', 'updated_at'])
                            except Exception:
                                pass
                            try:
                                extra = {
                                    'trade_id': str(tr.id),
                                    'release_type': 'REFUND',
                                    'refund_amount': str(e.release_amount or e.escrow_amount),
                                    'fiat_amount': str(tr.fiat_amount),
                                    'fiat_currency': tr.offer.currency_code if tr.offer else '',
                                }
                                if buyer_user:
                                    create_p2p_notification(
                                        notification_type=NotificationTypeChoices.P2P_TRADE_CANCELLED,
                                        user=buyer_user,
                                        business=tr.buyer_business,
                                        trade_id=str(tr.id),
                                        amount=str(tr.crypto_amount),
                                        token_type=(tr.offer.token_type if tr.offer else 'CUSD'),
                                        counterparty_name=tr.seller_display_name,
                                        additional_data=extra,
                                    )
                                if seller_user:
                                    create_p2p_notification(
                                        notification_type=NotificationTypeChoices.P2P_TRADE_CANCELLED,
                                        user=seller_user,
                                        business=tr.seller_business,
                                        trade_id=str(tr.id),
                                        amount=str(tr.crypto_amount),
                                        token_type=(tr.offer.token_type if tr.offer else 'CUSD'),
                                        counterparty_name=tr.buyer_display_name,
                                        additional_data=extra,
                                    )
                            except Exception as ne:
                                logger.warning(f"P2P REFUND notification error for trade {getattr(tr, 'id', None)}: {ne}")

                        else:
                            # DISPUTE_RELEASE or PARTIAL_REFUND → dispute resolved
                            try:
                                tr.status = 'COMPLETED'
                                tr.completed_at = dj_tz.now()
                                tr.save(update_fields=['status', 'completed_at', 'updated_at'])
                            except Exception:
                                pass
                            try:
                                details = {
                                    'trade_id': str(tr.id),
                                    'release_type': e.release_type,
                                    'refund_amount': str(e.release_amount or ''),
                                    'fiat_amount': str(tr.fiat_amount),
                                    'fiat_currency': tr.offer.currency_code if tr.offer else '',
                                }
                                if buyer_user:
                                    create_p2p_notification(
                                        notification_type=NotificationTypeChoices.P2P_DISPUTE_RESOLVED,
                                        user=buyer_user,
                                        business=tr.buyer_business,
                                        trade_id=str(tr.id),
                                        amount=str(tr.crypto_amount),
                                        token_type=(tr.offer.token_type if tr.offer else 'CUSD'),
                                        counterparty_name=tr.seller_display_name,
                                        additional_data=details,
                                    )
                                if seller_user:
                                    create_p2p_notification(
                                        notification_type=NotificationTypeChoices.P2P_DISPUTE_RESOLVED,
                                        user=seller_user,
                                        business=tr.seller_business,
                                        trade_id=str(tr.id),
                                        amount=str(tr.crypto_amount),
                                        token_type=(tr.offer.token_type if tr.offer else 'CUSD'),
                                        counterparty_name=tr.buyer_display_name,
                                        additional_data=details,
                                    )
                            except Exception as ne:
                                logger.warning(f"P2P DISPUTE notification error for trade {getattr(tr, 'id', None)}: {ne}")
                except Exception as ue:
                    logger.warning(f"Failed to mark P2P release confirmed for trade {getattr(e.trade, 'id', None)}: {ue}")
                processed += 1

        # Conversions (cUSD <> USDC)
        conv_qs = Conversion.objects.filter(status='SUBMITTED').exclude(to_transaction_hash__isnull=True).exclude(to_transaction_hash='')[:max_batch]
        for c in conv_qs:
            cr, pe = check_tx(c.to_transaction_hash or '')
            if pe:
                c.status = 'FAILED'
                c.error_message = str(pe)
                c.save(update_fields=['status', 'error_message', 'updated_at'])
                processed += 1
                continue
            if cr > 0:
                from django.utils import timezone as dj_tz
                c.status = 'COMPLETED'
                c.completed_at = dj_tz.now()
                c.save(update_fields=['status', 'completed_at', 'updated_at'])
                # Notification: conversion completed (ensure a user for business accounts)
                try:
                    from notifications.utils import create_transaction_notification
                    # Determine tokens and direction
                    if c.conversion_type == 'usdc_to_cusd':
                        from_token, to_token = 'USDC', 'cUSD'
                        amount_from = str(c.from_amount)
                        amount_to = str(c.to_amount)
                    else:
                        from_token, to_token = 'cUSD', 'USDC'
                        amount_from = str(c.from_amount)
                        amount_to = str(c.to_amount)

                    # Ensure we have a concrete user to attach the notification to
                    target_user = None
                    try:
                        if getattr(c, 'actor_user_id', None):
                            target_user = c.actor_user
                        elif getattr(c, 'actor_business_id', None):
                            acct = c.actor_business.accounts.first()
                            target_user = getattr(acct, 'user', None)
                    except Exception:
                        pass

                    if not target_user:
                        raise Exception('no_target_user')

                    notif = create_transaction_notification(
                        transaction_type='conversion',
                        sender_user=target_user,
                        business=c.actor_business,
                        amount=amount_to,
                        token_type=to_token,
                        transaction_id=str(c.id),
                        transaction_model='Conversion',
                        additional_data={
                            'from_amount': amount_from,
                            'from_token': from_token,
                            'to_amount': amount_to,
                            'to_token': to_token,
                            'transaction_hash': c.to_transaction_hash,
                            'conversion_type': c.conversion_type,
                        },
                    )
                    if not notif:
                        # Fallback to direct notification (should rarely happen)
                        title = "Conversión completada"
                        msg = f"Convertiste {amount_from} {from_token} a {amount_to} {to_token}"
                        notif_utils.create_notification(
                            user=target_user,
                            business=c.actor_business,
                            notification_type=NotificationTypeChoices.CONVERSION_COMPLETED,
                            title=title,
                            message=msg,
                            data={
                                'transaction_id': str(c.id),
                                'from_amount': amount_from,
                                'from_token': from_token,
                                'to_amount': amount_to,
                                'to_token': to_token,
                                'transaction_hash': c.to_transaction_hash,
                                'conversion_type': c.conversion_type,
                            },
                            related_object_type='Conversion',
                            related_object_id=str(c.id),
                            action_url=f"confio://transaction/{c.id}",
                        )
                except Exception as ne:
                    logger.warning(f"Conversion notification error for Conversion {c.id}: {ne}")
                processed += 1

        # USDC Withdrawals (tracked via unified table transaction_hash)
        try:
            from usdc_transactions.models_unified import UnifiedUSDCTransactionTable as UUT
            from usdc_transactions.models import USDCWithdrawal
            # Check both SUBMITTED and PROCESSING to be resilient to signal updates
            w_qs = UUT.objects.filter(
                transaction_type='withdrawal',
                status__in=['SUBMITTED', 'PROCESSING']
            ).exclude(transaction_hash__isnull=True).exclude(transaction_hash='')[:max_batch]
            for u in w_qs:
                txh = u.transaction_hash or ''
                cr, pe = check_tx(txh)
                if pe:
                    # Mark source withdrawal failed
                    try:
                        w = u.usdc_withdrawal
                        if w:
                            w.status = 'FAILED'
                            w.error_message = str(pe)
                            w.save(update_fields=['status', 'error_message', 'updated_at'])
                    except Exception:
                        pass
                    # Update unified as FAILED
                    try:
                        u.status = 'FAILED'
                        u.error_message = str(pe)
                        u.save(update_fields=['status', 'error_message', 'updated_at'])
                    except Exception:
                        pass
                    # Notify user
                    try:
                        # Determine target user for notification (business fallback)
                        target_user = None
                        try:
                            w = u.usdc_withdrawal
                            if w and w.actor_user_id:
                                target_user = w.actor_user
                            elif w and w.actor_business_id:
                                acct = w.actor_business.accounts.first()
                                target_user = getattr(acct, 'user', None)
                        except Exception:
                            pass
                        if not target_user:
                            raise Exception('no_target_user')
                        notif_utils.create_notification(
                            user=target_user,
                            business=u.actor_business,
                            notification_type=NotificationTypeChoices.USDC_WITHDRAWAL_FAILED,
                            title="Retiro USDC fallido",
                            message=f"Tu retiro de {u.amount} USDC falló",
                            data={
                                'transaction_id': str(u.transaction_id),
                                'transaction_type': 'withdrawal',
                                'type': 'withdrawal',
                                'amount': str(u.amount),
                                'currency': 'USDC',
                                'destination_address': u.destination_address,
                                'status': 'failed',
                                'transaction_hash': txh,
                            },
                            related_object_type='USDCWithdrawal',
                            related_object_id=str(getattr(u.usdc_withdrawal, 'id', '')),
                            action_url=f"confio://transaction/{u.transaction_id}"
                        )
                    except Exception as ne:
                        logger.warning(f"Withdrawal failure notification error for unified {u.id}: {ne}")
                    processed += 1
                    continue
                if cr > 0:
                    # Confirmed: mark models and notify
                    from django.utils import timezone as dj_tz
                    try:
                        w = u.usdc_withdrawal
                        if w:
                            w.status = 'COMPLETED'
                            if not w.completed_at:
                                w.completed_at = dj_tz.now()
                            w.save(update_fields=['status', 'completed_at', 'updated_at'])
                    except Exception:
                        pass
                    try:
                        u.status = 'COMPLETED'
                        if not u.completed_at:
                            u.completed_at = dj_tz.now()
                        u.save(update_fields=['status', 'completed_at', 'updated_at'])
                    except Exception:
                        pass
                    # Notification: withdrawal completed (mirror conversions pattern)
                    try:
                        # Determine target user for notification (business fallback)
                        target_user = None
                        try:
                            w = u.usdc_withdrawal
                            if w and w.actor_user_id:
                                target_user = w.actor_user
                            elif w and w.actor_business_id:
                                acct = w.actor_business.accounts.first()
                                target_user = getattr(acct, 'user', None)
                        except Exception:
                            pass
                        if not target_user:
                            raise Exception('no_target_user')
                        from notifications.utils import create_transaction_notification
                        logger.info(f"[OutboundScan] Creating withdrawal completed notification for user={getattr(target_user, 'id', None)} amount={u.amount}")
                        notif = create_transaction_notification(
                            transaction_type='withdrawal',
                            sender_user=target_user,
                            business=u.actor_business,
                            amount=str(u.amount),
                            token_type='USDC',
                            transaction_id=str(u.transaction_id),
                            transaction_model='USDCWithdrawal',
                            additional_data={
                                'transaction_hash': txh,
                                'destination_address': u.destination_address,
                                'status': 'COMPLETED',
                            },
                        )
                        if not notif:
                            # Fallback to direct notification
                            logger.info("[OutboundScan] Fallback notification path for withdrawal completed")
                            notif_utils.create_notification(
                                user=target_user,
                                business=u.actor_business,
                                notification_type=NotificationTypeChoices.USDC_WITHDRAWAL_COMPLETED,
                                title="Retiro USDC completado",
                                message=f"Tu retiro de {u.amount} USDC se ha completado",
                                data={
                                    'transaction_id': str(u.transaction_id),
                                    'transaction_type': 'withdrawal',
                                    'type': 'withdrawal',
                                    'amount': str(u.amount),
                                    'currency': 'USDC',
                                    'destination_address': u.destination_address,
                                    'status': 'completed',
                                    'transaction_hash': txh,
                                },
                                related_object_type='USDCWithdrawal',
                                related_object_id=str(getattr(u.usdc_withdrawal, 'id', '')),
                                action_url=f"confio://transaction/{u.transaction_id}"
                            )
                    except Exception as ne:
                        logger.warning(f"Withdrawal completion notification error for unified {u.id}: {ne}")
                    processed += 1
        except Exception as we:
            logger.warning(f"[OutboundScan] Withdrawal scan error: {we}")

        logger.info(f"[OutboundScan] processed={processed} items")
        return {'processed': processed}
    except Exception as e:
        logger.error(f"scan_outbound_confirmations failed: {e}")
        raise
    finally:
        try:
            _cache.delete(_lock_key)
        except Exception:
            pass


# ================================
# P2P open_dispute confirmation
# ================================

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=5, retry_kwargs={"max_retries": 6})
@ensure_db_connection_closed
def confirm_p2p_open_dispute(self, *, trade_id: str, txid: str, opener_user_id: str = None, opener_business_id: str = None, reason: str = ""):
    """
    Waits for on-chain confirmation of an open_dispute group and updates DB.

    Args:
        trade_id: P2PTrade.id
        txid: user-signed appcall txid for the group
        opener_user_id: optional initiating user id
        opener_business_id: optional initiating business id
        reason: optional dispute reason
    """
    try:
        client = AlgorandClient()
        algod_client = client.algod

        delays = [0.5, 1, 2, 4, 6, 8, 10]
        confirmed_round = 0
        pool_error = None

        for d in delays:
            try:
                info = algod_client.pending_transaction_info(txid)
            except Exception as e:
                logger.warning(f"pending_transaction_info error for {txid}: {e}")
                info = {}

            confirmed_round = int(info.get('confirmed-round') or 0)
            pool_error = info.get('pool-error') or info.get('pool_error')

            if confirmed_round > 0 or pool_error:
                break

            try:
                import time
                time.sleep(d)
            except Exception:
                pass

        # Load trade
        trade = P2PTrade.objects.filter(id=trade_id).select_related('buyer_user', 'seller_user', 'buyer_business', 'seller_business').first()
        if not trade:
            logger.error(f"confirm_p2p_open_dispute: trade {trade_id} not found")
            return {'status': 'missing'}

        if pool_error:
            logger.error(f"confirm_p2p_open_dispute: pool error for {txid}: {pool_error}")
            return {'status': 'failed', 'pool_error': pool_error}

        if confirmed_round > 0:
            # Update status
            if trade.status not in ('DISPUTED', 'CANCELLED', 'COMPLETED'):
                from django.utils import timezone as dj_tz
                trade.status = 'DISPUTED'
                trade.updated_at = dj_tz.now()
                try:
                    trade.save(update_fields=['status', 'updated_at'])
                except Exception:
                    pass

            # Ensure a dispute record exists
            try:
                from p2p_exchange.models import P2PDispute
                exists = False
                try:
                    _ = trade.dispute_details
                    exists = True
                except Exception:
                    exists = False
                if not exists:
                    kwargs = {
                        'trade': trade,
                        'reason': (reason or 'Dispute opened on-chain').strip(),
                        'priority': 2,
                        'status': 'UNDER_REVIEW',
                    }
                    try:
                        if opener_business_id and (trade.buyer_business_id == opener_business_id or trade.seller_business_id == opener_business_id):
                            from users.models import Business
                            kwargs['initiator_business'] = Business.objects.filter(id=opener_business_id).first()
                        elif opener_user_id:
                            from users.models import User as _User
                            kwargs['initiator_user'] = _User.objects.filter(id=opener_user_id).first()
                    except Exception:
                        pass
                    try:
                        P2PDispute.objects.create(**kwargs)
                    except Exception as ce:
                        logger.warning(f"confirm_p2p_open_dispute: failed to create dispute for trade {trade_id}: {ce}")
            except Exception as e:
                logger.warning(f"confirm_p2p_open_dispute: dispute ensure error: {e}")

            # Record system message
            try:
                from p2p_exchange.models import P2PMessage
                P2PMessage.objects.create(
                    trade=trade,
                    message='🚩 Disputa abierta en cadena',
                    sender_type='system',
                    message_type='system',
                )
            except Exception as e:
                logger.warning(f"confirm_p2p_open_dispute: failed to create system message: {e}")

            logger.info(f"confirm_p2p_open_dispute: trade {trade_id} confirmed in round {confirmed_round}")
            return {'status': 'confirmed', 'round': confirmed_round}

        # Not confirmed yet: schedule retry
        raise Exception(f"Tx {txid} not yet confirmed; scheduling retry")
    except Exception as e:
        logger.warning(f"confirm_p2p_open_dispute error: {e}")
        raise


@shared_task(name='blockchain.monitor_db_connections')
@ensure_db_connection_closed
def monitor_db_connections():
    """Monitor PostgreSQL database connections and log warnings if usage is high"""
    from django.db import connection
    
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    count(*) as total_connections,
                    count(*) FILTER (WHERE state = 'active') as active_connections,
                    count(*) FILTER (WHERE state = 'idle') as idle_connections,
                    count(*) FILTER (WHERE state = 'idle in transaction') as idle_in_transaction,
                    (SELECT setting::int FROM pg_settings WHERE name = 'max_connections') as max_connections
                FROM pg_stat_activity 
                WHERE pid <> pg_backend_pid();
            """)
            
            result = cursor.fetchone()
            total, active, idle, idle_in_txn, max_conns = result
            usage_pct = (total / max_conns) * 100
            
            message = (
                f"DB Connections: {total}/{max_conns} ({usage_pct:.1f}%) | "
                f"Active: {active}, Idle: {idle}, Idle in txn: {idle_in_txn}"
            )
            
            if usage_pct > 80:
                logger.error(f"HIGH CONNECTION USAGE: {message}")
            elif usage_pct > 60:
                logger.warning(f"ELEVATED CONNECTION USAGE: {message}")
            else:
                logger.info(f"Connection usage normal: {message}")
                
            return {
                'total_connections': total,
                'max_connections': max_conns,
                'usage_percentage': usage_pct,
                'active': active,
                'idle': idle,
                'idle_in_transaction': idle_in_txn
            }
    except Exception as e:
        logger.error(f"monitor_db_connections error: {e}")
        raise
