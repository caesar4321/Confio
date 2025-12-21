import base64
import time
from datetime import datetime, timedelta
from blockchain.algorand_client import get_indexer_client
from payments.models import Invoice, PaymentTransaction
from django.conf import settings

def find_ghosts():
    print("Searching for broken Pending Invoices (Client-side filtering)...")
    ids = ['KJRXWY9J', 'X88YHR4Q'] 
    
    invoices = Invoice.objects.filter(invoice_id__in=ids)
    if not invoices.exists():
        print("No target invoices found.")
        return

    indexer = get_indexer_client()
    app_id = getattr(settings, 'ALGORAND_PAYMENT_APP_ID', None) or getattr(settings, 'ALGORAND_CUSD_APP_ID', None)
    print(f"Using App ID: {app_id}")
    
    # 1. Fetch recent transactions for this App (last 1000?)
    try:
        response = indexer.search_transactions(
            application_id=app_id,
            limit=1000,
            min_round=0 # In production, restrict this. For testnet, 1000 is fine.
        )
        txns = response.get('transactions', [])
        print(f"Fetched {len(txns)} app calls.")
    except Exception as e:
        print(f"Indexer Error: {e}")
        return

    # 2. Iterate and match
    for inv in invoices:
        print(f"\n--- Investigating Invoice {inv.invoice_id} ---")
        pt_exists = PaymentTransaction.objects.filter(invoice=inv).exists()
        if pt_exists:
            print("  Has PT (likely debug). Checking chain anyway...")
            # continue - REMOVED

        target_arg = inv.invoice_id
        found = False
        
        for txn in txns:
            # Check application-transaction -> application-args
            appl = txn.get('application-transaction', {})
            args = appl.get('application-args', [])
            
            # Args are base64
            for arg_b64 in args:
                try:
                    arg_decoded = base64.b64decode(arg_b64).decode('utf-8', errors='ignore')
                    if target_arg in arg_decoded:
                        print(f"  MATCH FOUND! Hash: {txn['id']}")
                        print(f"    Sender: {txn['sender']}")
                        print(f"    Round: {txn['confirmed-round']}")
                        print(f"    Args: {arg_decoded}")
                        found = True
                        break # Found for this txn
                except:
                    pass
            
            if found:
                break # Found for this invoice
        
        if not found:
            print("  No matching transaction found on-chain.")

if __name__ == '__main__':
    find_ghosts()
find_ghosts()
