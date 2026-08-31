from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import logging
import re
import requests
from django.conf import settings
from decimal import Decimal
from .models import GuardarianTransaction, USDCDeposit

logger = logging.getLogger(__name__)


def _provider_evm_tx_hash(payload):
    if not isinstance(payload, dict):
        return ''
    for key in ('txHash', 'tx_hash', 'transactionHash', 'transaction_hash'):
        value = payload.get(key)
        if isinstance(value, str) and re.fullmatch(r'0x[0-9a-fA-F]{64}', value):
            return value.lower()
    for value in payload.values():
        if isinstance(value, dict):
            found = _provider_evm_tx_hash(value)
            if found:
                return found
        if isinstance(value, list):
            for item in value:
                found = _provider_evm_tx_hash(item)
                if found:
                    return found
    return ''


def _apply_provider_details(tx, data):
    """Persist attribution inputs even when the provider status is unchanged."""
    update_fields = []
    if data.get('to_amount'):
        actual = Decimal(str(data['to_amount']))
        if tx.to_amount_actual != actual:
            tx.to_amount_actual = actual
            update_fields.append('to_amount_actual')
    provider_hash = _provider_evm_tx_hash(data)
    if provider_hash:
        metadata = dict(tx.confio_fee_metadata or {})
        if metadata.get('provider_transfer_tx_hash') != provider_hash:
            metadata['provider_transfer_tx_hash'] = provider_hash
            tx.confio_fee_metadata = metadata
            update_fields.append('confio_fee_metadata')
    return update_fields

@shared_task
def poll_guardarian_transactions():
    """
    Poll Guardarian for status updates on pending transactions.
    Strategy: Check transactions created in the last 7 days that are not in a final state.
    """
    # Active states customization
    # 1. Draft/Waiting: User hasn't paid yet or just started. Abandon after 24 hours.
    waiting_states = ['new', 'waiting', 'waiting_for_deposit', 'waiting_for_customer']
    waiting_threshold = timezone.now() - timedelta(hours=24)
    
    # 2. Processing: User paid, money moving. Keep polling for 7 days to ensure completion.
    processing_states = ['pending', 'confirmed', 'exchanging', 'sending']
    processing_threshold = timezone.now() - timedelta(days=7)
    
    from django.db.models import Q
    
    pending_txs = GuardarianTransaction.objects.filter(
        Q(status__in=waiting_states, created_at__gte=waiting_threshold) |
        Q(status__in=processing_states, created_at__gte=processing_threshold)
    )
    
    if not pending_txs.exists():
        return "No pending Guardarian transactions"

    api_key = getattr(settings, 'GUARDARIAN_API_KEY', None)
    base_url = getattr(settings, 'GUARDARIAN_API_URL', 'https://api-payments.guardarian.com/v1')
    
    if not api_key:
        logger.error("GUARDARIAN_API_KEY not configured")
        return "Missing API Key"

    import time # Import locally to avoid top-level impact
    
    updated_count = 0
    
    for tx in pending_txs:
        try:
            # Call Guardarian API
            url = f'{base_url.rstrip("/")}/transaction/{tx.guardarian_id}'
            resp = requests.get(url, headers={'x-api-key': api_key}, timeout=10)
            
            if resp.status_code == 429:
                logger.warning("Guardarian rate limit hit during poll. Stopping cycle.")
                break

            if resp.status_code == 404:
                logger.warning(f"Guardarian Tx {tx.guardarian_id} not found (404). Marking as failed.")
                tx.status = 'failed'
                tx.status_details = 'Transaction not found on Guardarian (expired/invalid)'
                tx.save()
                updated_count += 1
                continue

            if not resp.ok:
                logger.warning(f"Guardarian poll failed for {tx.guardarian_id}: {resp.status_code}")
                continue
                
            data = resp.json()
            new_status = data.get('status')
            update_fields = _apply_provider_details(tx, data)
            
            if new_status and new_status != tx.status:
                old_status = tx.status
                tx.status = new_status
                update_fields.append('status')
                
                # Capture any error info or details
                if data.get('status_details'):
                    tx.status_details = data.get('status_details')
                    update_fields.append('status_details')
                
                tx.save(update_fields=list(dict.fromkeys(update_fields)))
                logger.info(f"Updated Guardarian Tx {tx.guardarian_id}: {old_status} -> {new_status}")
                updated_count += 1
                
                # Link deposit if finished
                if new_status == 'finished':
                    if tx.transaction_type == 'buy' and not tx.onchain_deposit:
                        tx.attempt_match_deposit()
                    elif tx.transaction_type == 'sell' and not tx.onchain_withdrawal:
                        tx.attempt_match_withdrawal()

            elif update_fields:
                tx.save(update_fields=list(dict.fromkeys(update_fields)))

            # Sleep to respect rate limits (basic throttle)
            time.sleep(1.0)

        except Exception as e:
            logger.error(f"Error polling Guardarian Tx {tx.guardarian_id}: {e}")

    return f"Polled {pending_txs.count()} txs, Updated {updated_count}"


@shared_task
def check_single_guardarian_transaction(guardarian_id):
    """
    On-demand check for a single transaction (triggered by frontend user action).
    """
    try:
        tx = GuardarianTransaction.objects.get(guardarian_id=guardarian_id)
    except GuardarianTransaction.DoesNotExist:
        logger.warning(f"Requested check for unknown Guardarian ID: {guardarian_id}")
        return "Transaction not found"

    api_key = getattr(settings, 'GUARDARIAN_API_KEY', None)
    base_url = getattr(settings, 'GUARDARIAN_API_URL', 'https://api-payments.guardarian.com/v1')
    
    if not api_key:
        return "Missing API Key"
        
    try:
        url = f'{base_url.rstrip("/")}/transaction/{tx.guardarian_id}'
        resp = requests.get(url, headers={'x-api-key': api_key}, timeout=10)
        
        if resp.ok:
            data = resp.json()
            new_status = data.get('status')
            update_fields = _apply_provider_details(tx, data)
            if new_status and new_status != tx.status:
                tx.status = new_status
                update_fields.append('status')
                if data.get('status_details'):
                    tx.status_details = data.get('status_details')
                    update_fields.append('status_details')
                tx.save(update_fields=list(dict.fromkeys(update_fields)))
                if new_status == 'finished':
                    if tx.transaction_type == 'buy' and not tx.onchain_deposit:
                        tx.attempt_match_deposit()
                    elif tx.transaction_type == 'sell' and not tx.onchain_withdrawal:
                        tx.attempt_match_withdrawal()
                return f"Updated to {new_status}"
            if update_fields:
                tx.save(update_fields=list(dict.fromkeys(update_fields)))
            if new_status == 'finished':
                if tx.transaction_type == 'buy' and not tx.onchain_deposit:
                    tx.attempt_match_deposit()
                    return "Finished and attempted deposit match"
                if tx.transaction_type == 'sell' and not tx.onchain_withdrawal:
                    tx.attempt_match_withdrawal()
                    return "Finished and attempted withdrawal match"
            return "No change"
        else:
            return f"API Error {resp.status_code}"
            
    except Exception as e:
        logger.error(f"Error checking single Guardarian Tx {guardarian_id}: {e}")
        return f"Error: {e}"
