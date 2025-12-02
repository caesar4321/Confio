import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User
from users.models_employee import BusinessEmployee

# Find the user
user = User.objects.filter(phone_number='9293993618').first()

if not user:
    print("User not found")
else:
    print(f"User ID: {user.id}, Username: {user.username}")
    
    # Get all employee records for this user
    records = BusinessEmployee.objects.filter(
        user=user,
        deleted_at__isnull=True
    ).select_related('business')
    
    print(f"\nTotal employee records: {records.count()}\n")
    
    for rec in records:
        print(f"Record ID: {rec.id}")
        print(f"  Business ID: {rec.business_id}")
        print(f"  Business Name: {rec.business.name}")
        print(f"  User ID: {rec.user_id}")
        print(f"  Role: {rec.role}")
        print(f"  Active: {rec.is_active}")
        print(f"  Created: {rec.created_at}")
        print()
