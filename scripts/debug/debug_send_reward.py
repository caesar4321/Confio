
import os
import django
from decimal import Decimal

# Configure Django
import sys
sys.path.insert(0, '/Users/julian/Confio')
print(f"DEBUG: sys.path: {sys.path}")
import os
if os.path.exists('/Users/julian/Confio/config/__init__.py'):
    print("DEBUG: config/__init__.py exists")
else:
    print("DEBUG: config/__init__.py DOES NOT EXIST")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.contrib.auth import get_user_model
from achievements.services.referral_rewards import sync_referral_reward_for_event, EventContext
from achievements.models import ReferralRewardEvent

User = get_user_model()

def debug_reward():
    try:
        user = User.objects.get(username='julianm')
    except User.DoesNotExist:
        print("User 'julianm' not found")
        return

    print(f"User found: {user.username} (ID: {user.id})")

    # Simulate Send Event
    ctx = EventContext(
        event="send",
        amount=Decimal("1.00"),
        metadata={"debug": True}
    )
    
    print("Calling sync_referral_reward_for_event...")
    try:
        updated_referral = sync_referral_reward_for_event(user, ctx)
        
        if updated_referral:
            print(f"Success! Referral updated. Status: {updated_referral.reward_status}")
            print(f"Referee Reward Status: {updated_referral.referee_reward_status}")
        else:
            print("Returned None (no referral updated).")
            
        # Check the specific event
        event = ReferralRewardEvent.objects.filter(
            user=user, 
            trigger="send",
            metadata__debug=True
        ).last()
        
        if event:
            print(f"Event Status: {event.reward_status}")
            print(f"Event Error: {event.error}")
        else:
            print("Event not found in DB!")
            
    except Exception as e:
        print(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_reward()
