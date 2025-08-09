#!/usr/bin/env python3
"""
Test specific CONFIO balance that we know exists
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
from django.conf import settings

async def test_specific_confio():
    """Test the specific address we know has 1000 CONFIO"""
    
    # Julian's business account that we distributed 1000 CONFIO to
    test_address = '0x04b06df35ddfa55c5e62c9f1a1cd2c6da36efa1b8c0e80cecd9c6c3e9b7b5b85'
    coin_type = f"{settings.CONFIO_PACKAGE_ID}::confio::CONFIO"
    
    print(f"Testing address: {test_address}")
    print(f"CONFIO coin type: {coin_type}")
    
    async with await get_pysui_client() as client:
        # First, let's see the raw response from get_coin
        from pysui.sui.sui_types.scalars import SuiString
        from pysui.sui.sui_types import SuiAddress
        
        algorand_address = SuiAddress(test_address)
        result = await client.client.get_coin(coin_type=SuiString(coin_type), address=algorand_address, fetch_all=True)
        
        print(f"Raw result type: {type(result)}")
        print(f"Has result_data: {hasattr(result, 'result_data')}")
        
        if result and hasattr(result, 'result_data'):
            print(f"Result data type: {type(result.result_data)}")
            print(f"Result data has 'data': {hasattr(result.result_data, 'data')}")
            
            if hasattr(result.result_data, 'data'):
                print(f"Data length: {len(result.result_data.data)}")
                for i, coin in enumerate(result.result_data.data):
                    print(f"Coin {i}: balance={coin.balance}, type={type(coin)}")
            else:
                print(f"Direct iteration over result_data:")
                try:
                    for i, coin in enumerate(result.result_data):
                        print(f"Coin {i}: balance={getattr(coin, 'balance', 'no balance')}, type={type(coin)}")
                except Exception as e:
                    print(f"Error iterating: {e}")
        
        # Now test our balance method
        balance = await client.get_confio_balance(test_address)
        print(f"Final balance: {balance} CONFIO")

if __name__ == "__main__":
    asyncio.run(test_specific_confio())