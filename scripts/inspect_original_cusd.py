#!/usr/bin/env python3
"""
Script to inspect the original cUSD package structure
and find the required parameters for minting
"""
import asyncio
import sys
import os
sys.path.append('/Users/julian/Confio')

# Configure Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from blockchain.pysui_client import get_pysui_client

async def inspect_original_cusd():
    """Inspect the original cUSD package to understand its structure"""
    
    ORIGINAL_CUSD_PACKAGE = "0x551a39bd96679261aaf731e880b88fa528b66ee2ef6f0da677bdf0762b907bcf"
    TREASURY_CAP_ID = "0xadbc39527efb7cfc63a5e9102aba7aa0c20f7957d851630a52f98547bc9ab68c"
    
    async with await get_pysui_client() as client:
        try:
            # Get package info
            print(f"Inspecting package: {ORIGINAL_CUSD_PACKAGE}")
            
            # Get all objects related to this package
            print("\n=== Looking for shared objects ===")
            
            # Check for shared objects by looking at recent transactions
            # that might have created PauseState and FreezeRegistry
            
            # First, let's get the TreasuryCap details
            treasury_result = await client.client.get_object(
                TREASURY_CAP_ID,
                {'showContent': True, 'showType': True, 'showOwner': True}
            )
            
            print(f"TreasuryCap details:")
            print(treasury_result.to_dict() if hasattr(treasury_result, 'to_dict') else treasury_result)
            
            # Let's try to find other objects created in the same transaction
            if hasattr(treasury_result, 'data') and hasattr(treasury_result.data, 'previous_transaction'):
                tx_digest = treasury_result.data.previous_transaction
                print(f"\nPrevious transaction: {tx_digest}")
                
                # Get transaction details to see what else was created
                tx_result = await client.get_transaction(tx_digest)
                print(f"Transaction details:")
                print(tx_result)
                
        except Exception as e:
            print(f"Error inspecting package: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(inspect_original_cusd())