import os
import django
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from users.models import User, Business, Account
from users.models_employee import BusinessEmployee
from users.graphql_employee import EmployeeQueries
from django.test import RequestFactory

def debug_delegates():
    # 1. Create a test user (owner)
    owner_email = f"owner_{os.getpid()}@example.com"
    owner = User.objects.create(
        username=f"owner_{os.getpid()}",
        email=owner_email,
        phone_number=f"555{os.getpid()}",
        phone_country="US",
        firebase_uid=f"uid_owner_{os.getpid()}"
    )
    
    # 2. Create a business
    business = Business.objects.create(
        name="Debug Business",
        category="retail"
    )
    
    # 3. Create business account
    Account.objects.create(
        user=owner,
        account_type='business',
        business=business
    )
    
    # Create personal account for owner
    Account.objects.create(
        user=owner,
        account_type='personal',
        account_index=0
    )
    
    # 4. Create owner employee record (simulating schema logic)
    BusinessEmployee.objects.create(
        business=business,
        user=owner,
        role='owner',
        hired_by=owner
    )
    
    # 5. Create another employee
    employee_user = User.objects.create(
        username=f"emp_{os.getpid()}",
        email=f"emp_{os.getpid()}@example.com",
        phone_number=f"556{os.getpid()}",
        phone_country="US",
        firebase_uid=f"uid_emp_{os.getpid()}"
    )
    
    BusinessEmployee.objects.create(
        business=business,
        user=employee_user,
        role='manager', # Managers are eligible delegates
        hired_by=owner
    )
    
    # 6. Mock info object with context
    class MockContext:
        def __init__(self, user):
            self.user = user
            
    class MockInfo:
        def __init__(self, context):
            self.context = context

    mock_info = MockInfo(MockContext(owner))
    
    # Patch require_business_context
    from unittest.mock import patch
    
    mock_jwt_context = {
        'business_id': business.id,
        'account_type': 'business',
        'user_id': owner.id
    }
    
    with patch('users.graphql_employee.require_business_context', return_value=mock_jwt_context):
        # 7. Call resolve_current_business_employees
        queries = EmployeeQueries()
        employees = queries.resolve_current_business_employees(mock_info)
        
        print(f"Total employees found: {len(employees)}")
        for emp in employees:
            print(f"Employee: {emp.user.username}, Role: {emp.role}")
            for acc in emp.user.accounts.all():
                print(f"  - Account: {acc.account_type}")

if __name__ == "__main__":
    try:
        debug_delegates()
    except Exception as e:
        print(f"Error: {e}")
