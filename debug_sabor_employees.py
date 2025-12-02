import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models_employee import BusinessEmployee

# Get all employees for Business ID 18 (Sabor de Chicha)
business_id = 18

employees = BusinessEmployee.objects.filter(
    business_id=business_id,
    deleted_at__isnull=True
).select_related('user', 'business')

print(f"Business: {employees.first().business.name if employees.exists() else 'Not found'}")
print(f"Total employees: {employees.count()}\n")

for emp in employees:
    print(f"Employee: {emp.user.get_full_name() or emp.user.username}")
    print(f"  ID: {emp.id}")
    print(f"  User ID: {emp.user_id}")
    print(f"  Role: {emp.role}")
    print(f"  Active: {emp.is_active}")
    print(f"  Created: {emp.created_at}")
    
    # Check personal account
    personal_accounts = emp.user.accounts.filter(account_type='personal', deleted_at__isnull=True)
    print(f"  Personal accounts: {personal_accounts.count()}")
    for acc in personal_accounts:
        print(f"    - Account ID: {acc.id}, Address: {acc.algorand_address or 'None'}")
    print()

# Check eligibility for delegates (non-cashier with personal account)
print("\n" + "="*60)
print("DELEGATE ELIGIBILITY CHECK")
print("="*60)

for emp in employees:
    role = (emp.role or '').toLowerCase()
    has_personal = emp.user.accounts.filter(account_type='personal', deleted_at__isnull=True).exists()
    is_eligible = role != 'cashier' and has_personal
    
    print(f"\n{emp.user.get_full_name() or emp.user.username}:")
    print(f"  Role: {emp.role} (cashier={role == 'cashier'})")
    print(f"  Has personal account: {has_personal}")
    print(f"  ELIGIBLE DELEGATE: {is_eligible}")
