import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models_employee import BusinessEmployee
from users.models import Account

# Get all employees for Business ID 18 (Sabor de Chicha)
business_id = 18

employees = BusinessEmployee.objects.filter(
    business_id=business_id,
    deleted_at__isnull=True
).select_related('user', 'business').order_by('role', 'created_at')

print(f"Business: Sabor de Chicha")
print(f"Total employees: {employees.count()}\n")

print("="*70)
print("DETAILED ACCOUNT CHECK FOR DELEGATE SELECTION")
print("="*70)

for emp in employees:
    print(f"\n{emp.user.get_full_name() or emp.user.username} (User ID: {emp.user_id})")
    print(f"  Role: {emp.role}")
    
    # Get ALL accounts for this user
    all_accounts = Account.objects.filter(
        user=emp.user,
        deleted_at__isnull=True
    )
    
    print(f"  Total accounts: {all_accounts.count()}")
    
    for acc in all_accounts:
        print(f"    - Type: {acc.account_type}, ID: {acc.id}")
        print(f"      Index: {acc.account_index}")
        print(f"      Algorand Address: {acc.algorand_address or 'MISSING!'}")
    
    # Check what the frontend query would return
    personal_accounts = emp.user.accounts.filter(
        account_type='personal',
        deleted_at__isnull=True
    )
    
    print(f"  Personal accounts found: {personal_accounts.count()}")
    
    if personal_accounts.exists():
        personal = personal_accounts.first()
        print(f"    First personal account ID: {personal.id}")
        print(f"    Algorand address: {personal.algorand_address or 'MISSING!'}")
        
        # This is what the frontend uses for delegate selection
        has_address = bool(personal.algorand_address)
        print(f"    HAS ALGORAND ADDRESS: {has_address}")
        
        if not has_address:
            print(f"    ⚠️  PROBLEM: Missing algorand_address - will be filtered out!")
