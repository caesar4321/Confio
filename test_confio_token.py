#!/usr/bin/env python
"""
Test CONFIO token integration on Algorand
"""
import os
import sys
import django
import asyncio

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_client import AlgorandClient, get_algorand_client
from decimal import Decimal


async def test_confio_token():
    """Test CONFIO token on Algorand"""
    
    print("=" * 60)
    print("CONFIO TOKEN TEST ON ALGORAND")
    print("=" * 60)
    
    async with await get_algorand_client() as client:
        # Token details
        CONFIO_ASSET_ID = 743890784
        CREATOR_ADDRESS = "KNKFUBM3GHOLF6S7L2O7JU6YDB7PCRV3PKBOBRCABLYHBHXRFXKNDWGAWE"
        
        print(f"\nCONFIO Token Details:")
        print(f"Asset ID: {CONFIO_ASSET_ID}")
        print(f"Creator: {CREATOR_ADDRESS}")
        
        # Test 1: Get asset information
        print("\n1. Getting asset information...")
        try:
            asset_info = await client.get_asset_info(CONFIO_ASSET_ID)
            if asset_info:
                params = asset_info.get('params', {})
                print(f"   Name: {params.get('name')}")
                print(f"   Symbol: {params.get('unit-name')}")
                print(f"   Decimals: {params.get('decimals')}")
                print(f"   Total Supply: {params.get('total') / (10 ** params.get('decimals', 0)):,.0f}")
                print(f"   URL: {params.get('url')}")
                print(f"   ✓ Asset information retrieved successfully")
            else:
                print(f"   ✗ Failed to get asset info")
        except Exception as e:
            print(f"   ✗ Error: {e}")
        
        # Test 2: Check creator's CONFIO balance
        print(f"\n2. Checking creator's CONFIO balance...")
        try:
            confio_balance = await client.get_confio_balance(CREATOR_ADDRESS)
            print(f"   Creator CONFIO balance: {confio_balance:,.2f} CONFIO")
            
            if confio_balance == 0:
                print(f"   ⚠️  Creator needs to opt-in to receive CONFIO tokens")
                print(f"   Note: Even the creator must opt-in to their own asset!")
            else:
                print(f"   ✓ Creator holds {confio_balance:,.0f} CONFIO tokens")
        except Exception as e:
            print(f"   ✗ Error getting balance: {e}")
        
        # Test 3: Test balance service integration
        print("\n3. Testing balance service integration...")
        try:
            from blockchain.balance_service import BalanceService
            from users.models import Account
            
            # Get a test account (if exists)
            test_account = Account.objects.filter(deleted_at__isnull=True).first()
            if test_account:
                print(f"   Using account: {test_account.aptos_address[:20]}...")
                
                # Try to get CONFIO balance through service
                balance_data = BalanceService.get_balance(test_account, 'CONFIO')
                print(f"   CONFIO balance: {balance_data['amount']} CONFIO")
                
                # Note: Balance will be 0 unless account has opted in
                if balance_data['amount'] == 0:
                    print(f"   Note: Account needs to opt-in to CONFIO asset ID {CONFIO_ASSET_ID}")
            else:
                print("   No test accounts found in database")
                
        except Exception as e:
            print(f"   ✗ Error testing balance service: {e}")
        
        # Test 4: Verify all configured assets
        print("\n4. Verifying all configured assets...")
        assets = {
            'USDC': client.USDC_ASSET_ID,
            'CONFIO': client.CONFIO_ASSET_ID,
            'cUSD': client.CUSD_ASSET_ID
        }
        
        for name, asset_id in assets.items():
            if asset_id:
                print(f"   {name}: Asset ID {asset_id} ✓")
            else:
                print(f"   {name}: Not configured")
        
        print("\n" + "=" * 60)
        print("CONFIO TOKEN TEST COMPLETE")
        print("=" * 60)
        
        print("\nNext Steps:")
        print("1. Creator must opt-in to CONFIO asset to receive the tokens")
        print("2. Users must opt-in to asset ID 743890784 before receiving CONFIO")
        print("3. View on explorer: https://testnet.algoexplorer.io/asset/743890784")


if __name__ == "__main__":
    # Run async test
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(test_confio_token())
    finally:
        loop.close()