
import os
import django
from algosdk.v2client import algod, indexer
import datetime

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.conf import settings

ADDR = "67BBOECDLISLNV5E5ESGP2ZNHIWDMXDSY7GU5XKW7WBAJM4JBBRXLYZJV4"

def inspect_67bbo():
    print(f"Inspecting 67BBO...")
    
    # 1. Check Balance
    client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
    try:
        info = client.account_info(ADDR)
        print(f"Balance: {info.get('amount')} microAlgos")
        print("Assets:")
        for asset in info.get('assets', []):
            if asset['amount'] > 0:
                print(f" - ID {asset['asset-id']}: {asset['amount']}")
    except Exception as e:
        print(f"Error checking balance: {e}")

    # 2. Check History (Funding Source)
    idx_client = indexer.IndexerClient(settings.ALGORAND_INDEXER_TOKEN, settings.ALGORAND_INDEXER_ADDRESS)
    try:
        resp = idx_client.search_transactions(address=ADDR)
        txs = resp.get('transactions', [])
        print(f"\nFound {len(txs)} transactions.")
        txs.sort(key=lambda x: x.get('confirmed-round'))
        
        for tx in txs:
            tx_type = tx.get('tx-type')
            sender = tx.get('sender')
            round_num = tx.get('confirmed-round')
            ts = tx.get('round-time')
            date_str = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
            
            direction = "OUT" if sender == ADDR else "IN"
            
            details = ""
            if tx_type == 'pay':
                details = f"Amount: {tx.get('payment-transaction', {}).get('amount')}"
            elif tx_type == 'axfer':
                ax = tx.get('asset-transfer-transaction', {})
                details = f"ASA {ax.get('asset-id')}: {ax.get('amount')}"
                
            print(f"[{date_str}] {direction} ({tx_type}) {details} | Peer: {sender if direction == 'IN' else '...' }")
            
    except Exception as e:
        print(f"Error checking history: {e}")

if __name__ == "__main__":
    inspect_67bbo()
