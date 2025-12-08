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
).select_related('user', 'business').order_by('role', 'created_at')

print(f"Business: {employees.first().business.name if employees.exists() else 'Not found'}")
print(f"Total employees: {employees.count()}\n")

for emp in employees:
    print(f"Employee: {emp.user.get_full_name() or emp.user.username}")
    print(f"  ID: {emp.id}")
    print(f"  User ID: {emp.user_id}")
    print(f"  Role: {emp.role}")
    print(f"  Active: {emp.is_active}")
    
    # Check personal account
    personal_accounts = emp.user.accounts.filter(account_type='personal', deleted_at__isnull=True)
    has_personal = personal_accounts.exists()
    print(f"  Has personal account: {has_personal}")
    
    # Check delegate eligibility
    role_lower = (emp.role or '').lower()
    is_eligible = role_lower != 'cashier' and has_personal
    print(f"  Eligible delegate: {is_eligible} (role={emp.role}, cashier={role_lower == 'cashier'})")
    print()
