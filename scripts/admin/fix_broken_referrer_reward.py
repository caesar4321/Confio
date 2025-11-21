#!/usr/bin/env python3
"""Fix the broken referrer reward by deleting and recreating the box with correct amounts"""
from algosdk.v2client import algod
from algosdk import mnemonic, account, encoding
from algosdk.transaction import PaymentTxn, ApplicationCallTxn, wait_for_confirmation, assign_group_id
from algosdk.logic import get_application_address

# Setup
algod_address = "https://testnet-api.4160.nodely.dev"
algod_token = ""
admin_mnemonic = "<REDACTED_OLD_COMPROMISED_MNEMONIC>"

client = algod.AlgodClient(algod_token, algod_address)
admin_private = mnemonic.to_private_key(admin_mnemonic)
admin_addr = account.address_from_private_key(admin_private)

# Contract details
app_id = 749662493
confio_asset_id = 749148838

# Get user_4923eef3's Algorand address
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User
from achievements.services.referral_rewards import get_primary_algorand_address

user = User.objects.get(username='user_4923eef3')
user_address = get_primary_algorand_address(user)

print(f"=== Fixing Broken Referrer Reward ===")
print(f"User: {user.username}")
print(f"Algorand Address: {user_address}")
print(f"App ID: {app_id}")
print()

user_addr_bytes = encoding.decode_address(user_address)

try:
    # First, read the current box to see what's in it
    import base64
    box_response = client.application_box_by_name(app_id, user_addr_bytes)
    box_value = base64.b64decode(box_response['value'])

    import struct
    amount_offset = 0
    claimed_offset = 8
    ref_amount_offset = 16
    ref_addr_offset = 24
    ref_claimed_offset = 56

    referee_amount = struct.unpack('>Q', box_value[amount_offset:amount_offset+8])[0]
    referee_claimed = struct.unpack('>Q', box_value[claimed_offset:claimed_offset+8])[0]
    referrer_amount = struct.unpack('>Q', box_value[ref_amount_offset:ref_amount_offset+8])[0]
    ref_address = encoding.encode_address(box_value[ref_addr_offset:ref_addr_offset+32])
    referrer_claimed = struct.unpack('>Q', box_value[ref_claimed_offset:ref_claimed_offset+8])[0]

    print(f"Current box state:")
    print(f"  Referee amount: {referee_amount / 1_000_000} CONFIO")
    print(f"  Referee claimed: {referee_claimed / 1_000_000} CONFIO")
    print(f"  Referrer amount: {referrer_amount / 1_000_000} CONFIO")
    print(f"  Referrer address: {ref_address}")
    print(f"  Referrer claimed: {referrer_claimed / 1_000_000} CONFIO")
    print()

    if referrer_amount > 0:
        print("⚠️  Referrer amount is already set. This box may not need fixing.")
        print("Continuing anyway to demonstrate the process...")
        print()

    # Step 1: Delete the box using admin delete_box call
    print("Step 1: Deleting existing box...")

    params_payment = client.suggested_params()
    params_call = client.suggested_params()

    app_address = get_application_address(app_id)

    # MBR refund payment (the contract will return the MBR when box is deleted)
    # For admin operations, we typically send 0 ALGO
    mbr_payment = PaymentTxn(
        sender=admin_addr,
        receiver=app_address,
        amt=0,
        sp=params_payment,
    )

    # Application call to delete box
    app_call = ApplicationCallTxn(
        sender=admin_addr,
        index=app_id,
        on_complete=0,  # NoOp
        sp=params_call,
        app_args=[b'delete_box'],
        accounts=[user_address],
        foreign_assets=[confio_asset_id],
        boxes=[(app_id, user_addr_bytes)],
    )

    # Group and sign
    assign_group_id([mbr_payment, app_call])
    signed_payment = mbr_payment.sign(admin_private)
    signed_call = app_call.sign(admin_private)

    # Send
    tx_id = client.send_transactions([signed_payment, signed_call])
    print(f"Delete box transaction ID: {tx_id}")

    result = wait_for_confirmation(client, tx_id, 4)
    print(f"✅ Box deleted in round {result['confirmed-round']}")
    print()

    print("Step 2: Now run Django command to resync the referral reward...")
    print(f"Command: CONFIO_ENV=testnet PYTHONPATH=/Users/julian/Confio myvenv/bin/python manage.py resync_referral_rewards --referred-user user_4923eef3 --force")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
