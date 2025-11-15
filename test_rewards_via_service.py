import os
import sys

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
os.environ['CONFIO_ENV'] = 'testnet'

import django
django.setup()

from blockchain.rewards_service import ConfioRewardsService

# Initialize service
service = ConfioRewardsService()

# User addresses
user_9_addr = "TIU6WOJ5CYM6TMOOBOQV4EDPUZ6RVNVEO6MTTULYH6SWW67VR75D6UJAHM"  # Referee
user_8_addr = "P7WYM6SDBLV5UWM6AWFD4ZCNH7DZE3EICBZOAOORAUHDBVQ44RRS6ZLZZU"  # Referrer

# Rewards: $5 each @ $0.25/CONFIO = 20 CONFIO each
reward_cusd_micro = 5_000_000  # $5 in micro-cUSD (this will calculate referee CONFIO amount)
referrer_confio_micro = 20_000_000  # 20 CONFIO in micro-CONFIO for referrer

print("Creating TWO-SIDED reward box via RewardsService")
print(f"Referee (user 9): {user_9_addr}")
print(f"Referrer (user 8): {user_8_addr}")
print(f"Reward (cUSD): ${reward_cusd_micro / 1_000_000}")
print(f"Referrer CONFIO: {referrer_confio_micro / 1_000_000}")
print()

try:
    result = service.mark_eligibility(
        user_address=user_9_addr,
        reward_cusd_micro=reward_cusd_micro,
        referee_confio_micro=0,  # Not used by contract, will be calculated
        referrer_confio_micro=referrer_confio_micro,
        referrer_address=user_8_addr,
    )

    print(f"✓ Box created successfully!")
    print(f"Transaction ID: {result['txid']}")
    print(f"Confirmed in round: {result.get('confirmed-round', 'N/A')}")

    # Read the box to verify
    from algosdk import encoding
    user_9_bytes = encoding.decode_address(user_9_addr)
    box_response = service.algod.application_box_by_name(service.app_id, user_9_bytes)
    box_value = box_response['value']

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
