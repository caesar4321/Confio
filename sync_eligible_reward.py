#!/usr/bin/env python3
"""Sync eligible reward for user 3db2c9a11e2c156 to the corrected blockchain contract"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from achievements.models import ReferralRewardEvent
from users.models import User
from blockchain.rewards_service import RewardsService
from decimal import Decimal

# Find the user
user_id = '3db2c9a11e2c156'
user = User.objects.get(id=user_id)
print(f'User: {user.id}')
print(f'Phone: {user.phone_number}')
print(f'Algorand Address: {user.algorand_address}')

# Find their eligible rewards
eligible = ReferralRewardEvent.objects.filter(user=user, reward_status='eligible')
print(f'\nEligible Rewards: {eligible.count()}')

for e in eligible:
    print(f'\n=== Reward Event ID: {e.id} ===')
    print(f'  Actor Role: {e.actor_role}')
    print(f'  Trigger: {e.trigger}')
    print(f'  Referee CONFIO: {e.referee_confio}')
    print(f'  Referrer CONFIO: {e.referrer_confio}')
    print(f'  Reward TX ID: {e.reward_tx_id}')
    print(f'  Referral: {e.referral}')

    if not e.reward_tx_id:
        print(f'\n  ⚠️  This reward needs to be synced to the blockchain')
        print(f'  Creating on-chain reward box...')

        # Initialize rewards service
        rewards_service = RewardsService()

        # Get the referrer from the referral relationship
        referrer_address = None
        if e.referral:
            if e.actor_role == 'referee':
                # User is the referee, get the referrer
                referrer = e.referral.referrer
            else:
                # User is the referrer, get the referee
                referrer = e.referral.referred_user

            if referrer and referrer.algorand_address:
                referrer_address = referrer.algorand_address

        # Calculate amounts in micro units
        referee_confio_micro = int(e.referee_confio * Decimal('1000000'))
        referrer_confio_micro = int(e.referrer_confio * Decimal('1000000'))

        # Convert to cUSD at $0.25 per CONFIO
        cusd_micro = referee_confio_micro * 250_000 // 1_000_000

        print(f'  Referee CONFIO: {e.referee_confio} ({referee_confio_micro} micro-CONFIO)')
        print(f'  Equivalent cUSD: ${cusd_micro / 1_000_000} ({cusd_micro} micro-cUSD)')

        if referrer_confio_micro > 0:
            print(f'  Referrer CONFIO: {e.referrer_confio} ({referrer_confio_micro} micro-CONFIO)')
            print(f'  Referrer Address: {referrer_address}')

        try:
            # Sync to blockchain
            result = rewards_service.mark_eligibility(
                user_address=user.algorand_address,
                reward_cusd_micro=cusd_micro,
                referee_confio_micro=referee_confio_micro,
                referrer_confio_micro=referrer_confio_micro,
                referrer_address=referrer_address,
            )

            print(f'\n  ✅ Success!')
            print(f'     Transaction ID: {result.txid}')
            print(f'     Round: {result.round}')

            # Mark as synced by storing the transaction ID
            e.reward_tx_id = result.txid
            e.save()
            print(f'     Marked as synced in database')

        except Exception as sync_error:
            print(f'\n  ❌ Error syncing to blockchain: {sync_error}')
            import traceback
            traceback.print_exc()
    else:
        print(f'  ✓ Already synced to blockchain (TX: {e.reward_tx_id})')

print('\n=== Done ===')
