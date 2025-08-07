#!/usr/bin/env python
"""
Test sponsored CONFIO transfers using the same principles as opt-in
"""

import os
import sys
import django
import asyncio
import base64
from decimal import Decimal
from algosdk import account, mnemonic, encoding
from algosdk.v2client import algod
import nacl.signing

# Add project to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_sponsor_service import algorand_sponsor_service
from blockchain.algorand_account_manager import AlgorandAccountManager

async def test_sponsored_transfer():
    """Test CONFIO transfer with sponsorship"""
    
    # This is the test account that has 0.5 ALGO and is already opted into CONFIO
    test_mnemonic = "quantum there flavor biology family kiss sweet flag pyramid audit under slender small brush sibling world similar bubble enable roof recall include rally above gold"
    test_private_key = mnemonic.to_private_key(test_mnemonic)
    test_address = account.address_from_private_key(test_private_key)
    
    # Recipient address (can be any valid Algorand address)
    # Using a known TestNet address
    recipient = "7ZUECA7HFLZTXENRV24SHLU4AVPUTMTTDUFUBNBD64C73F3UHRTHAIOF6Q"
    
    print(f"Sender: {test_address}")
    print(f"Recipient: {recipient}")
    
    # Verify balance
    client = algod.AlgodClient('', 'https://testnet-api.algonode.cloud')
    info = client.account_info(test_address)
    print(f"ALGO balance: {info['amount'] / 1_000_000} ALGO")
    
    # Check CONFIO balance
    assets = info.get('assets', [])
    confio_balance = 0
    for asset in assets:
        if asset['asset-id'] == AlgorandAccountManager.CONFIO_ASSET_ID:
            confio_balance = asset['amount'] / 1_000_000  # CONFIO has 6 decimals
            print(f"CONFIO balance: {confio_balance} CONFIO")
            break
    
    if confio_balance == 0:
        print("No CONFIO balance available for transfer")
        return
    
    # Amount to transfer (0.01 CONFIO for testing)
    transfer_amount = Decimal('0.01')
    print(f"\nTransferring {transfer_amount} CONFIO...")
    
    # Step 1: Create sponsored transfer
    print("\n1. Creating sponsored transfer...")
    result = await algorand_sponsor_service.create_sponsored_transfer(
        sender=test_address,
        recipient=recipient,
        amount=transfer_amount,
        asset_id=AlgorandAccountManager.CONFIO_ASSET_ID,
        note="Test CONFIO transfer"
    )
    
    if not result['success']:
        print(f"Failed to create transfer: {result['error']}")
        return
    
    print(f"   Group ID: {result['group_id']}")
    print(f"   Total fee: {result['total_fee']} microALGO")
    
    # Step 2: Sign user transaction using raw nacl (same approach as opt-in)
    print("\n2. Signing user transaction...")
    user_txn_b64 = result['user_transaction']
    
    # Decode the unsigned transaction
    import msgpack
    user_txn_bytes = base64.b64decode(user_txn_b64)
    txn_obj = msgpack.unpackb(user_txn_bytes)
    
    # Sign using raw nacl approach
    tx_type_bytes = b'TX'
    bytes_to_sign = tx_type_bytes + user_txn_bytes
    
    # Convert private key to nacl signing key
    signing_key = nacl.signing.SigningKey(test_private_key[:32])
    signature = signing_key.sign(bytes_to_sign).signature
    
    # Create signed transaction structure
    signed_txn = {
        b'sig': signature,
        b'txn': txn_obj
    }
    
    # Encode the signed transaction
    signed_txn_bytes = msgpack.packb(signed_txn)
    signed_txn_b64 = base64.b64encode(signed_txn_bytes).decode('utf-8')
    
    print(f"   Signed transaction length: {len(signed_txn_b64)} chars")
    
    # Step 3: Submit the atomic group
    print("\n3. Submitting atomic group...")
    submit_result = await algorand_sponsor_service.submit_sponsored_group(
        signed_user_txn=signed_txn_b64,
        signed_sponsor_txn=result['sponsor_transaction']
    )
    
    if submit_result['success']:
        print(f"\n✅ SUCCESS! CONFIO transfer completed")
        print(f"   Transaction ID: {submit_result['tx_id']}")
        print(f"   Confirmed round: {submit_result['confirmed_round']}")
        print(f"   Fees saved: {submit_result['fees_saved']} ALGO")
        print(f"\n   View on AlgoExplorer:")
        print(f"   https://testnet.algoexplorer.io/tx/{submit_result['tx_id']}")
        
        # Verify new balance
        print("\n4. Verifying new balance...")
        info = client.account_info(test_address)
        assets = info.get('assets', [])
        for asset in assets:
            if asset['asset-id'] == AlgorandAccountManager.CONFIO_ASSET_ID:
                new_balance = asset['amount'] / 1_000_000
                print(f"   New CONFIO balance: {new_balance} CONFIO")
                print(f"   Change: {new_balance - confio_balance} CONFIO")
                break
                
    else:
        print(f"\n❌ Failed to submit transfer: {submit_result['error']}")

if __name__ == "__main__":
    asyncio.run(test_sponsored_transfer())