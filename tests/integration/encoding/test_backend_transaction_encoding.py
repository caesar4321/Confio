#!/usr/bin/env python3
"""Test what the backend actually encodes for the referrer claim transaction"""
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

print(f"Referee: {referee.username} - {referee_addr}")
print(f"Referrer: {referrer.username} - {referrer_addr}")
print()

# Build the claim group
service = ConfioRewardsService()
group = service.build_referrer_claim_group(
    referrer_address=referrer_addr,
    referee_address=referee_addr,
)

print(f"✅ Built claim group: {group['group_id']}")
print()

# Decode the unsigned transaction bytes that will be sent to the client
user_unsigned_b64 = group['user_unsigned']
user_unsigned_bytes = base64.b64decode(user_unsigned_b64)

print(f"User unsigned transaction (msgpack bytes):")
print(f"  Length: {len(user_unsigned_bytes)} bytes")
print(f"  Base64: {user_unsigned_b64[:50]}...")
print()

# Decode to inspect the actual content
import algosdk
import msgpack
txn_dict = msgpack.unpackb(user_unsigned_bytes, raw=False)

print(f"Decoded transaction dict keys: {list(txn_dict.keys())}")
print(f"  Type: {txn_dict.get('type')}")
print(f"  Sender: {encoding.encode_address(txn_dict.get('snd'))}")
print(f"  App ID: {txn_dict.get('apid')}")
print(f"  App args: {txn_dict.get('apaa')}")

if 'apat' in txn_dict:
    print(f"  Accounts ({len(txn_dict['apat'])}):")
    for i, addr_bytes in enumerate(txn_dict['apat']):
        print(f"    [{i}] {encoding.encode_address(addr_bytes)}")

if 'apbx' in txn_dict:
    print(f"  Boxes ({len(txn_dict['apbx'])}):")
    for i, box_ref in enumerate(txn_dict['apbx']):
        app_index = box_ref.get('i', 0)
        box_name = box_ref.get('n')
        box_addr = encoding.encode_address(box_name)
        print(f"    [{i}] app={app_index}, name={box_addr}")
        print(f"        name_hex={box_name.hex()}")
else:
    print(f"  ❌ NO BOXES in the transaction dict!")

print()
print(f"Expected box address (referee): {referee_addr}")
print(f"Wrong box address (referrer): {referrer_addr}")
