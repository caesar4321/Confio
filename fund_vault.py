#!/usr/bin/env python3
"""Fund the rewards vault with CONFIO tokens"""
from algosdk.v2client import algod
from algosdk import mnemonic, account
from algosdk.transaction import AssetTransferTxn, wait_for_confirmation
from algosdk.logic import get_application_address

# Setup
algod_address = "https://testnet-api.4160.nodely.dev"
algod_token = ""
sponsor_mnemonic = "<REDACTED_OLD_COMPROMISED_MNEMONIC>"

client = algod.AlgodClient(algod_token, algod_address)
sponsor_private = mnemonic.to_private_key(sponsor_mnemonic)
sponsor_addr = account.address_from_private_key(sponsor_private)

# Contract details
app_id = 749662493
confio_asset_id = 749148838
amount_confio = 1000  # Fund with 1000 CONFIO

# Convert to micro-CONFIO
amount_micro = amount_confio * 1_000_000

print(f"=== Funding Rewards Vault ===")
print(f"App ID: {app_id}")
print(f"Amount: {amount_confio} CONFIO ({amount_micro} micro-CONFIO)")

app_address = get_application_address(app_id)
print(f"Vault Address: {app_address}")
print()

try:
    params = client.suggested_params()

    txn = AssetTransferTxn(
        sender=sponsor_addr,
        sp=params,
        receiver=app_address,
        amt=amount_micro,
        index=confio_asset_id,
    )

    signed_txn = txn.sign(sponsor_private)
    tx_id = client.send_transaction(signed_txn)

    print(f"Transaction ID: {tx_id}")
    result = wait_for_confirmation(client, tx_id, 4)
    print(f"✅ Funded in round {result['confirmed-round']}")

    # Check new balance
    account_info = client.account_info(app_address)
    for asset in account_info.get('assets', []):
        if asset['asset-id'] == confio_asset_id:
            new_balance = asset['amount']
            print(f"\nNew vault balance: {new_balance / 1_000_000} CONFIO ({new_balance} micro-CONFIO)")
            break

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
