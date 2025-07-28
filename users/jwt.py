from graphql_jwt.utils import jwt_encode, jwt_decode
from graphql_jwt.exceptions import PermissionDenied
from graphql_jwt.shortcuts import create_refresh_token
from datetime import datetime, timedelta
import logging
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)

def jwt_payload_handler(*args, **kwargs):
    """Add auth_token_version and account context to the JWT payload
    
    This function supports both old and new versions of django-graphql-jwt:
    - Old version: only passes user as argument
    - New version: passes user and context as arguments
    """
    # Handle both calling conventions
    if len(args) == 1:
        user = args[0]
        context = kwargs.get('context', None)
    elif len(args) == 2:
        user = args[0]
        context = args[1]
    else:
        raise ValueError("jwt_payload_handler expects 1 or 2 positional arguments")
    logger.info(f"jwt_payload_handler called with user: id={user.id}, username={user.username}, auth_token_version={getattr(user, 'auth_token_version', None)}")
    
    # Ensure user has auth_token_version
    if not hasattr(user, 'auth_token_version'):
        user.auth_token_version = 1
        user.save()
        logger.info(f"Set initial auth_token_version for user: {user.id}")
    
    # Get user ID and username
    user_id = user.id
    username = user.get_username()
    auth_token_version = user.auth_token_version
    
    # Get active account context from request if available
    account_type = 'personal'
    account_index = 0
    business_id = None
    
    if context and hasattr(context, 'active_account_type'):
        account_type = context.active_account_type
        account_index = context.active_account_index
        
        # Check if business_id is directly provided in context (for employee access)
        if hasattr(context, 'active_business_id') and context.active_business_id:
            business_id = str(context.active_business_id)
            logger.info(f"Using business_id from context: {business_id}")
        # If it's a business account and no business_id provided, get it from the account
        elif account_type == 'business':
            try:
                from users.models import Account
                account = Account.objects.get(
                    user=user,
                    account_type='business',
                    account_index=account_index
                )
                if account.business:
                    business_id = str(account.business.id)
            except Account.DoesNotExist:
                logger.warning(f"Business account not found for user {user_id} with index {account_index}")
    
    logger.info(f"User details - id: {user_id}, username: {username}, auth_token_version: {auth_token_version}")
    logger.info(f"Account context - type: {account_type}, index: {account_index}, business_id: {business_id}")
    
    # Get current timestamp
    now = datetime.utcnow()
    
    # Create the payload with all required fields
    payload = {
        'user_id': user_id,
        'username': username,
        'origIat': int(now.timestamp()),  # Convert to timestamp
        'auth_token_version': auth_token_version,
        'exp': int((now + timedelta(hours=1)).timestamp()),  # 1 hour for access token
        'type': 'access',  # Indicate this is an access token
        # Account context fields
        'account_type': account_type,
        'account_index': account_index,
        'business_id': business_id  # Will be None for personal accounts
    }
    logger.info(f"Generated JWT payload: {payload}")
    return payload


# Wrapper function for backward compatibility with older django-graphql-jwt versions
def jwt_payload_handler_legacy(user):
    """Legacy version that only accepts user argument"""
    return jwt_payload_handler(user, context=None)

def refresh_token_payload_handler(user, account_type='personal', account_index=0, business_id=None):
    """Generate a refresh token payload with longer expiration and account context"""
    now = datetime.utcnow()
    payload = {
        'user_id': user.id,
        'username': user.get_username(),
        'origIat': int(now.timestamp()),
        'auth_token_version': user.auth_token_version,
        'exp': int((now + timedelta(days=365)).timestamp()),  # 1 year for refresh token
        'type': 'refresh',  # Indicate this is a refresh token
        # Account context fields
        'account_type': account_type,
        'account_index': account_index,
        'business_id': business_id
    }
    return payload

def verify_auth_token_version(token):
    """Verify that the token's auth_token_version matches the user's current version"""
    try:
        logger.info("Verifying JWT token...")
        payload = jwt_decode(token)
        logger.info("Token decoded successfully. Payload: %s", payload)
        
        user_id = payload.get('user_id')
        token_version = payload.get('auth_token_version')
        
        if not user_id:
            logger.error("No user_id in token payload")
            raise PermissionDenied('Invalid token payload: missing user_id')
            
        if not token_version:
            logger.error("No auth_token_version in token payload")
            raise PermissionDenied('Invalid token payload: missing auth_token_version')
            
        User = get_user_model()
        try:
            user = User.objects.get(id=user_id)
            logger.info(f"Found user: id={user.id}, username={user.username}, auth_token_version={user.auth_token_version}")
        except User.DoesNotExist:
            logger.error(f"User not found: id={user_id}")
            raise PermissionDenied('User not found')
            
        if user.auth_token_version != token_version:
            logger.error(f"Token version mismatch: token={token_version}, user={user.auth_token_version}")
            raise PermissionDenied('Token version mismatch')
            
        logger.info("Token verification successful")
        return payload
        
    except Exception as e:
        logger.error(f"Token verification failed: {str(e)}")
        raise PermissionDenied(str(e)) 