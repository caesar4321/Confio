#!/usr/bin/env python3
"""
Update cUSD app sponsor address on testnet to new KMS address

The cUSD app currently has OLD sponsor address (PFFGG...) but we need to update it
to the NEW KMS address (UQ6WZ...) so conversions work properly.
"""

import sys
sys.path.insert(0, '/Users/julian/Confio')

from algosdk.v2client import algod
from algosdk import transaction
from algosdk.abi import Contract, Method
from algosdk.atomic_transaction_composer import (
    AtomicTransactionComposer,
    TransactionWithSigner
)
from blockchain.kms_manager import KMSSigner
import base64

# Testnet configuration
ALGOD_ADDRESS = 'https://testnet-api.4160.nodely.dev'
ALGOD_TOKEN = ''
CUSD_APP_ID = 744368177
ADMIN = 'UQ6WZKLQBQCNAQTOSEWZZXDY376RZTYP2U2ZZT7OIPEGP376HYLTCSL6E4'  # Current admin (KMS-backed)
NEW_SPONSOR = 'UQ6WZKLQBQCNAQTOSEWZZXDY376RZTYP2U2ZZT7OIPEGP376HYLTCSL6E4'  # Update sponsor to same KMS address
KMS_KEY_ALIAS = 'confio-testnet-sponsor'
KMS_REGION = 'eu-central-2'

print('=' * 80)
print('UPDATE CUSD SPONSOR ADDRESS ON TESTNET')
print('=' * 80)
print()
print(f'App ID: {CUSD_APP_ID}')
print(f'Admin: {ADMIN}')
print(f'New Sponsor: {NEW_SPONSOR}')
print()

# Connect
client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

# Get current sponsor
app_info = client.application_info(CUSD_APP_ID)
print('Current global state:')
for item in app_info['params']['global-state']:
    key_b64 = item['key']
    key = base64.b64decode(key_b64).decode('utf-8', errors='ignore')
    if key == 'sponsor_address':
        if item['value']['type'] == 1:  # bytes
            val_hex = base64.b64decode(item['value']['bytes']).hex()
            print(f'  sponsor_address: {val_hex}')
print()

# Confirm
response = input('Type "UPDATE TESTNET" to proceed: ')
if response != 'UPDATE TESTNET':
    print('Cancelled.')
    sys.exit(0)

print()
print('Calling set_sponsor_address...')

# Create KMS signer (this will sign with OLD admin key)
signer = KMSSigner(KMS_KEY_ALIAS, region_name=KMS_REGION)

# Get suggested params
params = client.suggested_params()

# Create app call using ABI
# The set_sponsor_address method takes an abi.Address parameter
from algosdk import encoding

# Decode new sponsor address to bytes
new_sponsor_bytes = encoding.decode_address(NEW_SPONSOR)

# Create app call transaction
txn = transaction.ApplicationCallTxn(
    sender=ADMIN,
    sp=params,
    index=CUSD_APP_ID,
    on_complete=transaction.OnComplete.NoOpOC,
    app_args=[
        bytes.fromhex('be77aae6'),  # Method selector for set_sponsor_address(address)void
        new_sponsor_bytes
    ]
)

# Sign with KMS
print('Signing with KMS...')
signed_txn = signer.sign_transaction(txn)

# Submit
print('Submitting transaction...')
tx_id = client.send_transaction(signed_txn)
print(f'✓ Transaction ID: {tx_id}')

# Wait for confirmation
print('Waiting for confirmation...')
confirmed = transaction.wait_for_confirmation(client, tx_id, 4)
print(f'✓ Confirmed in round {confirmed["confirmed-round"]}')
print()

# Verify update
print('Verifying sponsor address update...')
app_info = client.application_info(CUSD_APP_ID)
for item in app_info['params']['global-state']:
    key_b64 = item['key']
    key = base64.b64decode(key_b64).decode('utf-8', errors='ignore')
    if key == 'sponsor_address':
        if item['value']['type'] == 1:  # bytes
            val_bytes = base64.b64decode(item['value']['bytes'])
            val_address = encoding.encode_address(val_bytes)
            print(f'New sponsor address: {val_address}')
            if val_address == NEW_SPONSOR:
                print('✅ Sponsor address updated successfully!')
            else:
                print(f'⚠️  Warning: Address mismatch!')
                print(f'  Expected: {NEW_SPONSOR}')
                print(f'  Got:      {val_address}')
print()
print(f'View transaction: https://testnet.algoexplorer.io/tx/{tx_id}')
