#!/usr/bin/env python3
"""
Test script to verify pysui_client CONFIO balance fix
"""
import os
import sys
import django
import asyncio

# Add the project directory to sys.path
sys.path.insert(0, '/Users/julian/Confio')

# Configure Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.pysui_client import get_pysui_client
from users.models import Account

async def test_confio_balances():
    """Test CONFIO balances with fixed pysui_client"""
    print("Testing CONFIO balances with fixed pysui_client...")
    
    # Test addresses from the accounts
    test_addresses = [
        ('Julian Personal', '0x79bb06b52bc5bddad6d4bb8a99e91b5644baad67d9c25006d44d1c1b6bd6a6e9'),
        ('Julian Business', '0x04b06df35ddfa55c5e62c9f1a1cd2c6da36efa1b8c0e80cecd9c6c3e9b7b5b85'),
        ('Wonju Personal', '0x8bc5e5e68c2ecb1c7ae1bb64c92af2c7e1b0f1e4c87a1a42ea982a24c11e0d33'),
        ('Wonju Business', '0xa4d5c8e24f86c4c80c0b4c1e37f9b8f0e1a2a8a8f0d8b6b3c3c2e0f8a1a4a8a8')
    ]
    
    async with await get_pysui_client() as client:
        print(f"Connected to pysui client")
        
        for name, address in test_addresses:
            try:
                confio_balance = await client.get_confio_balance(address)
                print(f"{name}: {confio_balance} CONFIO")
            except Exception as e:
                print(f"Error getting balance for {name}: {e}")

if __name__ == "__main__":
    asyncio.run(test_confio_balances())