#!/usr/bin/env python3
"""Deploy the fixed rewards contract with proper initialization"""

from algosdk.v2client import algod
from algosdk import account, mnemonic, transaction
import base64

# Setup
algod_address = "https://testnet-api.4160.nodely.dev"
algod_token = ""
admin_mnemonic = "<REDACTED_OLD_COMPROMISED_MNEMONIC>"

client = algod.AlgodClient(algod_token, algod_address)
admin_private = mnemonic.to_private_key(admin_mnemonic)
admin_addr = account.address_from_private_key(admin_private)

confio_asset_id = 749148838

print("=== Deploying Fixed Rewards Contract ===")
print(f"Admin: {admin_addr}")
print()

# Read compiled TEAL
with open('/Users/julian/Confio/contracts/rewards/approval.teal', 'r') as f:
    approval_teal = f.read()

with open('/Users/julian/Confio/contracts/rewards/clear.teal', 'r') as f:
    clear_teal = f.read()

# Compile programs
approval_result = client.compile(approval_teal)
approval_binary = base64.b64decode(approval_result['result'])

clear_result = client.compile(clear_teal)
clear_binary = base64.b64decode(clear_result['result'])

print("✓ Programs compiled")

# Create application
params = client.suggested_params()

# Global schema: 14 uints, 2 bytes
global_schema = transaction.StateSchema(num_uints=14, num_byte_slices=2)
# Local schema: 0 (no local state)
local_schema = transaction.StateSchema(num_uints=0, num_byte_slices=0)

# App args for creation
# app_args[0]: CONFIO asset ID as uint64 bytes
# app_args[1]: admin address (32 bytes)
# app_args[2]: sponsor address (32 bytes)
from algosdk import encoding
app_args = [
    confio_asset_id.to_bytes(8, 'big'),  # CONFIO asset ID
    encoding.decode_address(admin_addr),  # admin address (32 bytes)
    encoding.decode_address(admin_addr),  # sponsor address (using admin for testnet)
]

txn = transaction.ApplicationCreateTxn(
    sender=admin_addr,
    sp=params,
    on_complete=transaction.OnComplete.NoOpOC,
    approval_program=approval_binary,
    clear_program=clear_binary,
    global_schema=global_schema,
    local_schema=local_schema,
    app_args=app_args,
    extra_pages=3,  # Program is larger than 2KB, needs extra pages
)

signed_txn = txn.sign(admin_private)
tx_id = client.send_transaction(signed_txn)
print(f"Transaction ID: {tx_id}")

result = transaction.wait_for_confirmation(client, tx_id, 4)
app_id = result['application-index']

print(f"✓ Application created: {app_id}")
print()

# Get application address
from algosdk.logic import get_application_address
app_address = get_application_address(app_id)
print(f"Application address: {app_address}")

# Bootstrap the contract (opt into CONFIO asset)
print("\n=== Bootstrapping Contract ===")

# Step 1: Fund the contract with ALGOs for MBR
print("1. Funding contract with ALGOs...")
params = client.suggested_params()
payment_txn = transaction.PaymentTxn(
    sender=admin_addr,
    receiver=app_address,
    amt=500_000,  # 0.5 ALGO for MBR
    sp=params,
)
signed = payment_txn.sign(admin_private)
tx_id = client.send_transaction(signed)
transaction.wait_for_confirmation(client, tx_id, 4)
print(f"   ✓ Funded with 0.5 ALGO (txid: {tx_id})")

# Step 2: Bootstrap (opt into CONFIO asset)
print("2. Opting into CONFIO asset...")
params_payment = client.suggested_params()
params_call = client.suggested_params()

# MBR payment for asset opt-in
mbr_payment = transaction.PaymentTxn(
    sender=admin_addr,
    receiver=app_address,
    amt=102_000,  # MBR for asset opt-in + buffer
    sp=params_payment,
)

# Bootstrap call
bootstrap_call = transaction.ApplicationCallTxn(
    sender=admin_addr,
    index=app_id,
    on_complete=transaction.OnComplete.NoOpOC,
    sp=params_call,
    app_args=[b'bootstrap', confio_asset_id.to_bytes(8, 'big')],
    foreign_assets=[confio_asset_id],
)

# Assign group ID
transaction.assign_group_id([mbr_payment, bootstrap_call])

# Sign both
signed_payment = mbr_payment.sign(admin_private)
signed_call = bootstrap_call.sign(admin_private)

# Send as atomic group
tx_id = client.send_transactions([signed_payment, signed_call])
result = transaction.wait_for_confirmation(client, tx_id, 4)
print(f"   ✓ Bootstrapped (txid: {tx_id})")

# Step 3: Fund vault with CONFIO
print("3. Funding vault with CONFIO...")
params = client.suggested_params()
fund_txn = transaction.AssetTransferTxn(
    sender=admin_addr,
    receiver=app_address,
    amt=200_000_000,  # 200 CONFIO
    index=confio_asset_id,
    sp=params,
)
signed = fund_txn.sign(admin_private)
tx_id = client.send_transaction(signed)
transaction.wait_for_confirmation(client, tx_id, 4)
print(f"   ✓ Funded vault with 200 CONFIO (txid: {tx_id})")

# Step 4: Set manual price
print("4. Setting manual price ($0.25/CONFIO)...")
params = client.suggested_params()
manual_price_micro_cusd = 250_000  # $0.25 in micro-cUSD

price_call = transaction.ApplicationCallTxn(
    sender=admin_addr,
    index=app_id,
    on_complete=transaction.OnComplete.NoOpOC,
    sp=params,
    app_args=[b'set_price_override', manual_price_micro_cusd.to_bytes(8, 'big')],
)
signed = price_call.sign(admin_private)
tx_id = client.send_transaction(signed)
transaction.wait_for_confirmation(client, tx_id, 4)
print(f"   ✓ Manual price set (txid: {tx_id})")

print()
print("=== Deployment Complete ===")
print(f"App ID: {app_id}")
print(f"App Address: {app_address}")
print()
print("Update your .env.testnet with:")
print(f"ALGORAND_REWARD_APP_ID={app_id}")
