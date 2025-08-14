#!/usr/bin/env python
"""
Update the payment contract with MBR support
"""
import os
import sys
from algosdk import mnemonic, account
from algosdk.v2client import algod
from algosdk.transaction import ApplicationCallTxn, wait_for_confirmation, OnComplete
from algosdk.abi import Method, Returns

# Setup
ALGOD_ADDRESS = 'https://testnet-api.algonode.cloud'
ALGOD_TOKEN = ''
APP_ID = 744232477

# Get admin mnemonic from env
admin_mnemonic = "<REDACTED_OLD_COMPROMISED_MNEMONIC>"
admin_private_key = mnemonic.to_private_key(admin_mnemonic)
admin_address = account.address_from_private_key(admin_private_key)

print(f'Admin address: {admin_address}')

# Connect to node
algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)

# Read raw TEAL files as text
with open('contracts/payment/approval.teal', 'r') as f:
    approval_teal = f.read()
    
# Compile to bytecode
result = algod_client.compile(approval_teal)
approval_program = result['result']

with open('contracts/payment/clear.teal', 'r') as f:
    clear_teal = f.read()
    
result = algod_client.compile(clear_teal)
clear_program = result['result']

import base64
approval_bytes = base64.b64decode(approval_program)
clear_bytes = base64.b64decode(clear_program)

print(f'Approval size: {len(approval_bytes)} bytes')
print(f'Clear size: {len(clear_bytes)} bytes')

# Create update transaction with ABI method call
params = algod_client.suggested_params()

# Define the update method
update_method = Method(
    name="update",
    args=[],
    returns=Returns(arg_type="void")
)

# Get the method selector
selector = update_method.get_selector()

# Create update app call with new bytecode
update_txn = ApplicationCallTxn(
    sender=admin_address,
    sp=params,
    index=APP_ID,
    on_complete=OnComplete.UpdateApplicationOC,
    approval_program=approval_bytes,
    clear_program=clear_bytes,
    app_args=[selector]
)

# Sign and send
signed_txn = update_txn.sign(admin_private_key)
tx_id = algod_client.send_transaction(signed_txn)

print(f'Update transaction sent: {tx_id}')

# Wait for confirmation
confirmed_txn = wait_for_confirmation(algod_client, tx_id, 10)
print(f'Contract updated in round {confirmed_txn.get("confirmed-round", 0)}')