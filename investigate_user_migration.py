
import os
import django
import sys
from django.conf import settings

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()


from users.models import User, Account
from send.models import SendTransaction
from algosdk.v2client import algod
from blockchain.algorand_account_manager import AlgorandAccountManager

def get_client():
    token = settings.ALGORAND_ALGOD_TOKEN
    address = settings.ALGORAND_ALGOD_ADDRESS
    return algod.AlgodClient(token, address)

def check_user():
    username = "wilberHL"
    new_address = "MDNNU3AXYICHOVIVHUAKITQEGUKSYRWJUQDATLJUQZMTFCVFRT34UO3J7Y"
    
    print(f"--- Investigating User: {username} ---")
    
    try:
        user = User.objects.get(username=username)
        print(f"User Found: ID={user.id}, Email={user.email}")
    except User.DoesNotExist:
        print("User not found by username!")
        return

    # Check accounts
    accounts = Account.objects.filter(user=user)
    print(f"Found {accounts.count()} accounts:")
    
    old_address = None
    
    for acc in accounts:
        print(f"  Account {acc.account_index} ({acc.account_type}): {acc.algorand_address}")
        if acc.algorand_address == new_address:
            print("    -> MATCHES NEW ADDRESS provided by user.")
        else:
            print("    -> Potential OLD ADDRESS.")
            old_address = acc.algorand_address

    old_address = "PRDLU7ZJRFB2ZMFJHQW3J5G3NEGN6HHV47CVKNHDAGF5P7MJAMHR37R72E"
    print(f"Using provided Old Address: {old_address}")

    # Check On-Chain Balances
    algod_client = get_client()
    
    if old_address:
        try:
            info = algod_client.account_info(old_address)
            print(f"\n--- OLD Address Status ({old_address}) ---")
            print(f"  ALGO Balance: {info.get('amount')}")
            for asset in info.get('assets', []):
                 print(f"  Asset {asset['asset-id']}: {asset['amount']}")
        except Exception as e:
            print(f"  Error checking old address: {e}")

    print(f"\n--- NEW Address Status ({new_address}) ---")
    try:
        info = algod_client.account_info(new_address)
        print(f"  ALGO Balance: {info.get('amount')}")
        for asset in info.get('assets', []):
             print(f"  Asset {asset['asset-id']}: {asset['amount']}")
    except Exception as e:
        print(f"  Error checking new address: {e}")

if __name__ == "__main__":
    check_user()
