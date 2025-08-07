#!/usr/bin/env python
"""
Script to opt the sponsor account into the CONFIO token
"""

import os
import sys
import django
from algosdk import account, mnemonic, transaction
from algosdk.v2client import algod

# Add project to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.conf import settings

def opt_in_sponsor_to_confio():
    """Opt in the sponsor account to CONFIO token"""
    
    # Get sponsor details
    sponsor_address = settings.BLOCKCHAIN_CONFIG.get('ALGORAND_SPONSOR_ADDRESS')
    sponsor_mnemonic = settings.BLOCKCHAIN_CONFIG.get('ALGORAND_SPONSOR_MNEMONIC')
    
    if not sponsor_address or not sponsor_mnemonic:
        print("ERROR: Sponsor address or mnemonic not configured")
        return
    
    print(f"Sponsor address: {sponsor_address}")
    
    # Connect to Algorand
    algod_client = algod.AlgodClient('', 'https://testnet-api.algonode.cloud')
    
    # Check current status
    account_info = algod_client.account_info(sponsor_address)
    print(f"Current balance: {account_info['amount'] / 1_000_000} ALGO")
    
    # Check if already opted in
    asset_id = 743890784  # CONFIO token
    assets = account_info.get('assets', [])
    
    if any(asset['asset-id'] == asset_id for asset in assets):
        print(f"✓ Sponsor is already opted into CONFIO (asset {asset_id})")
        return
    
    print(f"Sponsor needs to opt into CONFIO (asset {asset_id})")
    
    # Get suggested params
    params = algod_client.suggested_params()
    
    # Create opt-in transaction (0 amount transfer to self)
    opt_in_txn = transaction.AssetTransferTxn(
        sender=sponsor_address,
        sp=params,
        receiver=sponsor_address,
        amt=0,
        index=asset_id
    )
    
    # Sign the transaction
    private_key = mnemonic.to_private_key(sponsor_mnemonic)
    signed_txn = opt_in_txn.sign(private_key)
    
    # Submit the transaction
    try:
        tx_id = algod_client.send_transaction(signed_txn)
        print(f"Opt-in transaction submitted: {tx_id}")
        
        # Wait for confirmation
        confirmed_txn = transaction.wait_for_confirmation(algod_client, tx_id, 4)
        print(f"✓ Opt-in confirmed in round {confirmed_txn['confirmed-round']}")
        print(f"Transaction ID: {tx_id}")
        print(f"View on AlgoExplorer: https://testnet.algoexplorer.io/tx/{tx_id}")
        
        # Verify opt-in
        account_info = algod_client.account_info(sponsor_address)
        assets = account_info.get('assets', [])
        if any(asset['asset-id'] == asset_id for asset in assets):
            print(f"✓ SUCCESS: Sponsor is now opted into CONFIO")
            asset_info = next(a for a in assets if a['asset-id'] == asset_id)
            print(f"  Balance: {asset_info['amount']} CONFIO")
        else:
            print("⚠ Warning: Opt-in completed but asset not showing in account")
            
    except Exception as e:
        print(f"✗ Error submitting opt-in transaction: {e}")

if __name__ == "__main__":
    opt_in_sponsor_to_confio()