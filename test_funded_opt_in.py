#!/usr/bin/env python
"""
Test sponsored opt-in with the funded test account
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

async def test_funded_opt_in():
    """Test with the account we just funded"""
    
    # Use the account we just funded
    test_mnemonic = "quantum there flavor biology family kiss sweet flag pyramid audit under slender small brush sibling world similar bubble enable roof recall include rally above gold"
    test_private_key = mnemonic.to_private_key(test_mnemonic)
    test_address = account.address_from_private_key(test_private_key)
    
    print("=" * 60)
    print("Testing Sponsored Opt-In with Funded Account")
    print("=" * 60)
    
    print(f"\nTest account: {test_address}")
    
    # Connect to Algorand
    client = algod.AlgodClient('', 'https://testnet-api.algonode.cloud')
    
    # Check balance
    info = client.account_info(test_address)
    balance = info['amount'] / 1_000_000
    print(f"Current balance: {balance} ALGO")
    
    # Check if already opted into CONFIO
    asset_id = 743890784  # CONFIO token
    assets = info.get('assets', [])
    if any(a['asset-id'] == asset_id for a in assets):
        print(f"✓ Already opted into CONFIO")
        return
    
    print(f"\nCreating sponsored opt-in for CONFIO (asset {asset_id})...")
    
    # Create sponsored opt-in
    result = await algorand_sponsor_service.create_sponsored_opt_in(
        user_address=test_address,
        asset_id=asset_id
    )
    
    if not result['success']:
        print(f"❌ Failed to create opt-in: {result['error']}")
        return
    
    print("✓ Created sponsored opt-in transaction")
    print(f"  Group ID: {result['group_id']}")
    print(f"  Total fee: {result['total_fee']} microALGO")
    
    # Sign the user transaction
    print("\nSigning user transaction...")
    user_txn_b64 = result['user_transaction']
    
    # Decode and sign
    txn_obj = encoding.msgpack_decode(user_txn_b64)
    print(f"  Transaction type: {type(txn_obj).__name__}")
    
    signed_txn = txn_obj.sign(test_private_key)
    signed_txn_b64 = encoding.msgpack_encode(signed_txn)
    print(f"  ✓ Signed (length: {len(signed_txn_b64)})")
    
    # Submit the group
    print("\nSubmitting atomic group...")
    submit_result = await algorand_sponsor_service.submit_sponsored_group(
        signed_user_txn=signed_txn_b64,
        signed_sponsor_txn=result['sponsor_transaction']
    )
    
    if submit_result['success']:
        print(f"\n✅ SUCCESS! Transaction submitted")
        print(f"   Transaction ID: {submit_result['tx_id']}")
        print(f"   Confirmed round: {submit_result.get('confirmed_round', 'pending')}")
        print(f"   Fees saved: {submit_result['fees_saved']} ALGO")
        print(f"   View on AlgoExplorer: https://testnet.algoexplorer.io/tx/{submit_result['tx_id']}")
        
        # Verify opt-in
        print("\nVerifying opt-in...")
        info = client.account_info(test_address)
        assets = info.get('assets', [])
        confio_asset = next((a for a in assets if a['asset-id'] == asset_id), None)
        if confio_asset:
            print(f"✓ Successfully opted into CONFIO!")
            print(f"  Current CONFIO balance: {confio_asset['amount']}")
    else:
        print(f"\n❌ Failed to submit: {submit_result['error']}")

if __name__ == "__main__":
    asyncio.run(test_funded_opt_in())