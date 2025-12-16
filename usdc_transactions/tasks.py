from celery import shared_task
from django.utils import timezone
from datetime import timedelta
import logging
import requests
from django.conf import settings
from decimal import Decimal
from .models import GuardarianTransaction, USDCDeposit

logger = logging.getLogger(__name__)

@shared_task(name='usdc_transactions.poll_guardarian_transactions')
def poll_guardarian_transactions():
    """
    Poll Guardarian for status updates on pending transactions.
    Strategy: Check transactions created in the last 24 hours that are not in a final state.
    """
    # Active states that need polling
    active_states = ['new', 'waiting', 'pending', 'confirmed', 'exchanging', 'sending']
    
    # Time window: last 24 hours (generous window)
    time_threshold = timezone.now() - timedelta(hours=24)
    
    pending_txs = GuardarianTransaction.objects.filter(
        status__in=active_states,
        created_at__gte=time_threshold
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

            if not resp.ok:
                logger.warning(f"Guardarian poll failed for {tx.guardarian_id}: {resp.status_code}")
                continue
                
            data = resp.json()
            new_status = data.get('status')
            
            if new_status and new_status != tx.status:
                old_status = tx.status
                tx.status = new_status
                
                # Update amounts if available
                if data.get('to_amount'):
                    tx.to_amount_actual = Decimal(str(data.get('to_amount')))
                
                # Capture any error info or details
                if data.get('status_details'):
                    tx.status_details = data.get('status_details')
                
                tx.save()
                logger.info(f"Updated Guardarian Tx {tx.guardarian_id}: {old_status} -> {new_status}")
                updated_count += 1
                
                # Link deposit if finished
                if new_status == 'finished' and not tx.onchain_deposit:
                    tx.attempt_match_deposit()

            # Sleep to respect rate limits (basic throttle)
            time.sleep(1.0)

        except Exception as e:
            logger.error(f"Error polling Guardarian Tx {tx.guardarian_id}: {e}")

    return f"Polled {pending_txs.count()} txs, Updated {updated_count}"


@shared_task(name='usdc_transactions.check_single_guardarian_transaction')
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
            if new_status and new_status != tx.status:
                tx.status = new_status
                if data.get('to_amount'):
                    tx.to_amount_actual = Decimal(str(data.get('to_amount')))
                tx.save()
                return f"Updated to {new_status}"
            return "No change"
        else:
            return f"API Error {resp.status_code}"
            
    except Exception as e:
        logger.error(f"Error checking single Guardarian Tx {guardarian_id}: {e}")
        return f"Error: {e}"
