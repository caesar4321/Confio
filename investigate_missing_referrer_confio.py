#!/usr/bin/env python3
"""Investigate why julianmoonluna didn't receive CONFIO after claiming referrer reward"""
from algosdk.v2client import algod
from algosdk import encoding
import base64
import struct
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User
from achievements.models import UserReferral, ReferralRewardEvent
from achievements.services.referral_rewards import get_primary_algorand_address

# Algorand setup
client = algod.AlgodClient("", "https://testnet-api.4160.nodely.dev")
app_id = 749662493
confio_asset_id = 749148838

print("=" * 80)
print("INVESTIGATION: Missing Referrer CONFIO Reward")
print("=" * 80)

# Get users
referee = User.objects.get(username='user_4923eef3')
referrer = User.objects.get(username='julianmoonluna')

referee_addr = get_primary_algorand_address(referee)
referrer_addr = get_primary_algorand_address(referrer)

print(f"\n📋 USER INFORMATION")
print(f"Referee: {referee.username}")
print(f"  Algorand: {referee_addr}")
print(f"Referrer: {referrer.username}")
print(f"  Algorand: {referrer_addr}")

# Check database state
print(f"\n📊 DATABASE STATE")
referral = UserReferral.objects.get(referred_user=referee, referrer_user=referrer)
print(f"UserReferral ID: {referral.id}")
print(f"  status: {referral.status}")
print(f"  reward_status: {referral.reward_status}")
print(f"  reward_referee_confio: {referral.reward_referee_confio}")
print(f"  reward_referrer_confio: {referral.reward_referrer_confio}")
print(f"  referee_confio_awarded: {referral.referee_confio_awarded}")
print(f"  referrer_confio_awarded: {referral.referrer_confio_awarded}")
print(f"  reward_claimed_at: {referral.reward_claimed_at}")

# Check reward events
print(f"\n📝 REWARD EVENTS")
events = ReferralRewardEvent.objects.filter(referral=referral).order_by('created_at')
for e in events:
    print(f"Event {e.id}: {e.trigger} ({e.actor_role})")
    print(f"  Status: {e.reward_status}")
    print(f"  Referee CONFIO: {e.referee_confio}")
    print(f"  Referrer CONFIO: {e.referrer_confio}")
    print(f"  TX ID: {e.reward_tx_id if e.reward_tx_id else '(none)'}")

# Check on-chain box state
print(f"\n⛓️  ON-CHAIN BOX STATE")
referee_addr_bytes = encoding.decode_address(referee_addr)

try:
    box_response = client.application_box_by_name(app_id, referee_addr_bytes)
    box_value = base64.b64decode(box_response['value'])

    # Parse box
    amount_offset = 0
    claimed_offset = 8
    ref_amount_offset = 16
    ref_addr_offset = 24
    ref_claimed_offset = 56
    round_offset = 64

    referee_amount = struct.unpack('>Q', box_value[amount_offset:amount_offset+8])[0]
    referee_claimed = struct.unpack('>Q', box_value[claimed_offset:claimed_offset+8])[0]
    referrer_amount = struct.unpack('>Q', box_value[ref_amount_offset:ref_amount_offset+8])[0]
    ref_address = encoding.encode_address(box_value[ref_addr_offset:ref_addr_offset+32])
    referrer_claimed = struct.unpack('>Q', box_value[ref_claimed_offset:ref_claimed_offset+8])[0]
    round_created = struct.unpack('>Q', box_value[round_offset:round_offset+8])[0]

    print(f"Box exists for {referee_addr[:20]}...")
    print(f"  Referee amount: {referee_amount / 1_000_000} CONFIO")
    print(f"  Referee claimed: {referee_claimed / 1_000_000} CONFIO")
    print(f"  Referrer amount: {referrer_amount / 1_000_000} CONFIO")
    print(f"  Referrer address: {ref_address}")
    print(f"  Referrer claimed: {referrer_claimed / 1_000_000} CONFIO")
    print(f"  Created at round: {round_created}")

    # Diagnosis
    print(f"\n🔍 DIAGNOSIS")
    if referrer_amount == 0:
        print(f"❌ PROBLEM: Box has referrer_amount = 0")
        print(f"   This box was created with the bug that zeroed referrer rewards")
        print(f"   Referrer has nothing to claim from this box")
    elif referrer_claimed == referrer_amount and referrer_claimed > 0:
        print(f"✅ Referrer already claimed {referrer_claimed / 1_000_000} CONFIO")
        print(f"   Check referrer's Algorand balance for the transfer")
    elif referrer_claimed == 0 and referrer_amount > 0:
        print(f"⚠️  Referrer has {referrer_amount / 1_000_000} CONFIO available to claim")
        print(f"   But database shows they tried to claim")
        print(f"   The claim transaction may have failed")
    else:
        print(f"⚠️  Partial claim: {referrer_claimed / 1_000_000} of {referrer_amount / 1_000_000} CONFIO")

except Exception as e:
    print(f"❌ Box not found or error reading box: {e}")
    print(f"   The box may have been deleted after both parties claimed")

# Check referrer's CONFIO balance
print(f"\n💰 REFERRER'S CONFIO BALANCE")
try:
    account_info = client.account_info(referrer_addr)
    confio_balance = 0
    for asset in account_info.get('assets', []):
        if asset['asset-id'] == confio_asset_id:
            confio_balance = asset['amount']
            break

    print(f"Current CONFIO balance: {confio_balance / 1_000_000} CONFIO")

    if confio_balance == 0:
        print(f"❌ Referrer has ZERO CONFIO - they did NOT receive the reward")
    else:
        print(f"✅ Referrer has CONFIO - check if this includes the 20 CONFIO reward")

except Exception as e:
    print(f"❌ Error checking balance: {e}")

# Recommendations
print(f"\n💡 RECOMMENDATIONS")
if referrer_amount == 0:
    print(f"1. Delete the current box using admin delete_box")
    print(f"2. Re-sync the referral with the FIXED code that includes referrer amounts")
    print(f"3. Referrer can then claim their 20 CONFIO")
elif referrer_claimed > 0 and confio_balance == 0:
    print(f"1. Something is wrong - box shows claimed but wallet has no CONFIO")
    print(f"2. Check transaction history for the claim TX")
    print(f"3. May need to investigate the claim transaction")
elif referrer_claimed == 0 and referrer_amount > 0:
    print(f"1. Box has the reward ready but claim didn't complete")
    print(f"2. Referrer should retry claiming from the app")
    print(f"3. Or manually submit a claim_referrer transaction")

print("\n" + "=" * 80)
