import os
import sys
import django
from django.conf import settings
from algosdk.v2client import algod

print("DEBUG: Setting up Django...", flush=True)
# Initialize Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
print("DEBUG: Django setup complete.", flush=True)

# Constants from .env.mainnet
CONFIO_ASSET_ID = 3351104258
CUSD_ASSET_ID = 3198259450
USDC_ASSET_ID = 31566704
ALGOD_ADDRESS = "https://mainnet-api.4160.nodely.dev"
ALGOD_TOKEN = ""

def run_audit():
    print("Starting Audit...", flush=True)
    
    # Initialize Algorand Client
    client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
    
    from users.models import Account
    
    print("DEBUG: Querying accounts...", flush=True)
    accounts = Account.objects.filter(deleted_at__isnull=True).select_related('user')
    total_accounts = accounts.count()
    print(f"Checking {total_accounts} accounts...", flush=True)
    
    positive_balance_count = 0
    
    for i, acc in enumerate(accounts):
        if not acc.algorand_address:
            continue
            
        try:
            info = client.account_info(acc.algorand_address)
            assets = info.get('assets', [])
            
            has_balance = False
            relevant_assets = {}
            
            for asset in assets:
                aid = asset['asset-id']
                amount = asset['amount']
                
                if amount > 0:
                    if aid == CONFIO_ASSET_ID:
                        has_balance = True
                        relevant_assets['CONFIO'] = amount
                    elif aid == CUSD_ASSET_ID:
                        has_balance = True
                        relevant_assets['cUSD'] = amount
                    elif aid == USDC_ASSET_ID:
                        has_balance = True
                        relevant_assets['USDC'] = amount
            
            if has_balance:
                positive_balance_count += 1
                username = acc.user.username if acc.user else "Unknown"
                print(f"User: {username} ({acc.algorand_address}) - {relevant_assets}", flush=True)

        except Exception as e:
            # print(f"Error checking {acc.algorand_address}: {e}")
            pass
            
        if i % 50 == 0:
            print(f"Processed {i}/{total_accounts}...", flush=True)

    print("-" * 30, flush=True)
    print(f"Total Users with > 0 Balance: {positive_balance_count}", flush=True)
    print("-" * 30, flush=True)

if __name__ == '__main__':
    run_audit()
