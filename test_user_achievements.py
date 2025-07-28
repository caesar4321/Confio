#!/usr/bin/env python
"""Test user achievements query"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User, UserAchievement, AchievementType

# Get the user
username = '3db2c9a11e2c156'
user = User.objects.get(username=username)

print(f"Testing achievements for user: {username}")
print(f"User ID: {user.id}")
print(f"Firebase UID: {user.firebase_uid}")
print()

# Get all achievement types
achievement_types = AchievementType.objects.filter(is_active=True)
print(f"Total achievement types: {achievement_types.count()}")

# Get user achievements
user_achievements = UserAchievement.objects.filter(user=user).select_related('achievement_type')
print(f"\nUser achievements: {user_achievements.count()}")

# Group by status
by_status = {}
for ua in user_achievements:
    status = ua.status
    if status not in by_status:
        by_status[status] = []
    by_status[status].append(ua)

print("\nBy status:")
for status, achievements in by_status.items():
    print(f"  {status}: {len(achievements)}")
    if status in ['earned', 'claimed']:
        for a in achievements[:3]:  # Show first 3
            print(f"    - {a.achievement_type.name} ({a.achievement_type.confio_reward} CONFIO)")

# Test the GraphQL query logic
print("\n\nTesting GraphQL query logic:")
print("userAchievements query would return:")

# This mimics what the GraphQL resolver does
queryset = UserAchievement.objects.filter(user=user)
print(f"  Total: {queryset.count()}")
print(f"  Earned: {queryset.filter(status='earned').count()}")
print(f"  Claimed: {queryset.filter(status='claimed').count()}")

# Check if achievements have all required fields
print("\nChecking data integrity:")
for ua in user_achievements[:3]:
    print(f"\nAchievement: {ua.achievement_type.name}")
    print(f"  ID: {ua.id}")
    print(f"  Status: {ua.status}")
    print(f"  Achievement Type ID: {ua.achievement_type.id}")
    print(f"  Achievement Type Slug: {ua.achievement_type.slug}")
    print(f"  Category: {ua.achievement_type.category}")
    print(f"  CONFIO Reward: {ua.achievement_type.confio_reward}")