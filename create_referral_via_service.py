#!/usr/bin/env python3
"""Create referral using the backend service directly."""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User
from achievements.services.referral_rewards import get_primary_algorand_address, create_referral_reward
from blockchain.rewards_service import ConfioRewardsService

# Get users
referee = User.objects.get(username='user_4923eef3')
referrer = User.objects.get(username='julianmoonluna')

referee_addr = get_primary_algorand_address(referee)
referrer_addr = get_primary_algorand_address(referrer)

print(f"Referee: {referee.username} - {referee_addr}")
print(f"Referrer: {referrer.username} - {referrer_addr}")
print()

# Use the backend service to create the referral
print("Creating referral reward using backend service...")
result = create_referral_reward(
    referee_address=referee_addr,
    referrer_address=referrer_addr,
    referee_reward_cusd_cents=250,  # $2.50
    referrer_reward_cusd_cents=250,  # $2.50
)

print(f"✅ Result: {result}")
print()

# Verify the box was created
service = ConfioRewardsService()
from algosdk import encoding
referee_key = encoding.decode_address(referee_addr)

try:
    box_data = service._read_user_box(referee_key)
    print(f"✅ Box created successfully!")
    print(f"   Referee amount: {box_data['referee_amount'] / 1_000_000} CONFIO (claimed: {box_data['referee_claimed']})")
    print(f"   Referrer amount: {box_data['referrer_amount'] / 1_000_000} CONFIO (claimed: {box_data['referrer_claimed']})")
    print(f"   Referrer address: {box_data['referrer_address']}")
    print(f"   Round created: {box_data['round_created']}")
except Exception as e:
    print(f"❌ Failed to read box: {e}")
