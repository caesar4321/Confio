#!/usr/bin/env python
"""
Test sponsored opt-in directly
"""

import os
import sys
import django
import asyncio

# Add project to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_sponsor_service import algorand_sponsor_service

async def test_opt_in():
    """Test sponsored opt-in for a user"""
    user_address = "XTITQDJSETDOQG3WMSDKE7QPPAX22ZMDX6PZ5B43E4JCFTEBPUJGDY2RGQ"
    asset_id = 743890784  # CONFIO token
    
    print(f"Testing sponsored opt-in for:")
    print(f"  User: {user_address}")
    print(f"  Asset: {asset_id}")
    print()
    
    # Check sponsor health first
    health = await algorand_sponsor_service.check_sponsor_health()
    print(f"Sponsor health: {health}")
    
    if not health.get('can_sponsor'):
        print("Sponsor service not available!")
        return
    
    # Try to execute opt-in
    print("\nExecuting sponsored opt-in...")
    result = await algorand_sponsor_service.execute_server_side_opt_in(
        user_address=user_address,
        asset_id=asset_id
    )
    
    print(f"\nResult: {result}")
    
    if result.get('success'):
        print("\n✅ Success!")
        if result.get('already_opted_in'):
            print("Already opted in to this asset")
        elif result.get('requires_user_signature'):
            print("Transaction requires user signature")
            print(f"User transaction: {result.get('user_transaction', 'N/A')[:50]}...")
            print(f"Sponsor transaction: {result.get('sponsor_transaction', 'N/A')[:50]}...")
        else:
            print("Opt-in completed server-side")
    else:
        print(f"\n❌ Failed: {result.get('error')}")

if __name__ == "__main__":
    asyncio.run(test_opt_in())