#!/usr/bin/env python3
"""Test what build_referrer_claim_group actually produces"""
import os
import django
import base64

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User
from achievements.services.referral_rewards import get_primary_algorand_address
from blockchain.rewards_service import ConfioRewardsService
from algosdk import encoding

# Get users
referee = User.objects.get(username='user_4923eef3')
referrer = User.objects.get(username='julianmoonluna')

referee_addr = get_primary_algorand_address(referee)
referrer_addr = get_primary_algorand_address(referrer)

print(f"Referee: {referee.username}")
print(f"  Address: {referee_addr}")
print(f"  Hex: {encoding.decode_address(referee_addr).hex()}")
print()
print(f"Referrer: {referrer.username}")
print(f"  Address: {referrer_addr}")
print(f"  Hex: {encoding.decode_address(referrer_addr).hex()}")
print()

# Build the claim group
service = ConfioRewardsService()
try:
    group = service.build_referrer_claim_group(
        referrer_address=referrer_addr,
        referee_address=referee_addr,
    )

    print("✅ Successfully built claim group")
    print(f"Group ID: {group['group_id']}")

    # Decode the unsigned transaction to inspect it
    user_unsigned_bytes = base64.b64decode(group['user_unsigned'])
    sponsor_signed_bytes = base64.b64decode(group['sponsor_signed'])

    print()
    print("User unsigned transaction (msgpack):")
    print(f"  Length: {len(user_unsigned_bytes)} bytes")

    # Try to decode and inspect
    import algosdk
    user_txn = algosdk.encoding.msgpack_decode(group['user_unsigned'])
    print(f"  Sender: {user_txn.sender}")
    print(f"  Type: {user_txn.type}")

    if hasattr(user_txn, 'boxes'):
        print(f"  Boxes: {len(user_txn.boxes)} box references")
        for i, box_ref in enumerate(user_txn.boxes):
            box_name = box_ref.name
            box_app = box_ref.app_index
            print(f"    Box {i}: app_index={box_app}, name_hex={box_name.hex()}")
            try:
                box_addr = encoding.encode_address(box_name)
                print(f"            name_as_address={box_addr}")
            except:
                print(f"            name_length={len(box_name)} (not an address)")

    if hasattr(user_txn, 'accounts'):
        print(f"  Accounts: {user_txn.accounts}")

    if hasattr(user_txn, 'app_args'):
        print(f"  App args: {[arg.decode() if isinstance(arg, bytes) else arg for arg in user_txn.app_args]}")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
