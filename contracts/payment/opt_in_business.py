#!/usr/bin/env python3
"""
Script to opt a business account into CONFIO asset
"""

import sys
import os
from algosdk import mnemonic, account
from algosdk.v2client import algod
from algosdk.transaction import AssetTransferTxn, wait_for_confirmation

# Setup
ALGOD_ADDRESS = 'https://testnet-api.algonode.cloud'
ALGOD_TOKEN = ''
CONFIO_ID = 744150851

# Business account that needs to opt-in
business_address = 'YCV25L4FIZ66N3ZTAWKLREEMOFBBIB3CCV7BJIVBLDJZI2EM6VK6Z4MPEU'

print(f'=== CONFIO Asset Opt-In ===')
print(f'Asset ID: {CONFIO_ID}')
print(f'Business Address: {business_address}')
print()

algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

# Check current opt-in status
try:
    account_info = algod_client.account_info(business_address)
    assets = account_info.get('assets', [])
    
    has_confio = any(a['asset-id'] == CONFIO_ID for a in assets)
    
    if has_confio:
        print('✓ Account is already opted into CONFIO')
        confio_balance = next(a['amount'] for a in assets if a['asset-id'] == CONFIO_ID)
        print(f'Current balance: {confio_balance / 1_000_000} CONFIO')
        sys.exit(0)
    else:
        print('✗ Account is NOT opted into CONFIO')
        print(f'Currently opted into {len(assets)} assets')
        
except Exception as e:
    print(f'Error checking account: {e}')
    sys.exit(1)

print()
print('To opt-in, the business account needs to:')
print('1. Sign and send an AssetTransferTxn with:')
print(f'   - Sender: {business_address}')
print(f'   - Receiver: {business_address} (same as sender)')
print(f'   - Asset ID: {CONFIO_ID}')
print('   - Amount: 0')
print('   - Fee: 1000 microAlgos (0.001 ALGO)')
print()
print('This requires the private key for the business account.')
print()
print('If you have the mnemonic for this account, you can set it as an environment variable:')
print('export BUSINESS_MNEMONIC="your twenty five word mnemonic phrase here..."')
print()

# Check if we have the mnemonic
business_mnemonic = os.environ.get('BUSINESS_MNEMONIC')
if business_mnemonic:
    print('Found BUSINESS_MNEMONIC, proceeding with opt-in...')
    
    try:
        # Get private key
        business_private_key = mnemonic.to_private_key(business_mnemonic)
        derived_address = account.address_from_private_key(business_private_key)
        
        if derived_address != business_address:
            print(f'Error: Mnemonic derives to {derived_address}, not {business_address}')
            sys.exit(1)
        
        # Get suggested params
        params = algod_client.suggested_params()
        
        # Create opt-in transaction
        opt_in_txn = AssetTransferTxn(
            sender=business_address,
            sp=params,
            receiver=business_address,  # Send to self for opt-in
            amt=0,  # Zero amount for opt-in
            index=CONFIO_ID
        )
        
        # Sign transaction
        signed_txn = opt_in_txn.sign(business_private_key)
        
        # Send transaction
        print('Sending opt-in transaction...')
        tx_id = algod_client.send_transaction(signed_txn)
        print(f'Transaction sent: {tx_id}')
        
        # Wait for confirmation
        print('Waiting for confirmation...')
        confirmed_txn = wait_for_confirmation(algod_client, tx_id, 10)
        print(f'✓ Opt-in confirmed in round {confirmed_txn.get("confirmed-round", 0)}')
        print()
        print('The business account can now receive CONFIO payments!')
        
    except Exception as e:
        print(f'Error during opt-in: {e}')
        sys.exit(1)
else:
    print('BUSINESS_MNEMONIC not set. Cannot proceed with automatic opt-in.')
    print()
    print('The business account owner needs to opt-in using their wallet app.')
    print('In Pera Wallet or MyAlgo:')
    print('1. Go to the account')
    print('2. Find "Add Asset" or "Opt-In to Asset"')
    print(f'3. Search for asset ID {CONFIO_ID}')
    print('4. Confirm the opt-in transaction')