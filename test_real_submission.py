#!/usr/bin/env python
"""
Test real submission with the funded account
"""

import os
import sys
import django
import asyncio
import base64
from algosdk import account, mnemonic, transaction, encoding
from algosdk.v2client import algod

# Add project to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_sponsor_service import algorand_sponsor_service

async def test_real_submission():
    """Test with the account that has 0.5 ALGO"""
    
    # This is the account from test_simple_send.py that has 0.5 ALGO
    test_mnemonic = "quantum there flavor biology family kiss sweet flag pyramid audit under slender small brush sibling world similar bubble enable roof recall include rally above gold"
    test_private_key = mnemonic.to_private_key(test_mnemonic)
    test_address = account.address_from_private_key(test_private_key)
    
    print(f"Test account: {test_address}")
    
    # Verify balance
    client = algod.AlgodClient('', 'https://testnet-api.algonode.cloud')
    info = client.account_info(test_address)
    print(f"Balance: {info['amount'] / 1_000_000} ALGO")
    
    # Check if already opted in
    assets = info.get('assets', [])
    if any(a['asset-id'] == 743890784 for a in assets):
        print("Already opted into CONFIO!")
        return
    
    print("\nCreating sponsored opt-in...")
    result = await algorand_sponsor_service.create_sponsored_opt_in(
        user_address=test_address,
        asset_id=743890784
    )
    
    if not result['success']:
        print(f"Failed: {result['error']}")
        return
    
    print("Created successfully")
    print(f"Group ID: {result['group_id']}")
    
    # Sign the user transaction
    print("\nSigning user transaction...")
    user_txn_b64 = result['user_transaction']
    
    # Decode and sign
    txn_obj = encoding.msgpack_decode(user_txn_b64)
    signed_txn = txn_obj.sign(test_private_key)
    signed_txn_b64 = encoding.msgpack_encode(signed_txn)
    
    print(f"Signed transaction length: {len(signed_txn_b64)}")
    
    # Submit
    print("\nSubmitting atomic group...")
    submit_result = await algorand_sponsor_service.submit_sponsored_group(
        signed_user_txn=signed_txn_b64,
        signed_sponsor_txn=result['sponsor_transaction']
    )
    
    if submit_result['success']:
        print(f"✅ SUCCESS!")
        print(f"Transaction ID: {submit_result['tx_id']}")
        print(f"View: https://testnet.algoexplorer.io/tx/{submit_result['tx_id']}")
    else:
        print(f"❌ Failed: {submit_result['error']}")
        
        # Debug: Try submitting just the sponsor transaction alone
        print("\nDebug: Trying to submit sponsor transaction alone...")
        try:
            sponsor_bytes = base64.b64decode(result['sponsor_transaction'])
            tx_id = client.send_raw_transaction(sponsor_bytes)
            print(f"Sponsor transaction alone succeeded: {tx_id}")
        except Exception as e:
            print(f"Sponsor transaction alone failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_real_submission())