from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import logging

from users.models import Account
from .models import Balance
from django.conf import settings
from .algorand_client import AlgorandClient
from .models import ProcessedIndexerTransaction, IndexerAssetCursor
from usdc_transactions.models import USDCDeposit
from notifications.utils import create_notification
from notifications.models import NotificationType as NotificationTypeChoices
from send.models import SendTransaction
from payments.models import PaymentTransaction
from send.models import SendTransaction
from notifications.models import NotificationType as NotifType

logger = logging.getLogger(__name__)


"""
Legacy Sui transaction handlers (process_transaction, handle_cusd_transaction, etc.)
have been removed. Algorand deposits are handled by scan_inbound_deposits below.
"""


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


# ================================
# Outbound confirmation (algod poll)
# ================================

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=5, retry_kwargs={"max_retries": 6})
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

            try:
                merchant_acct = payment_tx.merchant_account
                create_notification(
                    user=payment_tx.merchant_account_user,
                    account=merchant_acct,
                    business=payment_tx.merchant_business,
                    notification_type=NotificationTypeChoices.PAYMENT_RECEIVED,
                    title="Pago recibido",
                    message=f"Recibiste {amount_str} {token}",
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
                create_notification(
                    user=payment_tx.payer_user,
                    account=payment_tx.payer_account,
                    business=payment_tx.payer_business,
                    notification_type=NotificationTypeChoices.PAYMENT_SENT,
                    title="Pago enviado",
                    message=f"Tu pago de {amount_str} {token} fue confirmado",
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
def scan_outbound_confirmations(max_batch: int = 50):
    """
    Worker-side autonomous scanner for any SUBMITTED outbound txns.
    - Confirms PaymentTransaction and SendTransaction by polling algod.
    - Avoids reliance on direct enqueue from API path.
    """
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
                    # Recipient notification
                    if s.recipient_user_id:
                        create_notification(
                            user=s.recipient_user,
                            account=None,
                            business=s.recipient_business,
                            notification_type=NotifType.SEND_RECEIVED,
                            title="Dinero recibido",
                            message=f"Recibiste {amount_str} {token}",
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
                        create_notification(
                            user=s.sender_user,
                            account=None,
                            business=s.sender_business,
                            notification_type=NotifType.SEND_SENT,
                            title="Dinero enviado",
                            message=f"Tu envío de {amount_str} {token} fue confirmado",
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

        logger.info(f"[OutboundScan] processed={processed} items")
        return {'processed': processed}
    except Exception as e:
        logger.error(f"scan_outbound_confirmations failed: {e}")
        raise
