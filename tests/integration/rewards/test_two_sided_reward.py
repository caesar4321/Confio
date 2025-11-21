from algosdk.v2client import algod
from algosdk import account, mnemonic, transaction, encoding
import os

# Setup
algod_address = "https://testnet-api.4160.nodely.dev"
algod_token = ""
admin_mnemonic = "<REDACTED_OLD_COMPROMISED_MNEMONIC>"

client = algod.AlgodClient(algod_token, algod_address)
admin_private = mnemonic.to_private_key(admin_mnemonic)
admin_addr = account.address_from_private_key(admin_private)

# Use the NEW contract with the fix
app_id = 749659762

# User addresses
user_9_addr = "TIU6WOJ5CYM6TMOOBOQV4EDPUZ6RVNVEO6MTTULYH6SWW67VR75D6UJAHM"  # Referee
user_8_addr = "P7WYM6SDBLV5UWM6AWFD4ZCNH7DZE3EICBZOAOORAUHDBVQ44RRS6ZLZZU"  # Referrer

# Rewards: $5 each @ $0.25/CONFIO = 20 CONFIO each
reward_cusd_micro = 5_000_000  # $5 in micro-cUSD
referee_confio_micro = 20_000_000  # 20 CONFIO in micro-CONFIO
referrer_confio_micro = 20_000_000  # 20 CONFIO in micro-CONFIO

print(f"Creating TWO-SIDED reward box for app {app_id}")
print(f"Referee (user 9): {user_9_addr}")
print(f"Referrer (user 8): {user_8_addr}")
print(f"Reward (cUSD): ${reward_cusd_micro / 1_000_000}")
print(f"Referee CONFIO: {referee_confio_micro / 1_000_000}")
print(f"Referrer CONFIO: {referrer_confio_micro / 1_000_000}")
print()

# Check if addresses are different
user_9_bytes = encoding.decode_address(user_9_addr)
user_8_bytes = encoding.decode_address(user_8_addr)
print(f"Addresses are different: {user_9_bytes != user_8_bytes}")
print()

try:
    params = client.suggested_params()

    confio_asset_id = 749148838

    app_call = transaction.ApplicationCallTxn(
        sender=admin_addr,
        sp=params,
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        app_args=[
            b'mark_eligible',
            reward_cusd_micro.to_bytes(8, 'big'),
            user_9_bytes,  # app_args[2] = referee address
            referee_confio_micro.to_bytes(8, 'big'),
            referrer_confio_micro.to_bytes(8, 'big')
        ],
        accounts=[user_9_addr, user_8_addr],  # accounts[0] = referee, accounts[1] = referrer
        boxes=[(app_id, user_9_bytes)],
        foreign_assets=[confio_asset_id]
    )

    signed = app_call.sign(admin_private)
    tx_id = client.send_transaction(signed)
    print(f"Transaction ID: {tx_id}")

    result = transaction.wait_for_confirmation(client, tx_id, 4)
    print(f"✓ Box created in round {result['confirmed-round']}")

    # Read the box to verify
    box_response = client.application_box_by_name(app_id, user_9_bytes)
    box_value = box_response['value']
    print(f"Box size: {len(box_value)} bytes")

    # Parse box contents
    import struct
    amount_offset = 0
    claimed_offset = 8
    round_offset = 16
    ref_addr_offset = 24
    ref_amount_offset = 56
    ref_claimed_offset = 64

    amount = struct.unpack('>Q', box_value[amount_offset:amount_offset+8])[0]
    claimed = struct.unpack('>Q', box_value[claimed_offset:claimed_offset+8])[0]
    ref_address = encoding.encode_address(box_value[ref_addr_offset:ref_addr_offset+32])
    ref_amount = struct.unpack('>Q', box_value[ref_amount_offset:ref_amount_offset+8])[0]
    ref_claimed = struct.unpack('>Q', box_value[ref_claimed_offset:ref_claimed_offset+8])[0]

    print(f"\nBox contents:")
    print(f"  Referee amount: {amount / 1_000_000} CONFIO")
    print(f"  Referee claimed: {claimed / 1_000_000} CONFIO")
    print(f"  Referrer address: {ref_address}")
    print(f"  Referrer amount: {ref_amount / 1_000_000} CONFIO")
    print(f"  Referrer claimed: {ref_claimed / 1_000_000} CONFIO")

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
