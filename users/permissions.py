"""
Permission checking utilities for business employees
"""
from django.core.exceptions import PermissionDenied
from .models import Account
from .models_employee import BusinessEmployee


def get_employee_context(user, business):
    """
    Get the employee context for a user and business.
    Returns None if user is the business owner (has full permissions).
    Returns BusinessEmployee instance if user is an employee.
    Raises PermissionDenied if user has no access to the business.
    """
    if not user or not user.is_authenticated:
        raise PermissionDenied("Authentication required")
    
    # Check if user owns the business
    if business.accounts.filter(user=user, account_type='business').exists():
        return None  # Owner has full permissions
    
    # Check if user is an employee
    employee = BusinessEmployee.objects.filter(
        business=business,
        user=user,
        is_active=True,
        deleted_at__isnull=True
    ).first()
    
    if not employee:
        raise PermissionDenied("You don't have access to this business")
    
    return employee


def check_employee_permission(user, business, permission_name):
    """
    Check if a user has a specific permission for a business.
    Returns True if user is owner or has the permission.
    Raises PermissionDenied if user doesn't have access.
    """
    employee = get_employee_context(user, business)
    
    # Owner has all permissions
    if employee is None:
        return True
    
    # Check employee permission
    if not employee.has_permission(permission_name):
        raise PermissionDenied(f"You don't have permission to {permission_name.replace('_', ' ')}")
    
    return True


def get_user_permissions_for_business(user, business):
    """
    Get all permissions for a user in a business context.
    Returns a dict of permission_name: bool
    """
    try:
        employee = get_employee_context(user, business)
    except PermissionDenied:
        # No access at all
        return {perm: False for perm in BusinessEmployee.DEFAULT_PERMISSIONS['cashier'].keys()}
    
    # Owner has all permissions
    if employee is None:
        return {perm: True for perm in BusinessEmployee.DEFAULT_PERMISSIONS['owner'].keys()}
    
    # Return employee's effective permissions
    return employee.get_effective_permissions()


class PermissionRequiredMixin:
    """
    Mixin for GraphQL mutations that require permission checks.
    """
    required_permission = None
    
    def check_permission(self, user, business):
        if self.required_permission:
            check_employee_permission(user, business, self.required_permission)