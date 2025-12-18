import base64
import time
from datetime import datetime, timedelta
from blockchain.algorand_client import get_indexer_client
from payments.models import Invoice, PaymentTransaction
from django.conf import settings

def find_ghosts():
    # 1. Get Pending Invoices that are suspiciously old or known broken
    print("Searching for broken Pending Invoices...")
    # Specifically looking for KJRXWY9J but generally any pending invoice > 1 hour old could be candidate
    ids = ['KJRXWY9J', 'X88YHR4Q'] # Add others if known
    
    invoices = Invoice.objects.filter(invoice_id__in=ids)
    
    if not invoices.exists():
        print("No target invoices found in DB.")
        return

    indexer = get_indexer_client()
    
    # App ID for Payment Contract (CUSD_APP_ID usually handles payments?)
    # Or is it a separate Payment App?
    # settings.ALGORAND_PAYMENT_APP_ID might exist?
    # Or CUSD_APP_ID?
    # Let's try to find potential App IDs from settings
    app_id = getattr(settings, 'ALGORAND_PAYMENT_APP_ID', None)
    if not app_id:
        print("ALGORAND_PAYMENT_APP_ID not set. Trying CUSD_APP_ID...")
        app_id = getattr(settings, 'ALGORAND_CUSD_APP_ID', None)
    
    print(f"Using App ID: {app_id}")
    
    for inv in invoices:
        print(f"\n--- Investigating Invoice {inv.invoice_id} ---")
        pt_exists = PaymentTransaction.objects.filter(invoice=inv).exists()
        if pt_exists:
            print("  Has PT. Skipping.")
            continue
            
        print(f"  No PT found. Searching blockchain for argument '{inv.invoice_id}'...")
        
        # Search by App ID and Argument
        # Argument must be base64 encoded
        # Invoice ID is string 'KJRXWY9J'
        # The contract expects a string argument? 
        # In `payment_mutations.py`, it passes `str(internal_id)`.
        
        arg_bytes = inv.invoice_id.encode('utf-8')
        # algosdk.encoding.encode_as_bytes? No, just raw bytes for search?
        # Indexer expects base64 encoded value for `application-arg`
        arg_b64 = base64.b64encode(arg_bytes).decode('ascii')
        
        print(f"  Searching Indexer for app-id={app_id}, arg={arg_b64} (raw='{inv.invoice_id}')")
        
        try:
            # Search transactions
            # Note: Indexer might be delayed.
            response = indexer.search_transactions(
                application_id=app_id,
                application_args=arg_b64,
                min_round=0 # Look globally
            )
            
            txns = response.get('transactions', [])
            print(f"  Found {len(txns)} matching transactions.")
            
            for txn in txns:
                tx_id = txn.get('id')
                confirmed_round = txn.get('confirmed-round')
                sender = txn.get('sender')
                print(f"    Possible Match! Hash: {tx_id}")
                print(f"    Sender: {sender}")
                print(f"    Confirmed Round: {confirmed_round}")
                
                if confirmed_round and confirmed_round > 0:
                    print("    STATUS: CONFIRMED ON CHAIN")
                    print(f"    ACTION REQUIRED: Create PT {inv.invoice_id} with hash {tx_id}")
                    # Validate Payer?
                    # Validate Timestamp?
                    ts = txn.get('round-time')
                    if ts:
                        dt = datetime.fromtimestamp(ts)
                        print(f"    Time: {dt}")
        except Exception as e:
            print(f"  Indexer Error: {e}")

if __name__ == '__main__':
    find_ghosts()
find_ghosts()
