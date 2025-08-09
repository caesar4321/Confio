#!/usr/bin/env python
"""
Send CONFIO tokens from sponsor account to a specific address
"""

import os
import sys
import django
from algosdk.v2client import algod
from algosdk import mnemonic, transaction, account
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from blockchain.algorand_account_manager import AlgorandAccountManager

def send_confio_tokens(recipient_address, amount_confio=100):
    """Send CONFIO from sponsor account to specified address"""
    
    # Get sponsor mnemonic from environment
    sponsor_mnemonic = os.environ.get('ALGORAND_SPONSOR_MNEMONIC', '')
    
    if not sponsor_mnemonic:
        print("ERROR: ALGORAND_SPONSOR_MNEMONIC not found in environment")
        return False
    
    # Clean up the mnemonic (remove quotes if present)
    sponsor_mnemonic = sponsor_mnemonic.strip('"').strip("'")
    
    try:
        sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)
        sponsor_address = account.address_from_private_key(sponsor_private_key)
        
        print(f"Using sponsor account: {sponsor_address[:20]}...")
        
    except Exception as e:
        print(f"ERROR: Invalid mnemonic: {e}")
        return False
    
    # Amount to send (with 6 decimals)
    amount = int(amount_confio * 1_000_000)
    
    client = algod.AlgodClient('', 'https://testnet-api.algonode.cloud')
    
    print(f"Sending {amount_confio} CONFIO tokens")
    print(f"From: {sponsor_address[:30]}...")
    print(f"To: {recipient_address[:30]}...")
    
    try:
        # Check sponsor's CONFIO balance first
        sponsor_info = client.account_info(sponsor_address)
        assets = sponsor_info.get('assets', [])
        sponsor_confio_balance = 0
        
        for asset in assets:
            if asset['asset-id'] == AlgorandAccountManager.CONFIO_ASSET_ID:
                sponsor_confio_balance = asset['amount'] / 1_000_000
                print(f"Sponsor's CONFIO balance: {sponsor_confio_balance} CONFIO")
                break
        
        if sponsor_confio_balance < amount_confio:
            print(f"ERROR: Insufficient CONFIO balance. Need {amount_confio}, have {sponsor_confio_balance}")
            return False
        
        # Get suggested params
        params = client.suggested_params()
        
        # Create asset transfer transaction
        txn = transaction.AssetTransferTxn(
            sender=sponsor_address,
            sp=params,
            receiver=recipient_address,
            amt=amount,
            index=AlgorandAccountManager.CONFIO_ASSET_ID,
            note=f"CONFIO transfer - {amount_confio} tokens".encode()
        )
        
        # Sign transaction
        signed_txn = txn.sign(sponsor_private_key)
        
        # Submit transaction
        tx_id = client.send_transaction(signed_txn)
        print(f"Transaction submitted: {tx_id}")
        print(f"View: https://testnet.algoexplorer.io/tx/{tx_id}")
        
        # Wait for confirmation
        print("Waiting for confirmation...")
        confirmed_txn = transaction.wait_for_confirmation(client, tx_id, 4)
        
        print(f"Transaction confirmed in round {confirmed_txn['confirmed-round']}")
        
        return True
                
    except Exception as e:
        if "asset <" in str(e) and "> missing from" in str(e):
            print(f"ERROR: Recipient needs to opt-in to CONFIO asset first!")
            print(f"Asset ID: {AlgorandAccountManager.CONFIO_ASSET_ID}")
        else:
            print(f"ERROR sending CONFIO: {e}")
        return False

if __name__ == "__main__":
    target_address = "N3T5WQVBAVMTSIVYNBLIEE4XNFLDYLY3SIIP6B6HENADL6UH7HA56MZSDE"
    amount = 100  # Sending 100 CONFIO
    
    print("CONFIO TOKEN TRANSFER")
    print("=" * 50)
    
    success = send_confio_tokens(target_address, amount)
    
    if success:
        print("Transfer completed successfully!")
    else:
        print("Transfer failed.")
    
    print("=" * 50)