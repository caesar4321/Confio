#!/usr/bin/env python
import os
import sys
import django
import asyncio

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'confio_backend.settings')
django.setup()

from blockchain.algorand_sponsor_service import algorand_sponsor_service

async def main():
    vault_address = "T53KTDAXITS34Y5435VREARQTREJHUK4WEIF6FU5KLPW7OS5QET5QMHCEY"
    
    print(f"Checking vault balance...")
    try:
        info = algorand_sponsor_service.algod.account_info(vault_address)
        current_balance = info.get('amount', 0)
        min_balance = info.get('min-balance', 0)
        
        print(f"Current balance: {current_balance} microAlgos ({current_balance/1_000_000:.6f} ALGO)")
        print(f"Minimum balance: {min_balance} microAlgos ({min_balance/1_000_000:.6f} ALGO)")
        print(f"Shortfall: {max(0, min_balance - current_balance)} microAlgos")
        
        if current_balance < min_balance:
            print(f"\nFunding vault with 1 ALGO...")
            result = await algorand_sponsor_service.fund_account(vault_address, 1_000_000)
            
            if result.get('success'):
                print(f"✅ Success! Transaction ID: {result.get('tx_id')}")
                
                # Check new balance
                new_info = algorand_sponsor_service.algod.account_info(vault_address)
                new_balance = new_info.get('amount', 0)
                print(f"New balance: {new_balance} microAlgos ({new_balance/1_000_000:.6f} ALGO)")
            else:
                print(f"❌ Failed: {result.get('error')}")
                sys.exit(1)
        else:
            print("✅ Vault already has sufficient balance")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
