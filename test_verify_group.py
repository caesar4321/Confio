#!/usr/bin/env python
"""
Verify the atomic group is properly formed
"""

import os
import sys
import django
import asyncio
import base64
import msgpack
from algosdk import encoding
from algosdk.v2client import algod

# Add project to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_sponsor_service import algorand_sponsor_service

async def verify_group_formation():
    """Verify that the atomic group is properly formed"""
    
    # Use a real test account that exists on TestNet
    test_address = "XTITQDJSETDOQG3WMSDKE7QPPAX22ZMDX6PZ5B43E4JCFTEBPUJGDY2RGQ"
    
    print("Creating sponsored opt-in transaction...")
    result = await algorand_sponsor_service.create_sponsored_opt_in(
        user_address=test_address,
        asset_id=743890784
    )
    
    if not result['success']:
        print(f"Failed: {result['error']}")
        return
    
    print("\n1. Analyzing User Transaction:")
    user_txn_b64 = result['user_transaction']
    user_txn_bytes = base64.b64decode(user_txn_b64)
    user_txn_dict = msgpack.unpackb(user_txn_bytes, raw=False)
    
    print(f"   Type: {user_txn_dict.get('type')}")
    print(f"   Has group: {'grp' in user_txn_dict}")
    if 'grp' in user_txn_dict:
        print(f"   Group ID: {user_txn_dict['grp'].hex()}")
    
    print("\n2. Analyzing Sponsor Transaction:")
    sponsor_txn_b64 = result['sponsor_transaction']
    sponsor_txn_bytes = base64.b64decode(sponsor_txn_b64)
    sponsor_signed_dict = msgpack.unpackb(sponsor_txn_bytes, raw=False)
    
    print(f"   Is signed: {'sig' in sponsor_signed_dict}")
    if 'txn' in sponsor_signed_dict:
        sponsor_txn_dict = sponsor_signed_dict['txn']
        print(f"   Type: {sponsor_txn_dict.get('type')}")
        print(f"   Has group: {'grp' in sponsor_txn_dict}")
        if 'grp' in sponsor_txn_dict:
            print(f"   Group ID: {sponsor_txn_dict['grp'].hex()}")
    
    print("\n3. Testing concatenation:")
    # This is what happens when we submit
    combined = user_txn_bytes + sponsor_txn_bytes  # User transaction is unsigned at this point
    print(f"   Combined length: {len(combined)}")
    print(f"   First 10 bytes: {combined[:10].hex()}")
    
    # Try to decode as msgpack
    print("\n4. Testing msgpack decode of combined:")
    try:
        # This should fail because it's two separate msgpack objects
        decoded = msgpack.unpackb(combined, raw=False)
        print(f"   Decoded successfully (unexpected!): {type(decoded)}")
    except Exception as e:
        print(f"   Failed as expected: {e}")
        print("   This is normal - atomic groups are concatenated bytes, not a single msgpack object")
    
    print("\n5. Simulating what the network expects:")
    print("   For atomic groups, Algorand expects concatenated signed transaction bytes")
    print("   Each transaction should be a complete signed transaction msgpack object")
    print("   The network will parse them sequentially")
    
    # Check if the account exists and has balance
    client = algod.AlgodClient('', 'https://testnet-api.algonode.cloud')
    try:
        info = client.account_info(test_address)
        balance = info['amount'] / 1_000_000
        print(f"\n6. Account status:")
        print(f"   Address: {test_address}")
        print(f"   Balance: {balance} ALGO")
        print(f"   Assets: {len(info.get('assets', []))}")
        
        # Check if already opted into CONFIO
        assets = info.get('assets', [])
        opted_in = any(a['asset-id'] == 743890784 for a in assets)
        print(f"   Already opted into CONFIO: {opted_in}")
    except Exception as e:
        print(f"\n6. Account check failed: {e}")

if __name__ == "__main__":
    asyncio.run(verify_group_formation())