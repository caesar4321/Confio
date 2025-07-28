"""
JWT Context Extraction Utilities

This module provides utilities to extract business context from JWT tokens
for GraphQL queries that should automatically use the user's active account context.
"""

import logging
from graphql_jwt.utils import jwt_decode
from graphql_jwt.exceptions import PermissionDenied

logger = logging.getLogger(__name__)

# Role-based permission matrix - defines what each role can do
# This is a negative-check system: if not explicitly allowed here, it's denied
# Owners bypass this check and have all permissions
ROLE_PERMISSIONS = {
    'admin': {
        # Admin can do most things except delete business
        'accept_payments', 'view_transactions', 'view_balance', 'send_funds',
        'manage_employees', 'view_business_address', 'view_analytics',
        'edit_business_info', 'manage_bank_accounts', 'manage_p2p',
        'create_invoices', 'manage_invoices', 'export_data'
    },
    'manager': {
        # Manager has operational permissions but can't manage employees or edit business
        'accept_payments', 'view_transactions', 'view_balance', 'send_funds',
        'view_business_address', 'view_analytics', 'manage_bank_accounts',
        'manage_p2p', 'create_invoices', 'manage_invoices', 'export_data'
    },
    'cashier': {
        # Cashier can only handle payments and view necessary information
        'accept_payments', 'view_transactions', 'view_balance', 
        'create_invoices', 'view_business_address'
    }
}

def check_role_permission(role, permission):
    """
    Check if a role has a specific permission.
    Owners always return True, others use negative-check.
    
    Args:
        role: The employee role (owner, admin, manager, cashier)
        permission: The permission to check
        
    Returns:
        bool: True if allowed, False if denied
    """
    if role == 'owner':
        return True
    
    # Negative check - must be explicitly allowed
    allowed_permissions = ROLE_PERMISSIONS.get(role, set())
    return permission in allowed_permissions

def get_jwt_business_context_with_validation(info, required_permission=None):
    """
    Extract business context from JWT token and validate access through BusinessEmployee.
    This ensures that for business accounts, the user has proper access rights.
    
    Args:
        info: GraphQL info object
        required_permission: Optional permission to check (e.g., 'view_balance', 'accept_payments')
                           Pass None for read-only operations that don't require permission checks
    
    Returns:
        dict: Contains 'business_id', 'account_type', 'account_index', 'user_id', 'employee_record'
        None: If no valid JWT context found, access denied, or permission check fails
    """
    # Extract JWT context
    try:
        # Get the request from GraphQL info
        request = info.context
        if not hasattr(request, 'META'):
            logger.warning("No request META found in GraphQL context")
            return None
            
        # Get authorization header
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('JWT '):
            logger.warning("No JWT token found in Authorization header")
            return None
            
        # Extract token
        token = auth_header[4:]  # Remove 'JWT ' prefix
        
        # Decode JWT payload
        payload = jwt_decode(token)
        
        # Extract context information
        jwt_context = {
            'user_id': payload.get('user_id'),
            'account_type': payload.get('account_type', 'personal'),
            'account_index': payload.get('account_index', 0),
            'business_id': payload.get('business_id'),  # Will be None for personal accounts
        }
        
        logger.info(f"Extracted JWT context: {jwt_context}")
        logger.info(f"JWT business_id type: {type(payload.get('business_id'))}, value: {payload.get('business_id')}")
        
    except Exception as e:
        logger.error(f"Error extracting JWT business context: {str(e)}")
        return None
    
    if not jwt_context:
        return None
    
    # Get the authenticated user
    user = info.context.user
    if not user or not user.is_authenticated:
        return None
    
    # For business accounts, validate access through BusinessEmployee
    if jwt_context['account_type'] == 'business' and jwt_context['business_id']:
        from .models_employee import BusinessEmployee
        
        logger.info(f"Validating business access: user_id={user.id}, business_id={jwt_context['business_id']}")
        
        # Check user's relationship to this business
        employee_record = BusinessEmployee.objects.filter(
            user=user,
            business_id=jwt_context['business_id'],
            deleted_at__isnull=True
        ).first()
        
        if not employee_record:
            logger.warning(f"User {user.id} has no relation to business {jwt_context['business_id']} - access denied")
            return None
        
        logger.info(f"Found employee record: role={employee_record.role}, business_name={employee_record.business.name}")
        
        # Add employee record to context for permission checking
        jwt_context['employee_record'] = employee_record
        
        # If a specific permission is required, check it
        if required_permission:
            if not check_role_permission(employee_record.role, required_permission):
                logger.warning(f"User {user.id} with role {employee_record.role} lacks permission '{required_permission}'")
                return None
    
    return jwt_context

def require_business_context(info):
    """
    Extract business context and require that it's a business account.
    Also validates access through BusinessEmployee relation.
    
    Raises:
        PermissionDenied: If not a business account, no valid context, or no access
        
    Returns:
        dict: Business context with guaranteed business_id and employee_record
    """
    context = get_jwt_business_context_with_validation(info)
    
    if not context:
        raise PermissionDenied("Invalid or missing JWT token or no access to business")
        
    if context['account_type'] != 'business' or not context['business_id']:
        raise PermissionDenied("This query requires a business account context")
        
    return context

def get_user_business_id(info):
    """
    Get the business_id from JWT context if available.
    
    Returns:
        str: business_id if in business context
        None: if in personal context or no valid JWT
    """
    context = get_jwt_business_context_with_validation(info, required_permission=None)
    return context.get('business_id') if context else None

def validate_business_access(info, business_id):
    """
    Validate that the user has access to the specified business.
    Uses BusinessEmployee relation to verify access rights.
    
    Args:
        info: GraphQL info object
        business_id: Business ID to validate access for
        
    Returns:
        bool: True if user has access, False otherwise
    """
    try:
        user = info.context.user
        if not user.is_authenticated:
            return False
        
        from .models_employee import BusinessEmployee
        
        # Check user's relationship to this business through BusinessEmployee
        employee_record = BusinessEmployee.objects.filter(
            user=user,
            business_id=business_id,
            deleted_at__isnull=True
        ).exists()
        
        return employee_record
            
    except Exception as e:
        logger.error(f"Error validating business access: {str(e)}")
        return False

def require_business_permission(info, permission):
    """
    Extract business context, validate access, and check specific permission.
    This is the main function to use in resolvers/mutations that need permission checking.
    
    Args:
        info: GraphQL info object
        permission: The permission required (e.g., 'accept_payments', 'manage_employees')
        
    Raises:
        PermissionDenied: If access denied or permission not granted
        
    Returns:
        dict: Business context with employee_record and verified permission
    """
    context = get_jwt_business_context_with_validation(info)
    
    if not context:
        raise PermissionDenied("Invalid JWT token or no access to business")
    
    if context['account_type'] != 'business':
        raise PermissionDenied("This operation requires a business account")
    
    employee_record = context.get('employee_record')
    if not employee_record:
        raise PermissionDenied("No employee record found")
    
    # Check permission using role-based negative check
    if not check_role_permission(employee_record.role, permission):
        raise PermissionDenied(f"Your role ({employee_record.role}) does not have permission to {permission}")
    
    return context