
import sys
import os
import django
from decimal import Decimal

# Add project root to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django.setup()

from users.schema import PrepareReferralRewardClaim
from achievements.models import ReferralRewardEvent
from users.models import User
from unittest.mock import MagicMock
import inspect
from blockchain.rewards_service import ConfioRewardsService

def debug_claim():
    print(f"ConfioRewardsService loaded from: {inspect.getfile(ConfioRewardsService)}")
    print("Starting debug of PrepareReferralRewardClaim...")
    
    # User 1242 (referee)
    target_user_id = 1242
    target_event_id = 130
    
    try:
        user = User.objects.get(id=target_user_id)
        print(f"User: {user} (ID: {user.id})")
        
        event = ReferralRewardEvent.objects.get(id=target_event_id)
        print(f"Event: {event} (ID: {event.id}, Trigger: {event.trigger}, Role: {event.actor_role}, Status: {event.reward_status})")
        
        # Mock info context
        class MockContext:
            def __init__(self, user):
                self.user = user

        class MockInfo:
            def __init__(self, user):
                self.context = MockContext(user)
        
        info = MockInfo(user)
        
        print(f"Mutation source file: {inspect.getfile(PrepareReferralRewardClaim)}")
        print("Mutation source code HEAD:")
        print(inspect.getsource(PrepareReferralRewardClaim.mutate)[:500])
        
        print("Calling mutate...")
        result = PrepareReferralRewardClaim.mutate(None, info, event_id=target_event_id)
        
        print(f"Result Success: {result.success}")
        print(f"Result Error: {result.error}")
        if result.success:
            print("Group ID:", result.group_id)
            
    except Exception as e:
        print(f"\nCRASHED WITH: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_claim()
