from django.utils.functional import SimpleLazyObject
from graphql_jwt.utils import get_http_authorization
from .jwt import verify_auth_token_version
from graphql_jwt.exceptions import PermissionDenied
import logging
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger(__name__)

class ActiveAccountMiddleware:
    """Middleware to set active account information on the request context"""
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Set default values
        request.active_account_type = 'personal'
        request.active_account_index = 0
        request.active_business_id = None
        
        # Try to extract account context from JWT token
        auth_header = request.headers.get('Authorization', '')
        if auth_header and auth_header.startswith('JWT'):
            try:
                from graphql_jwt.utils import jwt_decode
                token = auth_header[4:] if auth_header.startswith('JWT ') else auth_header[3:]
                payload = jwt_decode(token)
                
                # Extract account context from JWT payload
                request.active_account_type = payload.get('account_type', 'personal')
                request.active_account_index = payload.get('account_index', 0)
                request.active_business_id = payload.get('business_id')
                
                logger.info(f"Account context from JWT - type: {request.active_account_type}, index: {request.active_account_index}, business_id: {request.active_business_id}")
            except Exception as e:
                logger.debug(f"Could not extract account context from JWT: {e}")
        
        # Fallback to headers for backward compatibility (will be removed later)
        if request.path == '/graphql/' and request.method == 'POST':
            # Read active account headers (deprecated)
            header_account_type = request.headers.get('X-Active-Account-Type')
            header_account_index = request.headers.get('X-Active-Account-Index')
            
            if header_account_type or header_account_index:
                logger.warning("DEPRECATED: Using X-Active-Account headers. Please update client to use JWT-based account context.")
                if header_account_type:
                    request.active_account_type = header_account_type
                if header_account_index:
                    try:
                        request.active_account_index = int(header_account_index)
                    except ValueError:
                        logger.warning(f"Invalid active account index: {header_account_index}")
        
        logger.info(f"Final account context - type: {request.active_account_type}, index: {request.active_account_index}, business_id: {request.active_business_id}")
        return self.get_response(request)

class AuthTokenVersionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip for admin and static/media URLs
        if request.path.startswith('/admin/') or request.path.startswith('/static/') or request.path.startswith('/media/'):
            return self.get_response(request)

        # Skip authentication for refreshToken mutation and legal document query
        if request.path == '/graphql/' and request.method == 'POST':
            try:
                import json
                body = request.body.decode('utf-8')
                data = json.loads(body)
                query = str(data.get('query', ''))
                if 'refreshToken' in query or 'legalDocument' in query:
                    logger.info("Skipping auth for refreshToken mutation or legal document query")
                    request.user = AnonymousUser()
                    return self.get_response(request)
            except Exception as e:
                logger.error(f"Error checking for refreshToken mutation or legal document query: {e}")

        # For all other requests, proceed with normal authentication
        logger.info("=== AuthTokenVersionMiddleware ===")
        
        # Get the Authorization header directly
        auth_header = request.headers.get('Authorization', '')
        logger.info("Authorization header: %s", auth_header)
        
        if auth_header and auth_header.startswith('JWT'):
            # Extract the token part
            token = auth_header[4:] if auth_header.startswith('JWT ') else auth_header[3:]
            logger.info("Found JWT token: %s...", token[:20])
            
            try:
                # Verify the token version
                payload = verify_auth_token_version(token)
                logger.info("Token verified successfully. Payload: %s", payload)
                
                # Set the user on the request
                from django.contrib.auth import get_user_model
                User = get_user_model()
                try:
                    user = User.objects.get(id=payload['user_id'])
                    request.user = user
                    logger.info("User set on request: %s", user)
                except User.DoesNotExist:
                    logger.error("User not found in database: id=%s", payload['user_id'])
                    # Set anonymous user instead of None
                    request.user = AnonymousUser()
                    # Log the full payload for debugging
                    logger.error("JWT payload: %s", payload)
                
            except PermissionDenied as e:
                logger.warning("Token verification failed: %s", str(e))
                # Set anonymous user instead of None
                request.user = AnonymousUser()
            except Exception as e:
                # Log other errors but don't expose them
                logger.error("JWT verification error: %s", str(e))
                # Set anonymous user instead of None
                request.user = AnonymousUser()
        else:
            logger.info("No JWT token found in Authorization header")
            request.user = AnonymousUser()
            
        logger.info("Request user after middleware: %s", request.user)
        logger.info("Is authenticated: %s", getattr(request.user, 'is_authenticated', None))
        logger.info("=== End AuthTokenVersionMiddleware ===")
        
        return self.get_response(request) 