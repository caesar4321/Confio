from graphql_jwt.utils import jwt_encode, jwt_decode
from graphql_jwt.exceptions import PermissionDenied
from graphql_jwt.shortcuts import create_refresh_token
from datetime import datetime, timedelta
import logging
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)

def jwt_payload_handler(user, context=None):
    """Add auth_token_version to the JWT payload"""
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
    
    logger.info(f"User details - id: {user_id}, username: {username}, auth_token_version: {auth_token_version}")
    
    # Get current timestamp
    now = datetime.utcnow()
    
    # Create the payload with all required fields
    payload = {
        'user_id': user_id,
        'username': username,
        'origIat': int(now.timestamp()),  # Convert to timestamp
        'auth_token_version': auth_token_version,
        'exp': int((now + timedelta(hours=1)).timestamp()),  # 1 hour for access token
        'type': 'access'  # Indicate this is an access token
    }
    logger.info(f"Generated JWT payload: {payload}")
    return payload

def refresh_token_payload_handler(user):
    """Generate a refresh token payload with longer expiration"""
    now = datetime.utcnow()
    payload = {
        'user_id': user.id,
        'username': user.get_username(),
        'origIat': int(now.timestamp()),
        'auth_token_version': user.auth_token_version,
        'exp': int((now + timedelta(days=365)).timestamp()),  # 1 year for refresh token
        'type': 'refresh'  # Indicate this is a refresh token
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