#!/usr/bin/env python
"""Test script for CONFIO reward distribution system"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User, AchievementType, UserAchievement, ConfioRewardBalance
from django.utils import timezone

def test_confio_rewards():
    """Test the CONFIO reward distribution system"""
    
    # Get a test user (you can change this to any existing user)
    try:
        user = User.objects.first()
        if not user:
            print("No users found in database")
            return
    except Exception as e:
        print(f"Error getting user: {e}")
        return
    
    print(f"Testing with user: {user.username}")
    
    # Get or create CONFIO balance
    balance, created = ConfioRewardBalance.objects.get_or_create(
        user=user,
        defaults={'lock_until': timezone.now() + timezone.timedelta(days=365)}
    )
    
    print(f"\nCurrent CONFIO Balance:")
    print(f"  Total Earned: {balance.total_earned} CONFIO")
    print(f"  Total Locked: {balance.total_locked} CONFIO")
    print(f"  Achievement Rewards: {balance.achievement_rewards} CONFIO")
    print(f"  Daily Count: {balance.daily_reward_count}")
    print(f"  Daily Amount: {balance.daily_reward_amount} CONFIO")
    
    # Try to earn and claim a reward
    achievement_type = AchievementType.objects.filter(slug='welcome_signup').first()
    if achievement_type:
        print(f"\nTesting achievement: {achievement_type.name} ({achievement_type.confio_reward} CONFIO)")
        
        # Create or get user achievement
        user_achievement, created = UserAchievement.objects.get_or_create(
            user=user,
            achievement_type=achievement_type,
            defaults={'status': 'earned', 'earned_at': timezone.now()}
        )
        
        if created or user_achievement.status == 'pending':
            user_achievement.status = 'earned'
            user_achievement.earned_at = timezone.now()
            user_achievement.save()
            print("  Achievement marked as earned")
        
        # Try to claim reward
        if user_achievement.can_claim_reward:
            print("  Claiming reward...")
            success = user_achievement.claim_reward()
            if success:
                print("  ✅ Reward claimed successfully!")
                
                # Refresh balance
                balance.refresh_from_db()
                print(f"\nUpdated CONFIO Balance:")
                print(f"  Total Earned: {balance.total_earned} CONFIO")
                print(f"  Total Locked: {balance.total_locked} CONFIO")
                print(f"  Achievement Rewards: {balance.achievement_rewards} CONFIO")
            else:
                print("  ❌ Failed to claim reward")
        else:
            print("  ❌ Cannot claim reward (already claimed or not eligible)")
    else:
        print("No achievement types found. Run 'python manage.py create_achievement_types' first")
    
    # Show recent transactions
    print("\nRecent CONFIO Transactions:")
    transactions = user.confio_reward_transactions.all()[:5]
    for tx in transactions:
        print(f"  {tx.created_at.strftime('%Y-%m-%d %H:%M')} - {tx.transaction_type}: {tx.amount} CONFIO - {tx.description}")

if __name__ == "__main__":
    test_confio_rewards()