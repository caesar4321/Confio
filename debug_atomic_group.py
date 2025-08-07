#!/usr/bin/env python
"""
Debug atomic group transaction issues
"""

import os
import sys
import django
import asyncio
import base64
import msgpack
from algosdk import account, mnemonic, transaction, encoding
from algosdk.v2client import algod

# Add project to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_sponsor_service import algorand_sponsor_service

async def debug_atomic_group():
    """Debug the atomic group transaction flow"""
    
    # Create a test account
    test_private_key, test_address = account.generate_account()
    
    print("=" * 60)
    print("DEBUG: Atomic Group Transaction Flow")
    print("=" * 60)
    
    print(f"\n1. Accounts:")
    print(f"   Test address: {test_address}")
    print(f"   Sponsor address: {algorand_sponsor_service.sponsor_address}")
    
    # Check sponsor balance and asset opt-ins
    client = algod.AlgodClient('', 'https://testnet-api.algonode.cloud')
    
    print(f"\n2. Sponsor Account Status:")
    try:
        sponsor_info = client.account_info(algorand_sponsor_service.sponsor_address)
        print(f"   Balance: {sponsor_info['amount'] / 1_000_000} ALGO")
        print(f"   Assets opted in: {len(sponsor_info.get('assets', []))}")
        
        # Check if sponsor is opted into CONFIO token
        asset_id = 743890784
        assets = sponsor_info.get('assets', [])
        confio_opted_in = any(asset['asset-id'] == asset_id for asset in assets)
        print(f"   Opted into CONFIO (743890784): {confio_opted_in}")
        
        if not confio_opted_in:
            print("   WARNING: Sponsor is not opted into CONFIO token!")
    except Exception as e:
        print(f"   Error checking sponsor: {e}")
    
    print(f"\n3. Creating sponsored opt-in transaction...")
    opt_in_result = await algorand_sponsor_service.create_sponsored_opt_in(
        user_address=test_address,
        asset_id=asset_id
    )
    
    if not opt_in_result['success']:
        print(f"   FAILED: {opt_in_result['error']}")
        return
    
    print(f"   ✓ Created opt-in transaction")
    print(f"   Group ID: {opt_in_result['group_id']}")
    
    # Decode and inspect the user transaction
    print(f"\n4. Inspecting User Transaction:")
    user_txn_b64 = opt_in_result['user_transaction']
    user_txn_bytes = base64.b64decode(user_txn_b64)
    user_txn_dict = msgpack.unpackb(user_txn_bytes, raw=False)
    
    print(f"   Transaction type: {user_txn_dict.get('type')}")
    print(f"   Sender: {user_txn_dict.get('snd', b'').hex()[:20]}...")
    print(f"   Group ID in transaction: {user_txn_dict.get('grp', b'').hex() if 'grp' in user_txn_dict else 'NOT SET'}")
    print(f"   Fee: {user_txn_dict.get('fee', 0)}")
    
    # Decode and inspect the sponsor transaction
    print(f"\n5. Inspecting Sponsor Transaction:")
    sponsor_txn_b64 = opt_in_result['sponsor_transaction']
    sponsor_txn_bytes = base64.b64decode(sponsor_txn_b64)
    
    # The sponsor transaction is already signed, so it's wrapped in a signed transaction structure
    sponsor_signed_dict = msgpack.unpackb(sponsor_txn_bytes, raw=False)
    
    if 'txn' in sponsor_signed_dict:
        sponsor_txn_dict = sponsor_signed_dict['txn']
        print(f"   Transaction type: {sponsor_txn_dict.get('type')}")
        print(f"   Sender: {sponsor_txn_dict.get('snd', b'').hex()[:20]}...")
        print(f"   Group ID in transaction: {sponsor_txn_dict.get('grp', b'').hex() if 'grp' in sponsor_txn_dict else 'NOT SET'}")
        print(f"   Fee: {sponsor_txn_dict.get('fee', 0)}")
        print(f"   Has signature: {'sig' in sponsor_signed_dict}")
    else:
        print(f"   ERROR: Sponsor transaction doesn't have expected structure")
        print(f"   Keys: {list(sponsor_signed_dict.keys())}")
    
    # Check if group IDs match
    print(f"\n6. Group ID Verification:")
    user_grp = user_txn_dict.get('grp', b'')
    sponsor_grp = sponsor_txn_dict.get('grp', b'') if 'txn' in sponsor_signed_dict else b''
    
    if user_grp and sponsor_grp:
        if user_grp == sponsor_grp:
            print(f"   ✓ Group IDs match: {user_grp.hex()}")
        else:
            print(f"   ✗ Group IDs DO NOT match!")
            print(f"   User: {user_grp.hex()}")
            print(f"   Sponsor: {sponsor_grp.hex()}")
    else:
        print(f"   ✗ Missing group IDs!")
    
    # Try signing the user transaction
    print(f"\n7. Signing User Transaction:")
    try:
        # Recreate the transaction object
        txn_obj = encoding.msgpack_decode(user_txn_b64)
        print(f"   Decoded transaction type: {type(txn_obj).__name__}")
        
        # Sign it
        signed_txn = txn_obj.sign(test_private_key)
        signed_txn_b64 = encoding.msgpack_encode(signed_txn)
        print(f"   ✓ Signed successfully")
        print(f"   Signed transaction base64 length: {len(signed_txn_b64)}")
        
        # Decode to verify structure
        signed_bytes = base64.b64decode(signed_txn_b64)
        signed_dict = msgpack.unpackb(signed_bytes, raw=False)
        print(f"   Signed transaction has keys: {list(signed_dict.keys())}")
        if 'txn' in signed_dict:
            print(f"   Transaction group ID after signing: {signed_dict['txn'].get('grp', b'').hex() if 'grp' in signed_dict['txn'] else 'NOT SET'}")
    except Exception as e:
        print(f"   ✗ Signing failed: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("SUMMARY:")
    if confio_opted_in and user_grp == sponsor_grp and user_grp:
        print("✓ Setup looks correct. The issue might be with the network or final encoding.")
    else:
        if not confio_opted_in:
            print("✗ Sponsor needs to opt into CONFIO token first")
        if not user_grp or not sponsor_grp:
            print("✗ Group IDs are not properly set on transactions")
        if user_grp != sponsor_grp:
            print("✗ Group IDs don't match between transactions")

if __name__ == "__main__":
    asyncio.run(debug_atomic_group())