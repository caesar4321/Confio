
import sys
import os
import django

# Add project root to path
sys.path.insert(0, '/Users/julian/Confio')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from users.models import Account
from achievements.models import UserReferral, ReferralRewardEvent

def find_user(address):
    print(f"Searching for address: {address}")
    try:
        account = Account.objects.filter(algorand_address=address).first()
        if not account:
            print("No account found for this address.")
            return

        user = account.user
        print(f"User Found: ID={user.id} Username={user.username}")
        
        # Check Referrals
        referral = UserReferral.objects.filter(referred_user=user).first()
        if referral:
            print(f"Referral Record Found: ID={referral.id} Status={referral.status}")
            print(f"  Referrer: {referral.referrer_user.username} (ID={referral.referrer_user.id})")
            print(f"  Reward Status: Referee={referral.referee_reward_status} Referrer={referral.referrer_reward_status}")
            print(f"  Metadata: {referral.reward_metadata}")
        else:
            print("No UserReferral record found (User was not referred).")

        # Check Events
        events = ReferralRewardEvent.objects.filter(user=user)
        print(f"\nReferral Reward Events ({events.count()}):")
        for event in events:
            print(f"  Event ID={event.id} Type={event.trigger} Status={event.reward_status}")
            print(f"  Error: {event.error}")
            print(f"  Metadata: {event.metadata}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python find_user_by_address.py <address>")
    else:
        find_user(sys.argv[1])
