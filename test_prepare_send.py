#!/usr/bin/env python3
"""
Test prepare_send_transaction specifically
"""
import asyncio
import os
import sys
import django
from decimal import Decimal

# Setup Django
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.sponsor_service_pysui import SponsorServicePySui
from users.models import Account
from asgiref.sync import sync_to_async

async def test_prepare_send():
    """Test prepare_send_transaction"""
    
    try:
        # Get a test account
        print("Getting test account...")
        account = await sync_to_async(lambda: Account.objects.filter(
            aptos_address__isnull=False,
            aptos_address__gt=''
        ).first())()
        
        if not account:
            print("ERROR: No account with Sui address found")
            return
            
        print(f"Using account: {account.id}")
        print(f"Sui address: {account.aptos_address}")
        
        # Test getting coins first
        from blockchain.pysui_client import get_pysui_client
        from django.conf import settings
        
        async with await get_pysui_client() as client:
            print("\nGetting CUSD coins...")
            cusd_type = f"{settings.CUSD_PACKAGE_ID}::cusd::CUSD"
            coins = await client.get_coins(
                address=account.aptos_address,
                coin_type=cusd_type,
                limit=10
            )
            print(f"Found {len(coins)} CUSD coins")
            for i, coin in enumerate(coins[:3]):
                print(f"  Coin {i}: {coin['objectId']}, balance: {coin['balance']}")
        
        # Now test prepare_send_transaction
        print("\nPreparing send transaction...")
        result = await SponsorServicePySui.prepare_send_transaction(
            account=account,
            recipient="0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            amount=Decimal("0.01"),
            token_type="CUSD"
        )
        
        print(f"\nResult: {result}")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_prepare_send())