from google.oauth2 import id_token
from google.auth.transport import requests
from django.conf import settings
from typing import Dict, Optional, List
from decouple import config, Csv

def verify_google_oauth_token(id_token_str: str, client_id: str) -> Dict:
    """
    Verify a Google OAuth ID token using Google's public keys.
    
    Args:
        id_token_str: The Google OAuth ID token to verify
        client_id: The Google OAuth client ID to verify against
        
    Returns:
        Dict containing the verified token claims (sub, aud, iss, etc.)
        
    Raises:
        ValueError: If the token is invalid or verification fails
    """
    try:
        # Get valid client IDs from environment variables
        valid_client_ids = [
            config('GOOGLE_IOS_CLIENT_ID'),
            config('GOOGLE_WEB_CLIENT_ID'),
            config('GOOGLE_ANDROID_CLIENT_ID')
        ]
        
        # Verify the token using Google's public keys
        idinfo = id_token.verify_oauth2_token(
            id_token_str,
            requests.Request(),
            None  # Don't verify client ID here, we'll do it manually
        )
        
        # Verify the token's audience matches one of the valid client IDs
        if idinfo['aud'] not in valid_client_ids:
            raise ValueError(f"Token has wrong audience {idinfo['aud']}, expected one of {valid_client_ids}")
            
        return idinfo
        
    except Exception as e:
        raise ValueError(f"Failed to verify Google OAuth token: {str(e)}") 