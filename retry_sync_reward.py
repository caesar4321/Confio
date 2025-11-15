#!/usr/bin/env python3
"""Manually retry syncing the eligible reward for user 3db2c9a11e2c156"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from achievements.models import ReferralRewardEvent
from users.models import User
from achievements.services.referral_rewards import sync_referral_reward_for_event

# Find the user by their custom ID
user_custom_id = '3db2c9a11e2c156'
user = User.objects.get(id=user_custom_id)

print(f"Found user: {user.id} (PK: {user.pk})")
print(f"Algorand address: {user.algorand_address}\n")

# Find the user's eligible rewards that failed to sync
eligible_events = ReferralRewardEvent.objects.filter(
    user=user,
    reward_status='eligible',
    reward_tx_id=''  # Not yet synced to blockchain
)

print(f"=== Retrying Reward Sync for User {user_custom_id} ===")
print(f"Found {eligible_events.count()} eligible rewards not yet synced\n")

for event in eligible_events:
    print(f"Event ID: {event.id}")
    print(f"  Trigger: {event.trigger}")
    print(f"  Actor Role: {event.actor_role}")
    print(f"  Referee CONFIO: {event.referee_confio}")
    print(f"  Referrer CONFIO: {event.referrer_confio}")
    print(f"  Referral ID: {event.referral_id if event.referral else 'None'}")

    try:
        print(f"\n  Attempting to sync to blockchain...")
        success = sync_referral_reward_for_event(
            user_id=user.pk,  # Use the primary key
            referral_id=event.referral_id,
            event_name=event.trigger
        )

        if success:
            print(f"  ✅ Successfully synced!")
            # Reload to see updated data
            event.refresh_from_db()
            print(f"  Transaction ID: {event.reward_tx_id}")
        else:
            print(f"  ❌ Sync returned False")

    except Exception as e:
        print(f"  ❌ Error: {e}")
        import traceback
        traceback.print_exc()

    print()

print("=== Done ===")
