#!/usr/bin/env python3
"""Bootstrap the rewards contract 749660401"""

from algosdk.v2client import algod
from algosdk import account, mnemonic, transaction
from algosdk.logic import get_application_address

# Setup
algod_address = "https://testnet-api.4160.nodely.dev"
algod_token = ""
admin_mnemonic = "<REDACTED_OLD_COMPROMISED_MNEMONIC>"

client = algod.AlgodClient(algod_token, algod_address)
admin_private = mnemonic.to_private_key(admin_mnemonic)
admin_addr = account.address_from_private_key(admin_private)

confio_asset_id = 749148838
app_id = 749660401
app_address = get_application_address(app_id)

print(f"=== Bootstrapping Contract {app_id} ===")
print(f"Admin: {admin_addr}")
print(f"App Address: {app_address}")
print()

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

# Bootstrap call - needs extra fee for inner transaction
params_call.flat_fee = True
params_call.fee = 2000  # Cover both outer and inner transaction

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
print("=== Bootstrap Complete ===")
print(f"App ID: {app_id}")
print(f"App Address: {app_address}")
print()
print("Update your .env.testnet with:")
print(f"ALGORAND_REWARD_APP_ID={app_id}")
