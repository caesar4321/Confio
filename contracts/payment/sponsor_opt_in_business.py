#!/usr/bin/env python3
"""
Direct opt-in for business account using sponsor funds
This is a temporary solution for testing - the sponsor pays the opt-in fees
"""

import sys
import os
from algosdk import mnemonic, account
from algosdk.v2client import algod
from algosdk.transaction import AssetTransferTxn, PaymentTxn, wait_for_confirmation

# Setup
ALGOD_ADDRESS = 'https://testnet-api.algonode.cloud'
ALGOD_TOKEN = ''
CONFIO_ID = 744150851
CUSD_ID = 744192921

# Business account that needs opt-in
business_address = 'YCV25L4FIZ66N3ZTAWKLREEMOFBBIB3CCV7BJIVBLDJZI2EM6VK6Z4MPEU'

print('=== Sponsor-Funded Business Account Opt-In ===')
print(f'Business Address: {business_address}')
print()

# Get sponsor mnemonic from environment
sponsor_mnemonic = os.environ.get('ALGORAND_SPONSOR_MNEMONIC')
if not sponsor_mnemonic:
    print('Error: ALGORAND_SPONSOR_MNEMONIC not set')
    sys.exit(1)

sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)
sponsor_address = account.address_from_private_key(sponsor_private_key)

print(f'Sponsor Address: {sponsor_address}')

algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

# Check sponsor balance
sponsor_info = algod_client.account_info(sponsor_address)
sponsor_balance = sponsor_info['amount'] / 1_000_000
print(f'Sponsor Balance: {sponsor_balance} ALGO')

if sponsor_balance < 1:
    print('Warning: Sponsor balance is low!')

print()

# Check current opt-in status
try:
    account_info = algod_client.account_info(business_address)
    assets = account_info.get('assets', [])
    algo_balance = account_info.get('amount', 0) / 1_000_000
    
    print(f'Business ALGO Balance: {algo_balance} ALGO')
    
    has_confio = any(a['asset-id'] == CONFIO_ID for a in assets)
    has_cusd = any(a['asset-id'] == CUSD_ID for a in assets)
    
    print('Current opt-in status:')
    print(f'  CONFIO: {"✓ Already opted in" if has_confio else "✗ Not opted in"}')
    print(f'  cUSD: {"✓ Already opted in" if has_cusd else "✗ Not opted in"}')
    print()
    
except Exception as e:
    print(f'Error checking account: {e}')
    sys.exit(1)

# First, fund the business account with enough ALGO for opt-ins if needed
min_balance_for_opt_ins = 0.3  # Need 0.2 for 2 opt-ins + 0.1 buffer
if algo_balance < min_balance_for_opt_ins:
    print(f'Business account needs funding. Sending {min_balance_for_opt_ins} ALGO...')
    
    params = algod_client.suggested_params()
    
    funding_txn = PaymentTxn(
        sender=sponsor_address,
        sp=params,
        receiver=business_address,
        amt=int(min_balance_for_opt_ins * 1_000_000),
        note=b"Funding for asset opt-ins"
    )
    
    signed_funding = funding_txn.sign(sponsor_private_key)
    
    try:
        tx_id = algod_client.send_transaction(signed_funding)
        print(f'Funding transaction sent: {tx_id}')
        
        confirmed_txn = wait_for_confirmation(algod_client, tx_id, 10)
        print(f'✓ Funding confirmed in round {confirmed_txn.get("confirmed-round", 0)}')
        print()
    except Exception as e:
        print(f'Error funding account: {e}')
        sys.exit(1)

print('Note: The business account owner needs to opt-in to the assets themselves.')
print('This can be done through:')
print()
print('1. Their wallet app (Pera, MyAlgo, etc.) by adding these assets:')
print(f'   - CONFIO (Asset ID: {CONFIO_ID})')
print(f'   - cUSD (Asset ID: {CUSD_ID})')
print()
print('2. Or if they have their mnemonic, run:')
print('   export BUSINESS_MNEMONIC="their mnemonic here"')
print('   python manual_business_opt_in.py')
print()
print('The business account now has sufficient ALGO balance to perform the opt-ins.')