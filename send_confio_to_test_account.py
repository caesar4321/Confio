#!/usr/bin/env python
"""
Send some CONFIO tokens to test account for testing transfers
This requires the creator's private key to send tokens
"""

import os
import sys
import django
from algosdk.v2client import algod
from algosdk import mnemonic, transaction
import time

# Add project to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_account_manager import AlgorandAccountManager

def send_confio_to_test():
    """Send CONFIO to test account"""
    
    # Creator mnemonic (you'll need to provide this)
    # This is just a placeholder - replace with actual mnemonic
    creator_mnemonic = os.environ.get('ALGORAND_CREATOR_MNEMONIC', '')
    
    if not creator_mnemonic:
        print("ERROR: Set ALGORAND_CREATOR_MNEMONIC environment variable with the creator's mnemonic")
        print("Example: export ALGORAND_CREATOR_MNEMONIC='word1 word2 ...'")
        return
    
    try:
        creator_private_key = mnemonic.to_private_key(creator_mnemonic)
        creator_address = "KNKFUBM3GHOLF6S7L2O7JU6YDB7PCRV3PKBOBRCABLYHBHXRFXKNDWGAWE"
        
        # Verify the mnemonic matches the expected creator address
        from algosdk import account
        derived_address = account.address_from_private_key(creator_private_key)
        if derived_address != creator_address:
            print(f"ERROR: Mnemonic doesn't match creator address")
            print(f"Expected: {creator_address}")
            print(f"Got: {derived_address}")
            return
            
    except Exception as e:
        print(f"ERROR: Invalid mnemonic: {e}")
        return
    
    # Test account that we want to send CONFIO to
    test_address = "SW3VSGM6DCZEL7WW6LPLTJORGHQD5IMCE4C7IR3WKT5YBCTZABJAGI6D5Q"
    
    # Amount to send (10 CONFIO for testing)
    amount = 10_000_000  # 10 CONFIO with 6 decimals
    
    client = algod.AlgodClient('', 'https://testnet-api.algonode.cloud')
    
    print(f"Sending 10 CONFIO from creator to test account...")
    print(f"From: {creator_address[:10]}...")
    print(f"To: {test_address[:10]}...")
    
    try:
        # Get suggested params
        params = client.suggested_params()
        
        # Create asset transfer transaction
        txn = transaction.AssetTransferTxn(
            sender=creator_address,
            sp=params,
            receiver=test_address,
            amt=amount,
            index=AlgorandAccountManager.CONFIO_ASSET_ID,
            note=b"Test CONFIO allocation"
        )
        
        # Sign transaction
        signed_txn = txn.sign(creator_private_key)
        
        # Submit transaction
        tx_id = client.send_transaction(signed_txn)
        print(f"\nTransaction submitted: {tx_id}")
        print(f"View: https://testnet.algoexplorer.io/tx/{tx_id}")
        
        # Wait for confirmation
        print("\nWaiting for confirmation...")
        confirmed_txn = transaction.wait_for_confirmation(client, tx_id, 4)
        
        print(f"✅ Transaction confirmed in round {confirmed_txn['confirmed-round']}")
        
        # Verify new balance
        test_info = client.account_info(test_address)
        assets = test_info.get('assets', [])
        for asset in assets:
            if asset['asset-id'] == AlgorandAccountManager.CONFIO_ASSET_ID:
                balance = asset['amount'] / 1_000_000
                print(f"\nTest account new CONFIO balance: {balance} CONFIO")
                break
                
    except Exception as e:
        print(f"ERROR sending CONFIO: {e}")

if __name__ == "__main__":
    send_confio_to_test()