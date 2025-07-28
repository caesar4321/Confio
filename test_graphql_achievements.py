#!/usr/bin/env python3

import os
import sys
import django

# Add project root to path  
sys.path.append('/Users/julian/Confio')

# Set up Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from graphene.test import Client
from config.schema import schema
from users.models import AchievementType

def test_graphql_achievements():
    client = Client(schema)
    
    print("=== Testing GET_ACHIEVEMENT_TYPES GraphQL Query ===")
    
    query = """
    query {
      achievementTypes {
        id
        slug  
        name
        description
        category
        iconEmoji
        confioReward
        displayOrder
      }
    }
    """
    
    try:
        result = client.execute(query)
        print("GraphQL Query Result:")
        
        if 'errors' in result:
            print("Errors:", result['errors'])
        else:
            data = result.get('data', {})
            achievement_types = data.get('achievementTypes', [])
            print(f"Found {len(achievement_types)} achievement types")
            
            # Show first few achievements
            for achievement in achievement_types[:5]:
                print(f"- {achievement['name']} ({achievement['category']}) - {achievement['confioReward']} CONFIO")
                
            # Show categories
            categories = {}
            for achievement in achievement_types:
                cat = achievement['category']
                if cat not in categories:
                    categories[cat] = 0
                categories[cat] += 1
                
            print("\nCategories:")
            for cat, count in categories.items():
                print(f"- {cat}: {count} achievements")
                
    except Exception as e:
        print(f"Error executing GraphQL query: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_graphql_achievements()