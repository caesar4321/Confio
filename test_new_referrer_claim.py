#!/usr/bin/env python3
"""Test the NEW referrer claim flow with the updated contract."""
import os
import django
import base64

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User
from achievements.services.referral_rewards import get_primary_algorand_address
from blockchain.rewards_service import ConfioRewardsService
from algosdk import encoding, mnemonic, account
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

# First, mark the users as having a referral relationship
print("="*80)
print("STEP 1: Create referral relationship (mark referee eligible)")
print("="*80)

# In a real scenario, this would have already been done when the referee claimed.
# For testing, we'll simulate it by marking the referee eligible with a referrer.
# This creates the box with the referrer's address stored in it.

referee_key = encoding.decode_address(referee_addr)
referrer_key = encoding.decode_address(referrer_addr)

# Check if box already exists
try:
    box_data = service._read_user_box(referee_key)
    print(f"✅ Box already exists for referee {referee_addr}")
    print(f"   Referee amount: {box_data['referee_amount']} (claimed: {box_data['referee_claimed']})")
    print(f"   Referrer amount: {box_data['referrer_amount']} (claimed: {box_data['referrer_claimed']})")
    print(f"   Referrer address: {box_data['referrer_address']}")
except Exception as e:
    print(f"❌ Box does not exist yet: {e}")
    print(f"   You need to create the referral first by having the referee claim their reward.")
    print(f"   Or manually create the box for testing purposes.")
    exit(1)

print()

# Now test the referrer claim
print("="*80)
print("STEP 2: Build referrer claim transaction group")
print("="*80)

group = service.build_referrer_claim_group(
    referrer_address=referrer_addr,
    referee_address=referee_addr,
)

print(f"✅ Group built successfully")
print(f"   Sponsor transaction: {len(group['sponsor_unsigned'])} bytes")
print(f"   User transaction: {len(group['user_unsigned'])} bytes")
print()

# Decode the user transaction to inspect it
user_unsigned_b64 = group['user_unsigned']
user_unsigned_bytes = base64.b64decode(user_unsigned_b64)
txn_dict = msgpack.unpackb(user_unsigned_bytes, raw=False)

print("="*80)
print("STEP 3: Inspect the user transaction")
print("="*80)

print(f"Transaction type: {txn_dict.get('type')}")
print(f"Sender: {encoding.encode_address(txn_dict.get('snd'))}")
print(f"Application ID: {txn_dict.get('apid')}")
print()

# Check application args
if 'apaa' in txn_dict:
    print(f"Application args: {len(txn_dict['apaa'])}")
    for i, arg in enumerate(txn_dict['apaa']):
        if i == 0:
            print(f"  Arg {i}: {arg} (method)")
        elif i == 1:
            print(f"  Arg {i}: {encoding.encode_address(arg)} (referee address)")
        else:
            print(f"  Arg {i}: {arg.hex()}")

print()

# Check accounts
if 'apat' in txn_dict:
    print(f"Accounts: {len(txn_dict['apat'])}")
    for i, addr_bytes in enumerate(txn_dict['apat']):
        print(f"  Account {i}: {encoding.encode_address(addr_bytes)}")

print()

# Check boxes
if 'apbx' in txn_dict:
    print(f"✅ Boxes: {len(txn_dict['apbx'])} references")
    for i, box_ref in enumerate(txn_dict['apbx']):
        box_name = box_ref.get('n')
        box_addr = encoding.encode_address(box_name)
        print(f"  Box {i}: {box_addr}")
        print(f"         hex: {box_name.hex()}")

        # Verify it's the referee's address
        if box_addr == referee_addr:
            print(f"         ✅ CORRECT - This is the referee's address")
        else:
            print(f"         ❌ ERROR - This should be the referee's address!")
else:
    print("❌ NO BOXES in the transaction!")

print()
print("="*80)
print("SUMMARY")
print("="*80)
print(f"New contract app ID: {service.app_id}")
print(f"Referee address: {referee_addr}")
print(f"Referrer address: {referrer_addr}")
print(f"Box key (referee): {referee_key.hex()}")
print(f"Application args[1]: {txn_dict['apaa'][1].hex()}")
print(f"Are they equal? {txn_dict['apaa'][1].hex() == referee_key.hex()}")
print()

if 'apbx' in txn_dict and len(txn_dict['apbx']) > 0:
    box_hex = txn_dict['apbx'][0]['n'].hex()
    print(f"Box reference: {box_hex}")
    print(f"Expected (referee): {referee_key.hex()}")
    print(f"✅ Box reference is CORRECT!" if box_hex == referee_key.hex() else "❌ Box reference is WRONG!")
