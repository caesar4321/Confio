
import os
import django
import algosdk
from algosdk.v2client import indexer
import json
import base64

# Setup Django (optional but good for env vars)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.conf import settings

def inspect_group(txid):
    print(f"Inspecting Group for Transaction: {txid}")
    
    # Configure Indexer
    indexer_address = settings.ALGORAND_INDEXER_ADDRESS
    indexer_token = settings.ALGORAND_INDEXER_TOKEN
    
    idx_client = indexer.IndexerClient(indexer_token, indexer_address)
    
    try:
        # Get the initial tx to find the group ID
        response = idx_client.search_transactions(txid=txid)
        transactions = response.get('transactions', [])
        
        if not transactions:
            print("Transaction not found.")
            return

        initial_tx = transactions[0]
        group_id = initial_tx.get('group')
        
        if not group_id:
            print("This transaction is not part of a group.")
            return
            
        print(f"Group ID found: {group_id}")
        
        # Search for all transactions in this group
        # Note: 'group' parameter expected base64 encoded? The search_transactions param is `group_id`?
        # SDK says `group_id` takes bytes? or decoded? 
        # Actually usually it's base64 in response, pass base64 to search? No, `group_id` usually needs bytes or correct format.
        # Decode base64 group string to bytes
        group_id_bytes = base64.b64decode(group_id)
        
        # Pass bytes to SDK
        group_resp = idx_client.search_transactions(group_id=group_id_bytes)
        group_txs = group_resp.get('transactions', [])
        
        print(f"Found {len(group_txs)} transactions in group.")
        
        # Sort by intra-round-offset to get execution order
        group_txs.sort(key=lambda x: x.get('intra-round-offset', 0))
        
        known = {
            "PFFGG74A3BTBMPOJSTJALIIF4PO3JQJCS3WKYYXDQQ73J35EG2QOSCQRSY": "Funded V1 (Expected Source)",
            "P7WYM6SDBLV5UWM6AWFD4ZCNH7DZE3EICBZOAOORAUHDBVQ44RRS6ZLZZU": "Derived V1 (Incorrect Source?)",
            "D4LMXEAOL6IRA25ZWMIU4XQZMYQ6NY2USH742QZWM23ZUGTVWJFCFPBB2I": "Old V2",
            "67BBOECDLISLNV5E5ESGP2ZNHIWDMXDSY7GU5XKW7WBAJM4JBBRXLYZJV4": "Funded V2 (Likely Correct)"
        }

        for i, tx in enumerate(group_txs):
            print(f"\n--- Tx {i+1} ---")
            print(f"ID: {tx.get('id')}")
            print(f"Type: {tx.get('tx-type')}")
            
            sender = tx.get('sender')
            sender_label = known.get(sender, sender)
            print(f"Sender: {sender_label}")
            
            if 'payment-transaction' in tx:
                pay = tx['payment-transaction']
                rcv = pay.get('receiver')
                rcv_label = known.get(rcv, rcv)
                print(f"Receiver: {rcv_label}")
                print(f"Amount: {pay.get('amount')}")
                if pay.get('close-amount', 0) > 0:
                    cls = pay.get('close-remainder-to')
                    cls_label = known.get(cls, cls)
                    print(f"Close To: {cls_label}")
            
            if 'asset-transfer-transaction' in tx:
                axfer = tx['asset-transfer-transaction']
                rcv = axfer.get('receiver')
                rcv_label = known.get(rcv, rcv)
                print(f"Asset ID: {axfer.get('asset-id')}")
                print(f"Receiver: {rcv_label}")
                print(f"Amount: {axfer.get('amount')}")
                if axfer.get('close-amount', 0) > 0:
                     cls = axfer.get('close-to')
                     print(f"Close To: {cls}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_group("K2CG7KJHQASOICQZGPQYDGVH4T4EYGL75ZCAWXIJE5EUP3HYTJFQ")
