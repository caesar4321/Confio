#!/usr/bin/env python
"""
Send CONFIO tokens to a specific address
"""

import os
import sys
import django
from algosdk.v2client import algod
from algosdk import mnemonic, transaction, account
import time

# Add project to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_account_manager import AlgorandAccountManager

def send_confio_to_address(recipient_address, amount_confio=10):
    """Send CONFIO to specified address"""
    
    # Creator mnemonic (you'll need to provide this)
    creator_mnemonic = os.environ.get('ALGORAND_CREATOR_MNEMONIC', '')
    
    if not creator_mnemonic:
        print("ERROR: Set ALGORAND_CREATOR_MNEMONIC environment variable with the creator's mnemonic")
        print("Example: export ALGORAND_CREATOR_MNEMONIC='word1 word2 ...'")
        return False
    
    try:
        creator_private_key = mnemonic.to_private_key(creator_mnemonic)
        creator_address = "KNKFUBM3GHOLF6S7L2O7JU6YDB7PCRV3PKBOBRCABLYHBHXRFXKNDWGAWE"
        
        # Verify the mnemonic matches the expected creator address
        derived_address = account.address_from_private_key(creator_private_key)
        if derived_address != creator_address:
            print(f"ERROR: Mnemonic doesn't match creator address")
            print(f"Expected: {creator_address}")
            print(f"Got: {derived_address}")
            return False
            
    except Exception as e:
        print(f"ERROR: Invalid mnemonic: {e}")
        return False
    
    # Amount to send (with 6 decimals)
    amount = int(amount_confio * 1_000_000)
    
    client = algod.AlgodClient('', 'https://testnet-api.algonode.cloud')
    
    print(f"\n📤 Sending {amount_confio} CONFIO tokens")
    print(f"From: {creator_address[:20]}...")
    print(f"To: {recipient_address[:20]}...")
    
    try:
        # First check if recipient has opted into CONFIO
        recipient_info = client.account_info(recipient_address)
        assets = recipient_info.get('assets', [])
        opted_in = any(asset['asset-id'] == AlgorandAccountManager.CONFIO_ASSET_ID for asset in assets)
        
        if not opted_in:
            print(f"\n⚠️  Recipient needs to opt-in to CONFIO asset (ID: {AlgorandAccountManager.CONFIO_ASSET_ID})")
            print("They need to send a 0-amount transaction to themselves first")
            return False
        
        # Get suggested params
        params = client.suggested_params()
        
        # Create asset transfer transaction
        txn = transaction.AssetTransferTxn(
            sender=creator_address,
            sp=params,
            receiver=recipient_address,
            amt=amount,
            index=AlgorandAccountManager.CONFIO_ASSET_ID,
            note=f"CONFIO transfer - {amount_confio} tokens".encode()
        )
        
        # Sign transaction
        signed_txn = txn.sign(creator_private_key)
        
        # Submit transaction
        tx_id = client.send_transaction(signed_txn)
        print(f"\n✅ Transaction submitted: {tx_id}")
        print(f"📊 View: https://testnet.algoexplorer.io/tx/{tx_id}")
        
        # Wait for confirmation
        print("\n⏳ Waiting for confirmation...")
        confirmed_txn = transaction.wait_for_confirmation(client, tx_id, 4)
        
        print(f"✅ Transaction confirmed in round {confirmed_txn['confirmed-round']}")
        
        # Verify new balance
        recipient_info = client.account_info(recipient_address)
        assets = recipient_info.get('assets', [])
        for asset in assets:
            if asset['asset-id'] == AlgorandAccountManager.CONFIO_ASSET_ID:
                balance = asset['amount'] / 1_000_000
                print(f"\n💰 Recipient's new CONFIO balance: {balance} CONFIO")
                break
        
        return True
                
    except Exception as e:
        print(f"❌ ERROR sending CONFIO: {e}")
        return False

if __name__ == "__main__":
    # The address you want to send to
    target_address = "N3T5WQVBAVMTSIVYNBLIEE4XNFLDYLY3SIIP6B6HENADL6UH7HA56MZSDE"
    
    # Amount to send (in CONFIO)
    amount = 100  # Sending 100 CONFIO
    
    success = send_confio_to_address(target_address, amount)
    
    if success:
        print("\n🎉 Transfer completed successfully!")
    else:
        print("\n❌ Transfer failed. Please check the errors above.")