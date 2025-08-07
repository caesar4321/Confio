#!/usr/bin/env python
"""
Test with a real funded test account
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

async def test_with_funded_account():
    """Test with an account that has some ALGO"""
    
    # Create a test account
    test_private_key, test_address = account.generate_account()
    test_mnemonic = mnemonic.from_private_key(test_private_key)
    
    print("=" * 60)
    print("Testing Sponsored Opt-In with New Account")
    print("=" * 60)
    
    print(f"\nTest account created:")
    print(f"Address: {test_address}")
    print(f"Mnemonic: {test_mnemonic}")
    
    print("\n⚠️  This account needs to be funded with at least 0.2 ALGO")
    print("   (0.1 ALGO minimum balance + 0.1 ALGO for asset opt-in)")
    
    # Connect to Algorand
    client = algod.AlgodClient('', 'https://testnet-api.algonode.cloud')
    
    # Check balance
    try:
        info = client.account_info(test_address)
        balance = info['amount'] / 1_000_000
        print(f"\nCurrent balance: {balance} ALGO")
        
        if balance < 0.2:
            print("\n❌ Account needs funding!")
            print(f"   Please send at least 0.2 ALGO to: {test_address}")
            print("   You can use the Algorand TestNet dispenser:")
            print("   https://bank.testnet.algorand.network/")
            print(f"\n   Or send from sponsor account using:")
            print(f"   ./myvenv/bin/python -c \"")
            print(f"from algosdk import mnemonic, transaction")
            print(f"from algosdk.v2client import algod")
            print(f"client = algod.AlgodClient('', 'https://testnet-api.algonode.cloud')")
            print(f"# ... send transaction code ...\"")
            return
            
    except Exception as e:
        print(f"Account not found on network (expected for new account): {e}")
        print("\n❌ Account needs to be funded first!")
        print(f"   Please send at least 0.2 ALGO to: {test_address}")
        print("   You can use the Algorand TestNet dispenser:")
        print("   https://bank.testnet.algorand.network/")
        return
    
    print("\n✓ Account has sufficient balance")
    
    # Now test the sponsored opt-in
    print("\nTesting sponsored opt-in...")
    asset_id = 743890784  # CONFIO token
    
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
    
    # Sign the user transaction
    user_txn_b64 = result['user_transaction']
    txn_obj = encoding.msgpack_decode(user_txn_b64)
    signed_txn = txn_obj.sign(test_private_key)
    signed_txn_b64 = encoding.msgpack_encode(signed_txn)
    
    print("✓ Signed user transaction")
    
    # Submit the group
    submit_result = await algorand_sponsor_service.submit_sponsored_group(
        signed_user_txn=signed_txn_b64,
        signed_sponsor_txn=result['sponsor_transaction']
    )
    
    if submit_result['success']:
        print(f"✅ SUCCESS! Transaction submitted")
        print(f"   Transaction ID: {submit_result['tx_id']}")
        print(f"   View on AlgoExplorer: https://testnet.algoexplorer.io/tx/{submit_result['tx_id']}")
        
        # Verify opt-in
        info = client.account_info(test_address)
        assets = info.get('assets', [])
        if any(a['asset-id'] == asset_id for a in assets):
            print(f"✓ Account successfully opted into CONFIO!")
    else:
        print(f"❌ Failed to submit: {submit_result['error']}")

if __name__ == "__main__":
    asyncio.run(test_with_funded_account())