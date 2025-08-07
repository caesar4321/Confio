#!/usr/bin/env python
"""
Test client-side signing simulation for Algorand sponsored transactions
"""

import os
import sys
import django
import asyncio
import base64
import msgpack
from algosdk import account, mnemonic, transaction, encoding
from algosdk.transaction import AssetTransferTxn

# Add project to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_sponsor_service import algorand_sponsor_service

async def test_client_signing():
    """Test the full flow of client-side signing"""
    
    # Create a test account for simulation
    # Generate a random test account
    test_private_key, test_address = account.generate_account()
    test_mnemonic = mnemonic.from_private_key(test_private_key)
    
    print(f"Test address: {test_address}")
    print(f"Sponsor address: {algorand_sponsor_service.sponsor_address}")
    
    # Test asset ID (CONFIO token)
    asset_id = 743890784
    
    print("\n1. Creating sponsored opt-in transaction...")
    opt_in_result = await algorand_sponsor_service.create_sponsored_opt_in(
        user_address=test_address,
        asset_id=asset_id
    )
    
    if not opt_in_result['success']:
        print(f"Failed to create opt-in: {opt_in_result['error']}")
        return
    
    print(f"✓ Created opt-in transaction")
    print(f"  Group ID: {opt_in_result['group_id']}")
    print(f"  Total fee: {opt_in_result['total_fee']} microALGO")
    
    # Simulate client-side signing
    print("\n2. Simulating client-side signing...")
    
    # Get the user transaction (base64 encoded)
    user_txn_b64 = opt_in_result['user_transaction']
    print(f"  User transaction base64 length: {len(user_txn_b64)}")
    
    # Decode the transaction object  
    try:
        # Use algosdk.encoding to decode the msgpack transaction
        # This returns a Transaction object directly
        txn_obj = encoding.msgpack_decode(user_txn_b64)  # Pass base64 directly
        print(f"  ✓ Decoded transaction successfully")
        print(f"  Transaction type:", type(txn_obj).__name__)
        
        # In Python, the sign method returns a SignedTransaction object
        # We need to use encoding.msgpack_encode to get the bytes
        signed_txn = txn_obj.sign(test_private_key)
        
        # Use algosdk encoding to properly encode the signed transaction
        signed_txn_b64 = encoding.msgpack_encode(signed_txn)
        
        print(f"  ✓ Transaction signed successfully")
        print(f"  Signed transaction base64 length: {len(signed_txn_b64)}")
        
    except Exception as e:
        print(f"  ✗ Failed to sign transaction: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Get the sponsor transaction
    sponsor_txn_b64 = opt_in_result['sponsor_transaction']
    print(f"\n  Sponsor transaction base64 length: {len(sponsor_txn_b64)}")
    print(f"  First 50 chars of sponsor txn: {sponsor_txn_b64[:50]}...")
    
    # Check if the sponsor transaction is valid base64
    try:
        test_decode = base64.b64decode(sponsor_txn_b64)
        print(f"  ✓ Sponsor transaction is valid base64, decoded length: {len(test_decode)}")
    except Exception as e:
        print(f"  ✗ Sponsor transaction base64 decode failed: {e}")
        # Try adding padding
        missing_padding = len(sponsor_txn_b64) % 4
        if missing_padding:
            sponsor_txn_b64 += '=' * (4 - missing_padding)
            print(f"  Added padding, new length: {len(sponsor_txn_b64)}")
    
    print("\n3. Submitting signed transaction group...")
    try:
        submit_result = await algorand_sponsor_service.submit_sponsored_group(
            signed_user_txn=signed_txn_b64,  # Use the correctly encoded signed transaction
            signed_sponsor_txn=sponsor_txn_b64
        )
        
        if submit_result['success']:
            print(f"✓ Transaction submitted successfully!")
            print(f"  Transaction ID: {submit_result['tx_id']}")
            print(f"  Confirmed round: {submit_result.get('confirmed_round', 'pending')}")
            print(f"  Fees saved: {submit_result['fees_saved']} ALGO")
        else:
            print(f"✗ Failed to submit: {submit_result['error']}")
            
    except Exception as e:
        print(f"✗ Error submitting transaction: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_client_signing())