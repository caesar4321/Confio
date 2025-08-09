#!/usr/bin/env python
"""
Test script for Algorand integration
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


async def test_algorand_connection():
    """Test basic Algorand connection and operations"""
    
    print("Testing Algorand Integration...")
    print("-" * 50)
    
    async with await get_algorand_client() as client:
        # Test 1: Health check
        print("1. Testing health check...")
        health = await client.health_check()
        print(f"   Health check: {'✓ PASSED' if health else '✗ FAILED'}")
        
        # Test 2: Get node status
        print("\n2. Getting node status...")
        try:
            status = client.algod.status()
            print(f"   Network: Algorand {status.get('network-version', 'Unknown')}")
            print(f"   Last Round: {status.get('last-round', 'Unknown')}")
            print(f"   ✓ Node connection successful")
        except Exception as e:
            print(f"   ✗ Failed to get node status: {e}")
        
        # Test 3: Test account (you can replace with a real testnet account)
        test_address = "HZ57J3K46JIJXILONBBZOHX6BKPXEM2VVXNRFSUED6DKFD5ZD24PMJ3MVA"  # Algorand testnet dispenser
        
        print(f"\n3. Testing balance retrieval for address:")
        print(f"   {test_address}")
        
        # Test ALGO balance
        try:
            algo_balance = await client.get_algo_balance(test_address)
            print(f"   ALGO balance: {algo_balance} ALGO")
        except Exception as e:
            print(f"   ✗ Failed to get ALGO balance: {e}")
        
        # Test USDC balance
        try:
            usdc_balance = await client.get_usdc_balance(test_address)
            print(f"   USDC balance: {usdc_balance} USDC")
        except Exception as e:
            print(f"   ✗ Failed to get USDC balance: {e}")
        
        # Test cUSD balance (will use USDC as fallback if not configured)
        try:
            cusd_balance = await client.get_cusd_balance(test_address)
            print(f"   cUSD balance: {cusd_balance} cUSD")
        except Exception as e:
            print(f"   ✗ Failed to get cUSD balance: {e}")
        
        # Test 4: Test account creation
        print("\n4. Testing account creation...")
        try:
            new_account = await client.create_account()
            print(f"   ✓ New account created:")
            print(f"     Address: {new_account['address']}")
            print(f"     Mnemonic: {new_account['mnemonic'][:20]}...")  # Show only part of mnemonic
        except Exception as e:
            print(f"   ✗ Failed to create account: {e}")
        
        # Test 5: Test transaction building (dry run only)
        print("\n5. Testing transaction building...")
        try:
            if 'new_account' in locals():
                # Build a test transaction (won't execute)
                tx_bytes, tx_id = await client.build_transfer_transaction(
                    sender=test_address,
                    recipient=new_account['address'],
                    amount=Decimal('0.1'),
                    asset_id=None,  # ALGO transfer
                    note="Test transaction"
                )
                print(f"   ✓ Transaction built successfully")
                print(f"     Transaction ID: {tx_id}")
            else:
                print("   ⚠ Skipped: No test account created")
        except Exception as e:
            print(f"   ✗ Failed to build transaction: {e}")
    
    print("\n" + "-" * 50)
    print("Algorand Integration Test Complete!")


async def test_balance_service():
    """Test the balance service with Algorand"""
    from blockchain.balance_service import BalanceService
    from users.models import Account
    
    print("\n\nTesting Balance Service Integration...")
    print("-" * 50)
    
    # Get a test account from database (if exists)
    try:
        test_account = Account.objects.filter(deleted_at__isnull=True).first()
        if test_account:
            print(f"Using account: {test_account.algorand_address}")
            
            # Test balance retrieval through service
            balance_data = BalanceService.get_balance(test_account, 'CUSD')
            print(f"Balance Service Result:")
            print(f"  Amount: {balance_data['amount']} cUSD")
            print(f"  Available: {balance_data['available']} cUSD")
            print(f"  Pending: {balance_data['pending']} cUSD")
            print(f"  Last Synced: {balance_data['last_synced']}")
            print(f"  Is Stale: {balance_data['is_stale']}")
        else:
            print("No active accounts found in database")
    except Exception as e:
        print(f"Error testing balance service: {e}")


if __name__ == "__main__":
    print("=" * 50)
    print("ALGORAND INTEGRATION TEST")
    print("=" * 50)
    
    # Run async tests
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        # Test Algorand client
        loop.run_until_complete(test_algorand_connection())
        
        # Test Balance Service
        loop.run_until_complete(test_balance_service())
        
    finally:
        loop.close()
    
    print("\nAll tests completed!")