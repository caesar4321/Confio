from django.contrib.auth import get_user_model
from usdc_transactions.models import USDCDeposit
from achievements.services.referral_rewards import sync_referral_reward_for_event, EventContext
from achievements.models import ReferralRewardEvent
from decimal import Decimal

def run_fix():
    User = get_user_model()
    try:
        user = User.objects.get(id=2696)
        print(f"Processing for {user.username} (ID: 2696)")
    except User.DoesNotExist:
        print("User 2696 not found!")
        return

    # 1. Trigger Top Up
    # We grab the comprehensive deposit
    deposit = USDCDeposit.objects.filter(actor_user=user, status='COMPLETED').order_by('-created_at').first()
    
    if deposit:
        print(f"Found deposit: {deposit.amount} USDC (ID: {deposit.deposit_id})")
        
        ctx = EventContext(
            event="top_up",
            amount=deposit.amount,
            metadata={
                "deposit_id": str(deposit.deposit_id),
                "network": deposit.network,
                "source_address": deposit.source_address,
                "manual_fix": True
            }
        )
        sync_referral_reward_for_event(user, ctx)
        print("Top Up synced. Checkpoints should be recorded.")
    else:
        print("No completed deposit found to use for top_up fix.")

    # 2. Trigger Conversion
    # Find the skipped event
    skipped = ReferralRewardEvent.objects.filter(user=user, trigger='conversion_usdc_to_cusd').last()
    
    if skipped:
        print(f"Found conversion event: {skipped.id} (Status: {skipped.reward_status})")
        # Re-run sync with data from event
        ctx_conv = EventContext(
            event="conversion_usdc_to_cusd",
            amount=skipped.amount,
            metadata=skipped.metadata
        )
        res = sync_referral_reward_for_event(user, ctx_conv)
        print(f"Conversion re-synced. Result referral ID: {res.id if res else 'None'}")
        
        # Verify status
        skipped.refresh_from_db()
        print(f"Final Event Status: {skipped.reward_status}")
    else:
        print("No conversion event found to re-process.")

if __name__ == '__main__':
    run_fix()
