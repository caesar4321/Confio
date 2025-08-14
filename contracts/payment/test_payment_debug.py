#!/usr/bin/env python3
"""
Debug script to test payment contract transactions
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

# Get sponsor credentials
sponsor_mnemonic = os.environ.get('ALGORAND_SPONSOR_MNEMONIC')
if not sponsor_mnemonic:
    print("Error: ALGORAND_SPONSOR_MNEMONIC not set")
    sys.exit(1)

sponsor_private_key = mnemonic.to_private_key(sponsor_mnemonic)
sponsor_address = account.address_from_private_key(sponsor_private_key)

# Test account (use sponsor as payer for simplicity)
test_payer = sponsor_address
# Use a different address to avoid self-payment prevention
test_recipient = 'HZ57J3K46JIJXILONBBZOHX6BKPXEM2VVXNRFSUED6DKFD5ZD24PMJ3MVA'

algod_client = algod.AlgodClient(ALGOD_TOKEN, ALGOD_ADDRESS)
app_address = logic.get_application_address(APP_ID)

print(f'App ID: {APP_ID}')
print(f'App Address: {app_address}')
print(f'Sponsor: {sponsor_address}')
print(f'Test Payer: {test_payer}')
print(f'Test Recipient: {test_recipient}')

# Check payer has CONFIO
try:
    account_info = algod_client.account_info(test_payer)
    assets = account_info.get('assets', [])
    confio_balance = next((a['amount'] for a in assets if a['asset-id'] == CONFIO_ID), 0)
    print(f'Payer CONFIO balance: {confio_balance / 1_000_000} CONFIO')
    
    if confio_balance == 0:
        print("Error: Payer has no CONFIO tokens")
        sys.exit(1)
except Exception as e:
    print(f"Error checking balance: {e}")
    sys.exit(1)

# Get params
params = algod_client.suggested_params()

# Build sponsored payment group
transactions = []

# Transaction 0: Payment (sponsor → payer, 0)
sponsor_payment = PaymentTxn(
    sender=sponsor_address,
    sp=params,
    receiver=test_payer,
    amt=0
)
transactions.append(sponsor_payment)
print(f"\nTxn 0 built: Payment from {sponsor_address[:10]}... to {test_payer[:10]}...")

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
    sender=test_payer,
    sp=asset_params,
    receiver=app_address,
    amt=100000,  # 0.1 CONFIO
    index=CONFIO_ID
)
transactions.append(asset_transfer)
print(f"Txn 1 built: AssetTransfer from {test_payer[:10]}... to {app_address[:10]}...")

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

# Build app args
app_args = [
    method.get_selector(),
    (1).to_bytes(1, 'big'),  # Reference to transaction at index 1
    encoding.decode_address(test_recipient),
    b''  # Empty payment_id
]

print(f"\nApp args:")
for i, arg in enumerate(app_args):
    if isinstance(arg, bytes):
        print(f"  Arg {i}: {arg.hex()[:16]}... (len={len(arg)})")

app_call = ApplicationCallTxn(
    sender=sponsor_address,
    sp=app_params,
    index=APP_ID,
    on_complete=OnComplete.NoOpOC,
    app_args=app_args,
    accounts=[test_payer, test_recipient],
    foreign_assets=[CONFIO_ID]
)
transactions.append(app_call)
print(f"Txn 2 built: ApplicationCall from {sponsor_address[:10]}...")

# Group the transactions
assign_group_id(transactions)
group_id = base64.b64encode(transactions[0].group).decode()
print(f"\nGroup ID: {group_id}")

# Sign transactions
print(f"\nSigning transactions...")
signed_txns = []

# Sign all with sponsor key (in real scenario, user would sign txn 1)
for i, txn in enumerate(transactions):
    signed_txn = txn.sign(sponsor_private_key)
    signed_txns.append(signed_txn)
    print(f"  Txn {i} signed")

# Try to submit
print(f"\nSubmitting to network...")
try:
    tx_id = algod_client.send_transactions(signed_txns)
    print(f"✓ Success! Transaction ID: {tx_id}")
    
    # Wait for confirmation
    from algosdk.transaction import wait_for_confirmation
    confirmed_txn = wait_for_confirmation(algod_client, tx_id, 10)
    print(f"✓ Confirmed in round {confirmed_txn.get('confirmed-round', 0)}")
    
except Exception as e:
    print(f"✗ Error: {e}")
    
    # Try to extract more details
    if "logic eval error" in str(e):
        import re
        match = re.search(r'pc=(\d+)', str(e))
        if match:
            pc = int(match.group(1))
            print(f"\nDebug: Failed at program counter {pc}")
            
            # Try to map to approximate line in TEAL
            with open('approval_debug.teal', 'r') as f:
                lines = f.readlines()
                print(f"Check TEAL around this area for debugging")