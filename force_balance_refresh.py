#!/usr/bin/env python
"""
Force refresh balance for the recipient account
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
from blockchain.models import Balance
from django.core.cache import cache

def force_refresh_balance():
    """Force refresh balance for recipient account"""
    
    recipient_address = "XTITQDJSETDOQG3WMSDKE7QPPAX22ZMDX6PZ5B43E4JCFTEBPUJGDY2RGQ"
    
    print("=" * 60)
    print("FORCING BALANCE REFRESH")
    print("=" * 60)
    
    # Find the account
    try:
        account = Account.objects.filter(algorand_address=recipient_address).first()
        
        if not account:
            print("❌ Account not found in database")
            return
            
        print(f"\n✅ Found account:")
        print(f"   User: {account.user.email}")
        print(f"   Address: {account.algorand_address}")
        
        # Clear all caches for this account
        print(f"\n1. Clearing all caches...")
        
        # Clear Redis cache for all token types
        for token in ['CONFIO', 'CUSD', 'USDC', 'SUI']:
            cache_key = f"balance:{account.id}:{token}"
            cache.delete(cache_key)
            print(f"   Cleared cache for {token}")
        
        # Force refresh from blockchain
        print(f"\n2. Forcing blockchain query for CONFIO...")
        
        balance_data = BalanceService.get_balance(
            account,
            'CONFIO',
            force_refresh=True  # This forces blockchain query
        )
        
        print(f"   New CONFIO balance: {balance_data['amount']} CONFIO")
        print(f"   Last synced: {balance_data['last_synced']}")
        
        # Verify it's saved in database
        print(f"\n3. Verifying database update...")
        
        try:
            balance_record = Balance.objects.get(account=account, token='CONFIO')
            print(f"   Database balance: {balance_record.amount} CONFIO")
            print(f"   Is stale: {balance_record.is_stale}")
            print(f"   Last blockchain check: {balance_record.last_blockchain_check}")
        except Balance.DoesNotExist:
            print(f"   Creating new balance record...")
            Balance.objects.create(
                account=account,
                token='CONFIO',
                amount=balance_data['amount'],
                is_stale=False
            )
            print(f"   ✅ Created balance record")
        
        # Also refresh CUSD balance
        print(f"\n4. Also refreshing CUSD balance...")
        cusd_data = BalanceService.get_balance(
            account,
            'CUSD',
            force_refresh=True
        )
        print(f"   CUSD balance: {cusd_data['amount']} CUSD")
        
        print(f"\n✅ Balance refresh complete!")
        print(f"\n📱 Next steps:")
        print(f"   1. Pull to refresh in the app")
        print(f"   2. The app should now show 5.00 CONFIO")
        print(f"   3. If not, check that the app is querying with token type 'CONFIO'")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    force_refresh_balance()