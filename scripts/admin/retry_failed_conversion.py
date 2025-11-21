#!/usr/bin/env python3
"""Retry the failed conversion_usdc_to_cusd event that failed due to insufficient vault funds"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User
from achievements.models import ReferralRewardEvent
from achievements.services.referral_rewards import sync_referral_reward_for_event, EventContext
from decimal import Decimal

# Find the user
user = User.objects.get(username='user_4923eef3')
print(f"User: {user.username} (PK: {user.pk})")

# Find the failed conversion event
failed_event = ReferralRewardEvent.objects.get(id=50)
print(f"\nFailed Event ID: {failed_event.id}")
print(f"  Trigger: {failed_event.trigger}")
print(f"  Status: {failed_event.reward_status}")
print(f"  Error: {failed_event.error[:100]}...")
print(f"  Referral ID: {failed_event.referral_id}")

# Get the pending reward event to see what amounts should be
pending_event = ReferralRewardEvent.objects.get(id=49)
print(f"\nPending Event ID: {pending_event.id}")
print(f"  Status: {pending_event.reward_status}")
print(f"  Referee CONFIO: {pending_event.referee_confio}")
print(f"  Referrer CONFIO: {pending_event.referrer_confio}")

# Now retry the conversion event
print(f"\n=== Retrying sync for conversion event ===")
try:
    event_ctx = EventContext(
        event='conversion_usdc_to_cusd',
        amount=Decimal('5.0'),  # The conversion amount from the logs
        metadata={}
    )

    result = sync_referral_reward_for_event(user, event_ctx)

    if result:
        print(f"✅ Successfully synced! Referral: {result}")
        # Reload to see updated data
        failed_event.refresh_from_db()
        pending_event.refresh_from_db()

        print(f"\nUpdated failed event:")
        print(f"  Status: {failed_event.reward_status}")
        print(f"  Referee CONFIO: {failed_event.referee_confio}")
        print(f"  Referrer CONFIO: {failed_event.referrer_confio}")
        print(f"  TX ID: {failed_event.reward_tx_id}")

        print(f"\nUpdated pending event:")
        print(f"  Status: {pending_event.reward_status}")
    else:
        print(f"⚠️  Sync returned None (may be already processed or not eligible)")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
