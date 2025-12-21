import os
import django
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from achievements.models import ReferralRewardEvent

def inspect():
    try:
        event = ReferralRewardEvent.objects.get(id=146)
        print(f"Event 146:")
        print(f"  User: {event.user.username}")
        print(f"  Status: {event.reward_status}")
        print(f"  Trigger: {event.trigger}")
        print(f"  Referral ID: {event.referral_id}")
        
        if event.referral:
            ref = event.referral
            print(f"Referral {ref.id}:")
            print(f"  Status: {ref.status}")
            print(f"  Referrer Reward Status: {ref.referrer_reward_status}")
            print(f"  Referrer Awarded: {ref.referrer_confio_awarded}")
            print(f"  Referee Reward Status: {ref.referee_reward_status}")
            print(f"  Referee Awarded: {ref.referee_confio_awarded}")
    except ReferralRewardEvent.DoesNotExist:
        print("Event 146 not found")

if __name__ == "__main__":
    inspect()
