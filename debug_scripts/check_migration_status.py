import os
import django
from django.conf import settings
import algosdk
from algosdk.v2client import indexer

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User, Account

# Testnet Config
ALGOD_ADDRESS = "https://testnet-api.algonode.cloud"
ALGOD_TOKEN = ""
INDEXER_ADDRESS = "https://testnet-idx.algonode.cloud"
INDEXER_TOKEN = ""

def check_status(user_id):
    try:
        user = User.objects.get(id=user_id)
        print(f"Checking User ID: {user_id} ({user.email})")
        
        accounts = Account.objects.filter(user=user)
        algod_client = algosdk.v2client.algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
        indexer_client = indexer.IndexerClient(INDEXER_TOKEN, INDEXER_ADDRESS)

        for acc in accounts:
            print(f"\nAccount: {acc.account_type}_{acc.account_index}")
            print(f"  - Migrated: {acc.is_keyless_migrated}")
            print(f"  - Address (DB): {acc.algorand_address}")
            
            if acc.algorand_address:
                try:
                    # Check Balance
                    info = algod_client.account_info(acc.algorand_address)
                    balance = info.get('amount', 0)
                    assets = info.get('assets', [])
                    print(f"  - On-Chain Balance: {balance} microAlgos")
                    print(f"  - Assets: {assets}")

                    # Check History to find V1
                    print("  - Fetching Transaction History...")
                    response = indexer_client.search_transactions_by_address(acc.algorand_address)
                    txns = response.get('transactions', [])
                    print(f"  - Found {len(txns)} transactions")
                    
                    found_funder = False
                    for txn in txns:
                        # Looking for a payment TO this address from SOMEONE ELSE (ignoring the Sponsor)
                        sender = txn.get('sender')
                        rcv = txn.get('payment-transaction', {}).get('receiver')
                        
                        # Known Sponsor (from .env.testnet)
                        SPONSOR = "UQ6WZKLQBQCNAQTOSEWZZXDY376RZTYP2U2ZZT7OIPEGP376HYLTCSL6E4"
                        
                        if rcv == acc.algorand_address and sender != acc.algorand_address:
                            print(f"    - Received funds from: {sender}")
                            if sender == SPONSOR:
                                print("      (Sponsor Funding)")
                            else:
                                print("      (POSSIBLE V1 WALLET)")
                                # Check V1 Balance
                                v1_info = algod_client.account_info(sender)
                                v1_bal = v1_info.get('amount', 0)
                                v1_assets = v1_info.get('assets', [])
                                print(f"      -> V1 Balance: {v1_bal} microAlgos")
                                print(f"      -> V1 Assets: {v1_assets}")
                                found_funder = True
                                
                    if not found_funder:
                        print("    - No obvious V1 funder found (only Sponsor or self)")

                except Exception as e:
                    print(f"  - On-Chain Check Failed: {e}")
            else:
                print("  - No Address in DB")

        print(f"User {user_id} not found")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_status(8)

if __name__ == "__main__":
    check_status(8)
