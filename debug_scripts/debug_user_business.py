import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User, Business, Account
from users.models_employee import BusinessEmployee

# Find the user's business (assuming you're testing with your own account)
# Replace with your phone number or username
user = User.objects.filter(phone_number='9293993618').first()

if not user:
    print("User not found. Please update the script with your phone number or username.")
else:
    print(f"User: {user.username} ({user.get_full_name()})")
    
    # Find business accounts
    business_accounts = Account.objects.filter(
        user=user,
        account_type='business',
        deleted_at__isnull=True
    )
    
    print(f"\nFound {business_accounts.count()} business account(s)")
    
    for acc in business_accounts:
        business = acc.business
        print(f"\n{'='*60}")
        print(f"Business: {business.name} (ID: {business.id})")
        print(f"{'='*60}")
        
        # Get all employees
        employees = BusinessEmployee.objects.filter(
            business=business,
            deleted_at__isnull=True
        ).select_related('user')
        
        print(f"\nTotal employees: {employees.count()}")
        for emp in employees:
            personal_account = Account.objects.filter(
                user=emp.user,
                account_type='personal',
                deleted_at__isnull=True
            ).first()
            
            print(f"\n  - {emp.user.get_full_name() or emp.user.username}")
            print(f"    Role: {emp.role}")
            print(f"    Active: {emp.is_active}")
            print(f"    Has personal account: {personal_account is not None}")
            if personal_account:
                print(f"    Personal account ID: {personal_account.id}")
                print(f"    Algorand address: {personal_account.algorand_address or 'None'}")
