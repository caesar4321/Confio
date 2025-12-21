"""
User authentication and authorization middleware.

SECURITY UPDATE: ActiveAccountMiddleware has been removed.
- Previously: Account context came from X-Active-Account-Type/Index headers (insecure)
- Now: All account context comes from JWT tokens via jwt_context functions
- This prevents client-side manipulation of business context
- All mutations/queries now use require_authenticated_context() for secure context
"""

from django.utils.functional import SimpleLazyObject
from graphql_jwt.utils import get_http_authorization
from .jwt import verify_auth_token_version
from graphql_jwt.exceptions import PermissionDenied
import logging
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger(__name__)

class AuthTokenVersionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip for admin and static/media URLs
        # Skip for admin, account (2FA), and static/media URLs
        if (request.path.startswith('/admin/') or 
            request.path.startswith('/confio-control-panel/') or 
            request.path.startswith('/account/') or 
            request.path.startswith('/static/') or 
            request.path.startswith('/media/')):
            return self.get_response(request)

        # Skip authentication only for explicitly whitelisted operations (strict)
        if request.path == '/graphql/' and request.method == 'POST':
            try:
                import json
                body = request.body.decode('utf-8')
                data = json.loads(body)
                op_name = str(data.get('operationName') or '').strip()
                if op_name in ('refreshToken', 'legalDocument'):
                    logger.info("Skipping auth for whitelisted public operation: %s", op_name)
                    request.user = AnonymousUser()
                    return self.get_response(request)
            except Exception as e:
                logger.error(f"Error checking for public GraphQL operation: {e}")

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
