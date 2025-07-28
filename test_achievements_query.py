#!/usr/bin/env python3

import os
import sys
import django

# Add project root to path
sys.path.append('/Users/julian/Confio')

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import AchievementType, UserAchievement
from django.contrib.auth import get_user_model

User = get_user_model()

def test_achievements():
    print("=== Achievement Types in Database ===")
    achievement_types = AchievementType.objects.all().order_by('display_order')
    
    for achievement in achievement_types:
        print(f"- {achievement.name} ({achievement.category}) - {achievement.confio_reward} CONFIO")
    
    print(f"\nTotal Achievement Types: {achievement_types.count()}")
    
    print("\n=== Categories ===")
    categories = AchievementType.objects.values_list('category', flat=True).distinct()
    for category in categories:
        count = AchievementType.objects.filter(category=category).count()
        print(f"- {category}: {count} achievements")
    
    print("\n=== User Achievements ===")
    user_achievements = UserAchievement.objects.all()
    print(f"Total User Achievements: {user_achievements.count()}")
    
    if user_achievements.exists():
        for ua in user_achievements[:5]:
            print(f"- {ua.user.username}: {ua.achievement_type.name} ({ua.status})")

if __name__ == "__main__":
    test_achievements()