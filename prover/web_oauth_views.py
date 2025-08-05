"""
Web-based OAuth views for Aptos Keyless Account
Handles the OAuth flow with proper nonce support
"""
import json
import asyncio
import logging
from django.http import JsonResponse, HttpResponseRedirect
from django.views import View
from django.shortcuts import render
from django.urls import reverse
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from urllib.parse import urlencode, quote
import uuid
import jwt as pyjwt
from datetime import datetime, timedelta
from .aptos_keyless_service import keyless_service
from django.http import HttpResponse
import firebase_admin
from firebase_admin import auth as firebase_auth
from users.models import User, Account
from .utils.keyless_pepper import generate_keyless_pepper

# Get logger
logger = logging.getLogger(__name__)

@method_decorator(csrf_exempt, name='dispatch')
class AptosOAuthStartView(View):
    """Start the OAuth flow for Aptos Keyless"""
    
    def post(self, request):
        """Handle POST request with client-generated ephemeral key"""
        import json
        try:
            data = json.loads(request.body)
            provider = data.get('provider', 'google')
            ephemeral_key = data.get('ephemeralKeyPair')
            device_fingerprint = data.get('deviceFingerprint')
            
            if ephemeral_key:
                logger.info(f"Using client-generated ephemeral key with nonce: {ephemeral_key.get('nonce')}")
            
            if device_fingerprint:
                logger.info(f"Received device fingerprint data")
            
            return self._handle_oauth_start(request, provider, ephemeral_key, device_fingerprint)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON in request body'}, status=400)
    
    def get(self, request):
        """Handle GET request (legacy, server-generated ephemeral key)"""
        provider = request.GET.get('provider', 'google')
        return self._handle_oauth_start(request, provider, None, None)
    
    def _handle_oauth_start(self, request, provider, ephemeral_key=None, device_fingerprint=None):
        
        # Use configurable base URL for OAuth callbacks (for ngrok in development)
        oauth_base_url = getattr(settings, 'OAUTH_BASE_URL', None)
        if oauth_base_url:
            redirect_uri = f"{oauth_base_url.rstrip('/')}{reverse('aptos_oauth_callback')}"
        else:
            redirect_uri = request.build_absolute_uri(reverse('aptos_oauth_callback'))
        
        # Check if OAuth credentials are configured
        if provider == 'google' and not settings.GOOGLE_OAUTH_CLIENT_ID:
            return JsonResponse({
                'error': 'Google OAuth not configured. Please set GOOGLE_OAUTH_CLIENT_ID in .env file'
            }, status=500)
        elif provider == 'apple' and not settings.APPLE_OAUTH_CLIENT_ID:
            return JsonResponse({
                'error': 'Apple OAuth not configured. Please set APPLE_OAUTH_CLIENT_ID in .env file'
            }, status=500)
        
        # Check for localhost with Apple Sign-In
        if provider == 'apple' and ('localhost' in request.get_host() or '127.0.0.1' in request.get_host()):
            return JsonResponse({
                'error': 'Apple Sign-In does not support localhost. Please use ngrok or deploy to a public domain.',
                'suggestion': 'Run: ngrok http 8000'
            }, status=400)
        
        # Generate ephemeral key pair if not provided by client
        if not ephemeral_key:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                # Server-side generation (not recommended for non-custodial)
                logger.warning("Generating ephemeral key on server - consider client-side generation for non-custodial approach")
                ephemeral_key = loop.run_until_complete(keyless_service.generate_ephemeral_key(24))
            finally:
                loop.close()
        else:
            logger.info("Using client-provided ephemeral key (non-custodial approach)")
        
        # Create a signed state token containing the ephemeral key
        import base64
        from django.core import signing
        
        state_data = {
            'ephemeral_key': ephemeral_key,
            'provider': provider,
            'device_fingerprint': device_fingerprint,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Sign and encode the state data
        state = signing.dumps(state_data, salt='aptos-oauth-state')
        
        # Log for debugging
        logger.info(f"Created OAuth state token for provider: {provider}")
        
        # Build OAuth URL with nonce from ephemeral key
        if provider == 'google':
            oauth_url = self._build_google_oauth_url(
                ephemeral_key['nonce'],
                redirect_uri,
                state
            )
        elif provider == 'apple':
            oauth_url = self._build_apple_oauth_url(
                ephemeral_key['nonce'],
                redirect_uri,
                state
            )
        else:
            return JsonResponse({'error': 'Invalid provider'}, status=400)
        
        # Return OAuth URL for mobile app to open in web view
        return JsonResponse({
            'oauth_url': oauth_url,
            'state': state,
            'ephemeral_key': {
                'keyId': ephemeral_key.get('keyId'),  # Include keyId if present
                'publicKey': ephemeral_key['publicKey'],
                'expiryDate': ephemeral_key['expiryDate'],
                'nonce': ephemeral_key['nonce']
            }
        })
    
    def _build_google_oauth_url(self, nonce, redirect_uri, state):
        """Build Google OAuth URL with custom nonce"""
        params = {
            'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': 'openid email profile',
            'nonce': nonce,
            'state': state,
            'prompt': 'select_account'
        }
        oauth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
        
        # Log the OAuth URL for debugging
        logger.info(f"Google OAuth URL: {oauth_url}")
        logger.info(f"Redirect URI: {redirect_uri}")
        logger.info(f"Client ID: {settings.GOOGLE_OAUTH_CLIENT_ID}")
        
        return oauth_url
    
    def _build_apple_oauth_url(self, nonce, redirect_uri, state):
        """Build Apple OAuth URL with custom nonce"""
        # For development, Apple doesn't accept localhost
        if 'localhost' in redirect_uri or '127.0.0.1' in redirect_uri:
            # Use the production URL or a placeholder
            # This will fail but at least show the proper error
            redirect_uri = 'https://confio.lat/prover/oauth/aptos/callback/'
        
        params = {
            'client_id': settings.APPLE_OAUTH_CLIENT_ID,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': 'email name',
            'nonce': nonce,
            'state': state,
            'response_mode': 'form_post'
        }
        return f"https://appleid.apple.com/auth/authorize?{urlencode(params)}"


    def _get_redirect_uri(self, request):
        """Get the redirect URI, using configured base URL if available"""
        oauth_base_url = getattr(settings, 'OAUTH_BASE_URL', None)
        if oauth_base_url:
            # Ensure HTTPS for OAuth (required by Google)
            oauth_base_url = oauth_base_url.replace('http://', 'https://')
            return f"{oauth_base_url.rstrip('/')}{reverse('aptos_oauth_callback')}"
        else:
            return request.build_absolute_uri(reverse('aptos_oauth_callback'))


@method_decorator(csrf_exempt, name='dispatch')
class AptosOAuthCallbackView(View):
    """Handle OAuth callback and derive Keyless account"""
    
    def _get_redirect_uri(self, request):
        """Get the redirect URI, using configured base URL if available"""
        oauth_base_url = getattr(settings, 'OAUTH_BASE_URL', None)
        if oauth_base_url:
            # Ensure HTTPS for OAuth (required by Google)
            oauth_base_url = oauth_base_url.replace('http://', 'https://')
            return f"{oauth_base_url.rstrip('/')}{reverse('aptos_oauth_callback')}"
        else:
            return request.build_absolute_uri(reverse('aptos_oauth_callback'))
    
    def post(self, request):
        # Apple uses POST for callback
        code = request.POST.get('code')
        state = request.POST.get('state')
        return self._handle_callback(request, code, state)
    
    def get(self, request):
        # Google uses GET for callback
        code = request.GET.get('code')
        state = request.GET.get('state')
        return self._handle_callback(request, code, state)
    
    def _handle_callback(self, request, code, state):
        from django.core import signing
        
        logger.info(f"OAuth callback received - code: {code[:10] if code else 'None'}..., state: {state[:20] if state else 'None'}...")
        
        if not code or not state:
            error_msg = f'Missing code or state. Code: {bool(code)}, State: {bool(state)}'
            logger.error(error_msg)
            # Return HTML page that redirects to app with error
            error_params = urlencode({
                'success': 'false',
                'error': error_msg
            })
            error_url = f'confio://oauth-callback?{error_params}'
            return HttpResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Authentication Error</title>
    <script>
        function redirectToApp() {{
            try {{ window.location.href = '{error_url}'; }} catch (e) {{}}
            setTimeout(function() {{ try {{ window.location.replace('{error_url}'); }} catch (e) {{}} }}, 100);
        }}
        redirectToApp();
    </script>
</head>
<body onload="redirectToApp()">
    <p>Authentication error. Redirecting to app...</p>
    <p><a href="{error_url}">Click here if not redirected</a></p>
</body>
</html>
            """, content_type='text/html')
        
        # Decode the state token to retrieve session data
        try:
            state_data = signing.loads(state, salt='aptos-oauth-state', max_age=3600)  # 1 hour max age
        except signing.SignatureExpired:
            logger.error("OAuth state token expired")
            error_params = urlencode({
                'success': 'false',
                'error': 'Authentication session expired. Please try signing in again.'
            })
            error_url = f'confio://oauth-callback?{error_params}'
            return HttpResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Authentication Error</title>
    <script>
        function redirectToApp() {{
            try {{ window.location.href = '{error_url}'; }} catch (e) {{}}
            setTimeout(function() {{ try {{ window.location.replace('{error_url}'); }} catch (e) {{}} }}, 100);
        }}
        redirectToApp();
    </script>
</head>
<body onload="redirectToApp()">
    <p>Authentication error. Redirecting to app...</p>
    <p><a href="{error_url}">Click here if not redirected</a></p>
</body>
</html>
            """, content_type='text/html')
        except signing.BadSignature:
            logger.error("Invalid OAuth state token")
            error_params = urlencode({
                'success': 'false',
                'error': 'Invalid authentication state. Please try signing in again.'
            })
            error_url = f'confio://oauth-callback?{error_params}'
            return HttpResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Authentication Error</title>
    <script>
        function redirectToApp() {{
            try {{ window.location.href = '{error_url}'; }} catch (e) {{}}
            setTimeout(function() {{ try {{ window.location.replace('{error_url}'); }} catch (e) {{}} }}, 100);
        }}
        redirectToApp();
    </script>
</head>
<body onload="redirectToApp()">
    <p>Authentication error. Redirecting to app...</p>
    <p><a href="{error_url}">Click here if not redirected</a></p>
</body>
</html>
            """, content_type='text/html')
        
        ephemeral_key = state_data['ephemeral_key']
        provider = state_data['provider']
        device_fingerprint = state_data.get('device_fingerprint')
        
        try:
            # Exchange code for tokens
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                if provider == 'google':
                    jwt_token = loop.run_until_complete(self._exchange_google_code(code, request))
                elif provider == 'apple':
                    jwt_token = loop.run_until_complete(self._exchange_apple_code(code, request))
                else:
                    return JsonResponse({'error': 'Invalid provider'}, status=400)
                
                # Log the JWT token for debugging
                logger.info(f"JWT token received: {jwt_token[:50] if jwt_token else 'None'}...")
                
                if not jwt_token:
                    logger.error("Failed to get JWT token from OAuth provider")
                    error_params = urlencode({
                        'success': 'false',
                        'error': 'Failed to authenticate with OAuth provider. Please check client credentials.'
                    })
                    error_url = f'confio://oauth-callback?{error_params}'
                    return HttpResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="0; url={error_url}">
    <script>window.location.href = '{error_url}';</script>
</head>
<body>
    <p>Redirecting...</p>
</body>
</html>
                    """, content_type='text/html')
                
                # Decode JWT to check nonce
                import jwt as pyjwt
                decoded_jwt = pyjwt.decode(jwt_token, options={"verify_signature": False})
                jwt_nonce = decoded_jwt.get('nonce')
                ephemeral_nonce = ephemeral_key.get('nonce')
                
                logger.info(f"JWT nonce: {jwt_nonce}")
                logger.info(f"Ephemeral key nonce: {ephemeral_nonce}")
                logger.info(f"Nonces match: {jwt_nonce == ephemeral_nonce}")
                
                # Generate deterministic pepper for personal account index 0
                pepper = generate_keyless_pepper(
                    iss=decoded_jwt.get('iss'),
                    sub=decoded_jwt.get('sub'),
                    aud=decoded_jwt.get('aud'),
                    account_type='personal',
                    business_id='',
                    account_index=0
                )
                logger.info(f"Generated deterministic pepper for user: {pepper}")
                
                # Derive Keyless account
                logger.info(f"Deriving Keyless account for sub={decoded_jwt.get('sub')}, aud={decoded_jwt.get('aud')}, iss={decoded_jwt.get('iss')}")
                keyless_account = loop.run_until_complete(
                    keyless_service.derive_keyless_account(jwt_token, ephemeral_key, pepper)
                )
                logger.info(f"Derived Keyless address: {keyless_account.get('address')}")
                logger.info(f"Pepper received: {keyless_account.get('pepper', 'Not provided - using pepper service')}")
            finally:
                loop.close()
            
            # Create backend JWT for the user
            
            # Decode the OAuth JWT to get user info
            decoded_jwt = pyjwt.decode(jwt_token, options={"verify_signature": False})
            email = decoded_jwt.get('email', '')
            sub = decoded_jwt.get('sub', '')
            
            # Sign in with Firebase using the OAuth ID token
            logger.info(f"Signing in with Firebase using {provider} ID token")
            firebase_token = None
            firebase_uid = None
            
            try:
                # Look up Firebase user by their provider ID (Google sub or Apple sub)
                # This will find the exact same Firebase user that native sign-in creates
                provider_id = f'{provider}.com'
                
                # Use provider identifier to find the user
                from firebase_admin.auth import ProviderIdentifier
                firebase_users = firebase_auth.get_users([
                    ProviderIdentifier(provider_id=provider_id, provider_uid=sub)
                ])
                
                if firebase_users.users:
                    # Found the Firebase user by their provider ID!
                    firebase_user = firebase_users.users[0]
                    firebase_uid = firebase_user.uid
                    logger.info(f"Found existing Firebase user by {provider} ID {sub}, Firebase UID: {firebase_uid}")
                    
                    # Create a custom token for the existing Firebase user
                    firebase_token = firebase_auth.create_custom_token(firebase_uid)
                    logger.info(f"Created custom token for existing Firebase user: {firebase_uid}")
                else:
                    # No existing Firebase user with this provider ID
                    logger.info(f"No existing Firebase user found for {provider} ID: {sub}")
                    
                    # No existing Firebase user with this provider ID
                    # Create a new Firebase user
                    logger.info(f"Creating new Firebase user for {provider} ID: {sub}")
                    
                    try:
                        # Create a new Firebase user
                        # Firebase will generate its own UID
                        user_record = firebase_auth.create_user(
                            email=email,
                            email_verified=True,
                            display_name=decoded_jwt.get('name', ''),
                        )
                        firebase_uid = user_record.uid
                        logger.info(f"Created new Firebase user with UID: {firebase_uid}")
                        
                        # Now link the OAuth provider to this user
                        # This ensures future lookups by provider ID will find this user
                        from firebase_admin.auth import UserProvider
                        provider_data = UserProvider(
                            uid=sub,
                            provider_id=provider_id,
                            email=email
                        )
                        
                        # Update user to add the provider
                        firebase_auth.update_user(
                            firebase_uid,
                            provider_to_link=provider_data
                        )
                        logger.info(f"Linked {provider} provider to Firebase user {firebase_uid}")
                        
                        # Create custom token for the new user
                        firebase_token = firebase_auth.create_custom_token(firebase_uid)
                        
                    except Exception as create_error:
                        logger.error(f"Error creating Firebase user: {str(create_error)}")
                        # Try alternative approach if provider linking fails
                        try:
                            # Just create the user without provider linking
                            user_record = firebase_auth.create_user(
                                email=email,
                                email_verified=True,
                            )
                            firebase_uid = user_record.uid
                            firebase_token = firebase_auth.create_custom_token(firebase_uid)
                            logger.info(f"Created Firebase user without provider linking: {firebase_uid}")
                        except Exception as e:
                            logger.error(f"Failed to create Firebase user: {str(e)}")
                            firebase_uid = None
                            firebase_token = None
                
            except Exception as firebase_error:
                logger.error(f"Firebase authentication error: {str(firebase_error)}")
                # Continue without Firebase token - don't break the flow
                firebase_token = None
                firebase_uid = None
            
            # Create new user for web OAuth flow
            # This maintains separate users from Firebase authentication
            username = f"user_{uuid.uuid4().hex[:8]}"
            
            # Firebase UID is required - it's our primary user identifier
            if not firebase_uid:
                logger.error(f"Failed to get Firebase UID for {email}. Cannot proceed without Firebase.")
                error_params = urlencode({
                    'success': 'false',
                    'error': 'Firebase authentication failed. Please try again.'
                })
                error_url = f'confio://oauth-callback?{error_params}'
                return HttpResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="0; url={error_url}">
    <script>window.location.href = '{error_url}';</script>
</head>
<body>
    <p>Redirecting...</p>
</body>
</html>
                """, content_type='text/html')
            
            # We have a Firebase UID - check if user exists in our DB
            try:
                user = User.objects.get(firebase_uid=firebase_uid)
                logger.info(f"Found existing user in DB with firebase_uid: {firebase_uid}")
                created = False
            except User.DoesNotExist:
                # Firebase user exists but not in our DB - create them
                user = User.objects.create(
                    username=username,
                    email=email,
                    firebase_uid=firebase_uid,
                    is_active=True
                )
                logger.info(f"Created new user for Firebase account: {email}, firebase_uid: {firebase_uid}")
                created = True
            
            # Create or update default personal account with Aptos address
            from users.models import Account
            
            # Check if the user already has a personal account
            try:
                account = Account.objects.get(
                    user=user,
                    account_type='personal',
                    account_index=0
                )
                # Update the address
                old_address = account.aptos_address
                account.aptos_address = keyless_account['address']
                account.save()
                logger.info(f"Updated existing personal account - Old address: {old_address}, New address: {keyless_account['address']}")
                if old_address and old_address != keyless_account['address']:
                    logger.warning(f"ADDRESS CHANGED for user {user.email} (firebase_uid: {firebase_uid})!")
                    logger.warning(f"This suggests non-deterministic address generation - investigate JWT claims and pepper service")
                
                # Verify the update
                account.refresh_from_db()
                logger.info(f"Verified address after save: {account.aptos_address}")
            except Account.DoesNotExist:
                # Create new account
                account = Account.objects.create(
                    user=user,
                    account_type='personal',
                    account_index=0,
                    aptos_address=keyless_account['address']  # Store Aptos address in aptos_address field
                )
                logger.info(f"Created default personal account with Aptos address: {keyless_account['address']}")
            
            # Store device fingerprint if provided
            if device_fingerprint:
                logger.info(f"Storing device fingerprint for user {user.id}")
                # You can store this in a UserDevice model or similar
                # For now, we'll include it in the JWT payload
            
            # Generate backend JWT tokens (access and refresh)
            # Access token - short lived (1 hour)
            access_token_payload = {
                'user_id': user.id,
                'username': user.username,
                'type': 'access',  # Required by Apollo client
                'auth_token_version': user.auth_token_version,  # Required for token validation
                'exp': datetime.utcnow() + timedelta(hours=1),
                'iat': datetime.utcnow(),
                'account_type': 'personal',
                'account_index': 0
            }
            
            # Include device fingerprint hash if available
            if device_fingerprint:
                import hashlib
                import json as json_lib
                device_hash = hashlib.sha256(json_lib.dumps(device_fingerprint, sort_keys=True).encode()).hexdigest()[:16]
                access_token_payload['device_id'] = device_hash
            
            access_token = pyjwt.encode(
                access_token_payload,
                settings.SECRET_KEY,
                algorithm='HS256'
            )
            
            # Refresh token - long lived (30 days)
            refresh_token_payload = {
                'user_id': user.id,
                'username': user.username,
                'type': 'refresh',  # Required by Apollo client
                'auth_token_version': user.auth_token_version,
                'exp': datetime.utcnow() + timedelta(days=30),
                'iat': datetime.utcnow()
            }
            
            refresh_token = pyjwt.encode(
                refresh_token_payload,
                settings.SECRET_KEY,
                algorithm='HS256'
            )
            
            # No session cleanup needed since we're using stateless tokens
            
            # Check if user has verified phone in our database
            is_phone_verified = bool(user.phone_number and user.phone_country)
            logger.info(f"Phone verification check for user {user.email}: phone_number='{user.phone_number}', phone_country='{user.phone_country}', is_verified={is_phone_verified}")
            
            # Prepare redirect params
            redirect_params_dict = {
                'success': 'true',
                'keyless_account': json.dumps({
                    'address': keyless_account['address'],
                    'publicKey': keyless_account['publicKey'],
                    'jwt': jwt_token,
                    'ephemeralKeyPair': ephemeral_key,
                    'pepper': keyless_account.get('pepper')
                }),
                'backend_token': access_token,  # Keep for backward compatibility
                'access_token': access_token,
                'refresh_token': refresh_token,
                'user_id': user.id,
                'is_phone_verified': 'true' if is_phone_verified else 'false'
            }
            
            logger.info(f"OAuth callback returning is_phone_verified: {'true' if is_phone_verified else 'false'} for user {user.email}")
            
            # Add Firebase tokens if available
            if firebase_token:
                redirect_params_dict['firebase_token'] = firebase_token.decode('utf-8') if isinstance(firebase_token, bytes) else firebase_token
                redirect_params_dict['firebase_uid'] = firebase_uid
            
            redirect_params = urlencode(redirect_params_dict)
            
            # Return a minimal HTML page that redirects to the app
            redirect_url = f'confio://oauth-callback?{redirect_params}'
            return HttpResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="0; url={redirect_url}">
    <script>window.location.href = '{redirect_url}';</script>
</head>
<body>
    <p>Redirecting...</p>
</body>
</html>
            """, content_type='text/html')
            
        except Exception as e:
            logger.error(f"OAuth callback error: {str(e)}")
            # Return HTML page that redirects to app with error
            error_params = urlencode({
                'success': 'false',
                'error': str(e)
            })
            error_url = f'confio://oauth-callback?{error_params}'
            return HttpResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Authentication Error</title>
    <script>
        function redirectToApp() {{
            try {{ window.location.href = '{error_url}'; }} catch (e) {{}}
            setTimeout(function() {{ try {{ window.location.replace('{error_url}'); }} catch (e) {{}} }}, 100);
        }}
        redirectToApp();
    </script>
</head>
<body onload="redirectToApp()">
    <p>Authentication error. Redirecting to app...</p>
    <p><a href="{error_url}">Click here if not redirected</a></p>
</body>
</html>
            """, content_type='text/html')
    
    async def _exchange_google_code(self, code, request):
        """Exchange Google authorization code for ID token"""
        import aiohttp
        
        logger.info(f"Exchanging Google OAuth code for token")
        logger.info(f"Client ID: {settings.GOOGLE_OAUTH_CLIENT_ID}")
        logger.info(f"Has Client Secret: {bool(settings.GOOGLE_OAUTH_CLIENT_SECRET and settings.GOOGLE_OAUTH_CLIENT_SECRET != 'YOUR_GOOGLE_CLIENT_SECRET_HERE')}")
        
        async with aiohttp.ClientSession() as session:
            post_data = {
                'code': code,
                'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
                'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
                'redirect_uri': self._get_redirect_uri(request),
                'grant_type': 'authorization_code'
            }
            
            async with session.post('https://oauth2.googleapis.com/token', data=post_data) as response:
                response_text = await response.text()
                logger.info(f"Google OAuth response status: {response.status}")
                
                if response.status != 200:
                    logger.error(f"Google OAuth error response: {response_text}")
                    return None
                
                import json as json_lib
                data = json_lib.loads(response_text)
                id_token = data.get('id_token')
                
                if not id_token:
                    logger.error(f"No id_token in Google response. Keys: {list(data.keys())}")
                else:
                    logger.info(f"Successfully got id_token from Google")
                
                return id_token
    
    async def _exchange_apple_code(self, code, request):
        """Exchange Apple authorization code for ID token"""
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            async with session.post('https://appleid.apple.com/auth/token', data={
                'code': code,
                'client_id': settings.APPLE_OAUTH_CLIENT_ID,
                'client_secret': settings.APPLE_OAUTH_CLIENT_SECRET,
                'redirect_uri': self._get_redirect_uri(request),
                'grant_type': 'authorization_code'
            }) as response:
                data = await response.json()
                return data.get('id_token')


@method_decorator(csrf_exempt, name='dispatch')
class AptosOAuthCloseView(View):
    """Force close the OAuth window by redirecting to the app"""
    
    def get(self, request):
        """Handle close request by redirecting to app with cancel status"""
        # Return a page that aggressively tries to close the window
        return HttpResponse("""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Closing...</title>
    <script>
        // Immediately try to redirect to the app
        window.location.href = 'confio://oauth-callback?success=false&error=window_closed';
        
        // Also try to close the window
        setTimeout(function() {
            try {
                window.close();
                window.open('', '_self', '');
                window.close();
            } catch (e) {}
        }, 100);
    </script>
</head>
<body>
    <p>Closing window...</p>
</body>
</html>
        """, content_type='text/html')