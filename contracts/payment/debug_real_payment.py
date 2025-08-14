#!/usr/bin/env python3
"""
Debug script to reproduce the exact failing payment from the app
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algosdk import mnemonic, account, encoding
from algosdk.v2client import algod
from algosdk.transaction import *
from algosdk.abi import Method, Argument, Returns
from algosdk import logic
import base64

# Setup
ALGOD_ADDRESS = 'https://testnet-api.algonode.cloud'
ALGOD_TOKEN = ''
APP_ID = 744223545
CONFIO_ID = 744150851

# The EXACT addresses from the failing transaction
payer_address = 'N3T5WQVBAVMTSIVYNBLIEE4XNFLDYLY3SIIP6B6HENADL6UH7HA56MZSDE'
recipient_address = 'YCV25L4FIZ66N3ZTAWKLREEMOFBBIB3CCV7BJIVBLDJZI2EM6VK6Z4MPEU'

# Get sponsor credentials
sponsor_mnemonic = os.environ.get('ALGORAND_SPONSOR_MNEMONIC')
if not sponsor_mnemonic:
    print("Error: ALGORAND_SPONSOR_MNEMONIC not set")
    sys.exit(1)

sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)
sponsor_address = account.address_from_private_key(sponsor_private_key)

algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
app_address = logic.get_application_address(APP_ID)

print(f'=== Reproducing Exact Failing Transaction ===')
print(f'App ID: {APP_ID}')
print(f'App Address: {app_address}')
print(f'Sponsor: {sponsor_address}')
print(f'Payer: {payer_address}')
print(f'Recipient: {recipient_address}')
print()

# First, check if recipient is opted into CONFIO
try:
    account_info = algod_client.account_info(recipient_address)
    assets = account_info.get('assets', [])
    has_confio = any(a['asset-id'] == CONFIO_ID for a in assets)
    
    if not has_confio:
        print(f'WARNING: Recipient is NOT opted into CONFIO (asset {CONFIO_ID})')
        print(f'The payment will fail when the contract tries to send CONFIO to the recipient.')
        print(f'The recipient must opt-in to CONFIO first.')
        print()
        
        # Show how to opt-in
        print('To opt-in the recipient, they need to execute:')
        print('  1. An AssetTransferTxn with amount=0 to themselves')
        print(f'  2. Asset ID: {CONFIO_ID}')
        print()
    else:
        print(f'✓ Recipient is opted into CONFIO')
        
except Exception as e:
    print(f"Error checking recipient: {e}")

# Check payer balance
try:
    account_info = algod_client.account_info(payer_address)
    assets = account_info.get('assets', [])
    confio_balance = next((a['amount'] for a in assets if a['asset-id'] == CONFIO_ID), 0)
    print(f'Payer CONFIO balance: {confio_balance / 1_000_000} CONFIO')
except Exception as e:
    print(f"Error checking payer: {e}")

print()
print('Building transaction group...')

# Get params
params = algod_client.suggested_params()

# Build the EXACT transaction group structure
transactions = []

# Transaction 0: Payment (sponsor → payer, 0)
sponsor_payment = PaymentTxn(
    sender=sponsor_address,
    sp=params,
    receiver=payer_address,
    amt=0,
    note=b'Payment for invoice 9U4387PF'
)
transactions.append(sponsor_payment)

# Transaction 1: AXFER (payer → app) with 0 fee
asset_params = SuggestedParams(
    fee=0,
    first=params.first,
    last=params.last,
    gh=params.gh,
    gen=params.gen,
    flat_fee=True
)

asset_transfer = AssetTransferTxn(
    sender=payer_address,
    sp=asset_params,
    receiver=app_address,
    amt=4000000,  # 4 CONFIO (exact amount from logs)
    index=CONFIO_ID,
    note=b'Payment for invoice 9U4387PF'
)
transactions.append(asset_transfer)

# Transaction 2: AppCall from sponsor
app_params = SuggestedParams(
    fee=2000,
    first=params.first,
    last=params.last,
    gh=params.gh,
    gen=params.gen,
    flat_fee=True
)

# Create method for ABI
method = Method(
    name='pay_with_confio',
    args=[
        Argument(arg_type='axfer', name='payment'),
        Argument(arg_type='address', name='recipient'),
        Argument(arg_type='string', name='payment_id')
    ],
    returns=Returns(arg_type='void')
)

app_call = ApplicationCallTxn(
    sender=sponsor_address,
    sp=app_params,
    index=APP_ID,
    on_complete=OnComplete.NoOpOC,
    app_args=[
        method.get_selector(),
        (1).to_bytes(1, 'big'),  # Reference to transaction at index 1
        encoding.decode_address(recipient_address),
        b''  # Empty payment_id
    ],
    accounts=[payer_address, recipient_address],
    foreign_assets=[CONFIO_ID]
)
transactions.append(app_call)

# Group the transactions
assign_group_id(transactions)

print('Transaction group built:')
for i, txn in enumerate(transactions):
    print(f'  Txn {i}: {type(txn).__name__}')
    if hasattr(txn, 'sender'):
        print(f'         Sender: {txn.sender}')
    if hasattr(txn, 'receiver'):
        print(f'         Receiver: {txn.receiver}')

print()
print('This script demonstrates the exact transaction structure that is failing.')
print('The error occurs at pc=1360 which is checking:')
print('  Assert(Gtxn[prev_idx].sender == actual_payer)')
print()
print('Where:')
print(f'  prev_idx = 1 (group_index - 1)')
print(f'  Gtxn[1].sender = {payer_address}')
print(f'  actual_payer = Accounts[0] = {payer_address}')
print()
print('These should match, but the assertion is failing.')
print()
print('Possible causes:')
print('1. The recipient is not opted into CONFIO (most likely)')
print('2. There is a bug in the contract logic')
print('3. There is an issue with transaction ordering')