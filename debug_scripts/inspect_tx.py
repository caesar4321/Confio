
import os
import django
import algosdk
from algosdk.v2client import indexer
import json
import sys

# Setup Django (optional but good for env vars)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.conf import settings

def inspect_tx(txid):
    print(f"Inspecting Transaction: {txid}")
    
    # Configure Indexer
    indexer_address = settings.ALGORAND_INDEXER_ADDRESS
    indexer_token = settings.ALGORAND_INDEXER_TOKEN
    
    print(f"Connecting to Indexer: {indexer_address}")
    
    idx_client = indexer.IndexerClient(indexer_token, indexer_address)
    
    try:
        response = idx_client.search_transactions(txid=txid)
        transactions = response.get('transactions', [])
        
        if not transactions:
            print("Transaction not found.")
            return

        tx = transactions[0]
        print("\n--- Transaction Details ---")
        print(f"Type: {tx.get('tx-type')}")
        print(f"Sender: {tx.get('sender')}")
        
        if 'payment-transaction' in tx:
            pay = tx['payment-transaction']
            print(f"Receiver: {pay.get('receiver')}")
            print(f"Amount: {pay.get('amount')} microAlgos")
            if pay.get('close-amount', 0) > 0:
                print(f"Close To: {pay.get('close-remainder-to')}")
                print(f"Close Amount: {pay.get('close-amount')}")
                
        if 'asset-transfer-transaction' in tx:
            axfer = tx['asset-transfer-transaction']
            print(f"Asset ID: {axfer.get('asset-id')}")
            print(f"Receiver: {axfer.get('receiver')}")
            print(f"Amount: {axfer.get('amount')}")
            
        print(f"Round: {tx.get('confirmed-round')}")
        print(f"Time: {tx.get('round-time')}")
        
        # Check if known addresses involved
        known = {
            "PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY": "Funded V1 (Expected Source)",
            "P7WYM6SDBLV5UWM6AWFD4ZCNH7DZE3EICBZOAOORAUHDBVQ44RRS6ZLZZU": "Derived V1 (Incorrect Source?)",
            "D4LMXEAOL6IRA25ZWMIU4XQZMYQ6NY2USH742QZWM23ZUGTVWJFCFPBB2I": "V2 (Goal Destination)"
        }
        
        sender = tx.get('sender')
        receiver = tx.get('payment-transaction', {}).get('receiver') or tx.get('asset-transfer-transaction', {}).get('receiver')
        
        if sender in known:
            print(f"SENDER IS: {known[sender]}")
        if receiver in known:
            print(f"RECEIVER IS: {known[receiver]}")
            
        print("\nFull JSON:")
        print(json.dumps(tx, indent=2))

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_tx("K2CG7KJHQASOICQZGPQYDGVH4T4EYGL75ZCAWXIJE5EUP3HYTJFQ")
