from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from django.utils.deprecation import MiddlewareMixin
from urllib.parse import parse_qs
import jwt
from django.conf import settings

User = get_user_model()

@database_sync_to_async
def get_user_and_context_from_token(token):
    """Get user and account context from JWT token"""
    try:
        # Remove 'JWT ' prefix if present
        if token.startswith('JWT '):
            token = token[4:]
        
        # Decode the token using proper JWT verification
        from users.jwt import verify_auth_token_version
        payload = verify_auth_token_version(token)
        
        user_id = payload.get('user_id')
        
        if user_id:
            user = User.objects.get(id=user_id)
            
            # Extract account context from JWT
            account_context = {
                'account_type': payload.get('account_type', 'personal'),
                'account_index': payload.get('account_index', 0),
                'business_id': payload.get('business_id')
            }
            
            return user, account_context
        return AnonymousUser(), None
    except Exception as e:
        print(f"WebSocket JWT verification failed: {e}")
        return AnonymousUser(), None

class JWTAuthMiddleware(BaseMiddleware):
    """
    Custom middleware to authenticate WebSocket connections using JWT tokens
    """
    async def __call__(self, scope, receive, send):
        # Close old database connections to prevent usage of timed out connections
        from django.db import close_old_connections
        close_old_connections()

        # Get token from query string
        query_string = scope.get('query_string', b'').decode()
        query_params = parse_qs(query_string)
        token = query_params.get('token', [None])[0]
        
        if token:
            user, account_context = await get_user_and_context_from_token(token)
            scope['user'] = user
            scope['account_context'] = account_context
        else:
            scope['user'] = AnonymousUser()
            scope['account_context'] = None
        
        return await super().__call__(scope, receive, send)