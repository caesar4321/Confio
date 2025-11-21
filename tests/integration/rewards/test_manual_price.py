from algosdk.v2client import algod
from algosdk import account, mnemonic, transaction
import os

# Setup
algod_address = "https://testnet-api.4160.nodely.dev"
algod_token = ""
admin_mnemonic = "<REDACTED_OLD_COMPROMISED_MNEMONIC>"

client = algod.AlgodClient(algod_token, algod_address)
admin_private = mnemonic.to_private_key(admin_mnemonic)
admin_addr = account.address_from_private_key(admin_private)

app_id = 749659762

# Try to set manual price
params = client.suggested_params()
manual_price_micro_cusd = 250000  # $0.25/CONFIO in micro-cUSD

print(f"Setting manual price for app {app_id}")
print(f"Price: {manual_price_micro_cusd} micro-cUSD per CONFIO")
print(f"Admin: {admin_addr}")

try:
    app_call = transaction.ApplicationCallTxn(
        sender=admin_addr,
        sp=params,
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[
            b'set_manual_price',
            manual_price_micro_cusd.to_bytes(8, 'big')
        ]
    )

    signed = app_call.sign(admin_private)
    tx_id = client.send_transaction(signed)
    print(f"Transaction ID: {tx_id}")

    result = transaction.wait_for_confirmation(client, tx_id, 4)
    print(f"✓ Confirmed in round {result['confirmed-round']}")
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
