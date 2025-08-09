#!/usr/bin/env python
"""
Check the balance of the recipient account directly
"""

import os
import sys
import django
from algosdk.v2client import algod

# Add project to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_account_manager import AlgorandAccountManager
from users.models import Account
from blockchain.balance_service import BalanceService

def check_recipient_balance():
    """Check recipient account balance in both blockchain and database"""
    
    recipient_address = "XTITQDJSETDOQG3WMSDKE7QPPAX22ZMDX6PZ5B43E4JCFTEBPUJGDY2RGQ"
    
    print("=" * 60)
    print("CHECKING RECIPIENT BALANCE")
    print("=" * 60)
    
    # 1. Check directly on blockchain
    print("\n1. BLOCKCHAIN BALANCE (Direct from Algorand):")
    client = algod.AlgodClient('', 'https://testnet-api.algonode.cloud')
    
    try:
        info = client.account_info(recipient_address)
        print(f"   ALGO: {info['amount'] / 1_000_000} ALGO")
        
        # Check CONFIO balance
        assets = info.get('assets', [])
        for asset in assets:
            if asset['asset-id'] == AlgorandAccountManager.CONFIO_ASSET_ID:
                confio_balance = asset['amount'] / 1_000_000
                print(f"   CONFIO: {confio_balance} CONFIO ✅")
                break
        else:
            print(f"   CONFIO: Not found in assets")
    except Exception as e:
        print(f"   Error: {e}")
    
    # 2. Check in Django database
    print("\n2. DATABASE BALANCE (Django Account model):")
    try:
        # Find account by Algorand address
        accounts = Account.objects.filter(algorand_address=recipient_address)
        
        if accounts.exists():
            for account in accounts:
                print(f"\n   Account found:")
                print(f"   - User: {account.user.email if account.user else 'No user'}")
                print(f"   - Account Type: {account.account_type}")
                print(f"   - Account Index: {account.account_index}")
                print(f"   - Active: {account.is_active}")
                print(f"   - Algorand Address: {account.algorand_address}")
                
                # Check cached balance
                print(f"\n   Cached Balance (from BalanceService):")
                
                # Force refresh to get latest from blockchain
                balance_data = BalanceService.get_balance(
                    account,
                    'CONFIO',
                    force_refresh=True  # Force blockchain query
                )
                
                print(f"   - CONFIO: {balance_data['amount']} CONFIO")
                print(f"   - Last Synced: {balance_data['last_synced']}")
                print(f"   - Is Stale: {balance_data['is_stale']}")
                
                # Also check the Balance model directly
                from blockchain.models import Balance
                try:
                    balance_record = Balance.objects.get(account=account, token='CONFIO')
                    print(f"\n   Balance Record in DB:")
                    print(f"   - Amount: {balance_record.amount}")
                    print(f"   - Last Synced: {balance_record.last_synced}")
                    print(f"   - Is Stale: {balance_record.is_stale}")
                except Balance.DoesNotExist:
                    print(f"\n   No Balance record in DB for CONFIO")
        else:
            print(f"   No account found with address: {recipient_address}")
    except Exception as e:
        print(f"   Error: {e}")
        import traceback
        traceback.print_exc()
    
    # 3. Check cache
    print("\n3. CACHE STATUS:")
    try:
        from django.core.cache import cache
        
        # Try to find the account to get its ID
        accounts = Account.objects.filter(algorand_address=recipient_address)
        if accounts.exists():
            account = accounts.first()
            cache_key = f"balance:{account.id}:CONFIO"
            cached_balance = cache.get(cache_key)
            
            if cached_balance:
                print(f"   Redis Cache Key: {cache_key}")
                print(f"   Cached Balance: {cached_balance.amount if hasattr(cached_balance, 'amount') else cached_balance}")
            else:
                print(f"   No cached balance found for key: {cache_key}")
                
            # Clear the cache to force refresh
            print(f"\n   Clearing cache for account...")
            cache.delete(cache_key)
            print(f"   Cache cleared. Next query will fetch from blockchain.")
    except Exception as e:
        print(f"   Cache error: {e}")

if __name__ == "__main__":
    check_recipient_balance()