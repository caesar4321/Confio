
import os
import django
import algosdk
from algosdk.v2client import indexer
import json
import datetime

# Setup Django (optional but good for env vars)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.conf import settings

TARGET_ADDR = "PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY"

def inspect_pffgg_history():
    print(f"Inspecting History for: {TARGET_ADDR}")
    
    # Configure Indexer
    indexer_address = settings.ALGORAND_INDEXER_ADDRESS
    indexer_token = settings.ALGORAND_INDEXER_TOKEN
    
    idx_client = indexer.IndexerClient(indexer_token, indexer_address)
    
    try:
        # Get all transactions for this address
        response = idx_client.search_transactions(address=TARGET_ADDR)
        transactions = response.get('transactions', [])
        
        print(f"Found {len(transactions)} transactions.")
        
        # Sort by round
        transactions.sort(key=lambda x: x.get('confirmed-round'))
        
        for tx in transactions:
            tx_type = tx.get('tx-type')
            sender = tx.get('sender')
            round_num = tx.get('confirmed-round')
            ts = tx.get('round-time')
            date_str = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
            
            # Determine direction
            direction = "OUT" if sender == TARGET_ADDR else "IN"
            
            details = ""
            if tx_type == 'pay':
                pay = tx.get('payment-transaction', {})
                amt = pay.get('amount')
                rcv = pay.get('receiver')
                details = f"{amt} uA -> {rcv}"
            elif tx_type == 'axfer':
                ax = tx.get('asset-transfer-transaction', {})
                asa = ax.get('asset-id')
                amt = ax.get('amount')
                rcv = ax.get('receiver')
                details = f"ASA {asa}: {amt} -> {rcv}"
            
            print(f"[{date_str}] [{round_num}] {direction} ({tx_type}) {details} | Sender: {sender}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_pffgg_history()
