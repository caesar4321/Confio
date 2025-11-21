#!/usr/bin/env python3
"""Test two-sided reward box creation with the fixed contract"""

from algosdk.v2client import algod
from algosdk import account, mnemonic, transaction, encoding
import struct

# Setup
algod_address = "https://testnet-api.4160.nodely.dev"
algod_token = ""
admin_mnemonic = "<REDACTED_OLD_COMPROMISED_MNEMONIC>"

client = algod.AlgodClient(algod_token, algod_address)
admin_private = mnemonic.to_private_key(admin_mnemonic)
admin_addr = account.address_from_private_key(admin_private)

# Use the CORRECTED contract with proper Txn.accounts indexing
app_id = 749662493
confio_asset_id = 749148838

# Generate fresh user addresses for testing
user_9_private, user_9_addr = account.generate_account()  # Referee
user_8_private, user_8_addr = account.generate_account()  # Referrer
print(f"Generated referee: {user_9_addr}")
print(f"Generated referrer: {user_8_addr}")

# Rewards: $5 each @ $0.25/CONFIO = 20 CONFIO each
reward_cusd_micro = 5_000_000  # $5 in micro-cUSD
referrer_confio_micro = 20_000_000  # 20 CONFIO in micro-CONFIO

print(f"=== Testing TWO-SIDED Reward Box Creation ===")
print(f"App ID: {app_id}")
print(f"Referee (user 9): {user_9_addr}")
print(f"Referrer (user 8): {user_8_addr}")
print(f"Reward (cUSD): ${reward_cusd_micro / 1_000_000}")
print(f"Referrer CONFIO: {referrer_confio_micro / 1_000_000}")
print()

user_9_bytes = encoding.decode_address(user_9_addr)
user_8_bytes = encoding.decode_address(user_8_addr)

try:
    params_payment = client.suggested_params()
    params_call = client.suggested_params()

    # MBR payment for box creation
    from algosdk.logic import get_application_address
    app_address = get_application_address(app_id)

    mbr_payment = transaction.PaymentTxn(
        sender=admin_addr,
        receiver=app_address,
        amt=100_000,  # MBR for box
        sp=params_payment,
    )

    # Application call to mark eligibility
    app_call = transaction.ApplicationCallTxn(
        sender=admin_addr,
        index=app_id,
        on_complete=transaction.OnComplete.NoOpOC,
        sp=params_call,
        app_args=[
            b'mark_eligible',
            reward_cusd_micro.to_bytes(8, 'big'),  # app_args[1] = reward in cUSD
            user_9_bytes,  # app_args[2] = referee address (32 bytes)
            referrer_confio_micro.to_bytes(8, 'big'),  # app_args[3] = referrer CONFIO amount
        ],
        accounts=[user_9_addr, user_8_addr],  # Foreign accounts: [1]=referee, [2]=referrer
        foreign_assets=[confio_asset_id],
        boxes=[(app_id, user_9_bytes)],
    )

    # Debug: Print app_args before sending
    print(f"\nDebug - Transaction Details:")
    print(f"  NumAppArgs: {len(app_call.app_args)}")
    for i, arg in enumerate(app_call.app_args):
        if i == 0:
            print(f"  app_args[{i}]: {arg} (method name)")
        else:
            print(f"  app_args[{i}]: {arg.hex() if isinstance(arg, bytes) else arg} ({len(arg)} bytes)")
    print(f"  accounts: {app_call.accounts}")
    print()

    # Assign group ID
    transaction.assign_group_id([mbr_payment, app_call])

    # Sign both
    signed_payment = mbr_payment.sign(admin_private)
    signed_call = app_call.sign(admin_private)

    # Send as atomic group
    tx_id = client.send_transactions([signed_payment, signed_call])
    print(f"Transaction ID: {tx_id}")

    result = transaction.wait_for_confirmation(client, tx_id, 4)
    print(f"✓ Box created in round {result['confirmed-round']}")
    print()

    # Read the box to verify
    import base64
    box_response = client.application_box_by_name(app_id, user_9_bytes)
    box_value = base64.b64decode(box_response['value'])
    print(f"Box size: {len(box_value)} bytes")

    # Parse box contents - offsets from contracts/rewards/confio_rewards.py
    amount_offset = 0  # AMOUNT_OFFSET
    claimed_offset = 8  # CLAIMED_OFFSET
    ref_amount_offset = 16  # REF_AMOUNT_OFFSET
    ref_addr_offset = 24  # REF_ADDRESS_OFFSET
    ref_claimed_offset = 56  # REF_CLAIMED_OFFSET
    round_offset = 64  # ROUND_OFFSET

    amount = struct.unpack('>Q', box_value[amount_offset:amount_offset+8])[0]
    claimed = struct.unpack('>Q', box_value[claimed_offset:claimed_offset+8])[0]
    ref_round = struct.unpack('>Q', box_value[round_offset:round_offset+8])[0]
    ref_address = encoding.encode_address(box_value[ref_addr_offset:ref_addr_offset+32])
    ref_amount = struct.unpack('>Q', box_value[ref_amount_offset:ref_amount_offset+8])[0]
    ref_claimed = struct.unpack('>Q', box_value[ref_claimed_offset:ref_claimed_offset+8])[0]

    print(f"\n✅ TWO-SIDED Reward Box Contents:")
    print(f"  Referee amount: {amount / 1_000_000} CONFIO")
    print(f"  Referee claimed: {'Yes' if claimed else 'No'}")
    print(f"  Round: {ref_round}")
    print(f"  Referrer address: {ref_address}")
    print(f"  Referrer amount: {ref_amount / 1_000_000} CONFIO")
    print(f"  Referrer claimed: {'Yes' if ref_claimed else 'No'}")
    print(f"\nDebug:")
    print(f"  Expected user_8: {user_8_addr}")
    print(f"  Admin address: {admin_addr}")
    print(f"  Box hex (ref address): {box_value[ref_addr_offset:ref_addr_offset+32].hex()}")

    # Verify the box was created correctly
    expected_referee_amount = reward_cusd_micro * 1_000_000 // 250_000  # Convert cUSD to CONFIO at $0.25/CONFIO

    if ref_address == user_8_addr and ref_amount == referrer_confio_micro and amount == expected_referee_amount:
        print(f"\n🎉 SUCCESS! Two-sided reward box created correctly!")
        print(f"   - Referee can claim {amount / 1_000_000} CONFIO")
        print(f"   - Referrer can claim {ref_amount / 1_000_000} CONFIO")
    else:
        print(f"\n❌ ERROR: Box contents don't match expected values")
        print(f"   Expected referee: {expected_referee_amount / 1_000_000} CONFIO, got {amount / 1_000_000}")
        print(f"   Expected referrer: {referrer_confio_micro / 1_000_000} CONFIO, got {ref_amount / 1_000_000}")
        print(f"   Expected ref address: {user_8_addr}, got {ref_address}")

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
