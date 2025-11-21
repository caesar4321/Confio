#!/usr/bin/env python3
"""Test if Python algosdk msgpack encode/decode corrupts box references"""
import os
import django
import base64

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User
from achievements.services.referral_rewards import get_primary_algorand_address
from blockchain.rewards_service import ConfioRewardsService
from algosdk import encoding
import msgpack

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

# Get the unsigned transaction
user_unsigned_b64 = group['user_unsigned']
user_unsigned_bytes = base64.b64decode(user_unsigned_b64)

print("=" * 80)
print("STEP 1: Original unsigned transaction")
print("=" * 80)
txn_dict = msgpack.unpackb(user_unsigned_bytes, raw=False)
if 'apbx' in txn_dict:
    for i, box_ref in enumerate(txn_dict['apbx']):
        box_name = box_ref.get('n')
        box_addr = encoding.encode_address(box_name)
        print(f"Box {i}: {box_addr}")
print()

# Now decode it using algosdk's msgpack_decode
print("=" * 80)
print("STEP 2: Decode with algosdk.encoding.msgpack_decode")
print("=" * 80)
unsigned_txn_obj = encoding.msgpack_decode(user_unsigned_b64)
print(f"Type: {type(unsigned_txn_obj)}")
if hasattr(unsigned_txn_obj, 'boxes'):
    print(f"Boxes: {unsigned_txn_obj.boxes}")
print()

# Now re-encode it
print("=" * 80)
print("STEP 3: Re-encode with algosdk.encoding.msgpack_encode")
print("=" * 80)
re_encoded_b64 = encoding.msgpack_encode(unsigned_txn_obj)
re_encoded_bytes = base64.b64decode(re_encoded_b64)
txn_dict_2 = msgpack.unpackb(re_encoded_bytes, raw=False)
if 'apbx' in txn_dict_2:
    for i, box_ref in enumerate(txn_dict_2['apbx']):
        box_name = box_ref.get('n')
        box_addr = encoding.encode_address(box_name)
        print(f"Box {i}: {box_addr}")
else:
    print("❌ NO BOXES after re-encoding!")
print()

print("=" * 80)
print("COMPARISON")
print("=" * 80)
print(f"Original boxes: {txn_dict.get('apbx')}")
print(f"Re-encoded boxes: {txn_dict_2.get('apbx')}")
print()
print(f"Are they equal? {txn_dict.get('apbx') == txn_dict_2.get('apbx')}")
