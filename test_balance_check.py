#!/usr/bin/env python3
"""
Test balance checking for distributed tokens
"""
import os
import sys
import asyncio

# Setup Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from blockchain.aptos_balance_service import AptosBalanceService

async def test_balance():
    """Test balance checking for the distributed address"""
    
    # Test address that received CONFIO and cUSD tokens
    test_address = "0xb5c85a6044403766e5d32e93b6543a3712a8648a040385bf33283d5c55508f1c"
    
    print(f"Testing balance for address: {test_address}")
    
    # Test CONFIO balance
    print("\n--- Testing CONFIO Balance ---")
    confio_balance = await AptosBalanceService.get_token_balance_async(
        test_address, 
        AptosBalanceService.CONFIO_ADDRESS, 
        6
    )
    print(f"CONFIO Balance: {confio_balance}")
    
    # Test cUSD balance (should now show 200 after minting)
    print("\n--- Testing cUSD Balance ---")
    cusd_balance = await AptosBalanceService.get_token_balance_async(
        test_address,
        AptosBalanceService.CUSD_ADDRESS,
        6
    )
    print(f"cUSD Balance: {cusd_balance}")

if __name__ == "__main__":
    asyncio.run(test_balance())