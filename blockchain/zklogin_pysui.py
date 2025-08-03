"""
zkLogin implementation using pysui SDK - Client-side version
This module now only provides helper functions for zkLogin
All proofs and signatures must come from the client
"""
import json
import base64
import hashlib
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from pysui.sui.sui_types import SuiAddress
from pysui.sui.sui_crypto import SuiPublicKey, SuiPrivateKey
from django.conf import settings
from users.models import User, Account
import logging

logger = logging.getLogger(__name__)


class ZkLoginPySui:
    """
    zkLogin helper functions for client-side zkLogin
    Server never stores proofs or ephemeral keys
    """
    
    @classmethod
    def compute_zklogin_address(
        cls,
        jwt_payload: Dict,
        user_salt: str,
        aud: str = 'confio-abbda'
    ) -> str:
        """
        Compute zkLogin address from JWT payload and salt
        This must match the client-side computation exactly
        
        Args:
            jwt_payload: Decoded JWT payload with iss, sub, etc.
            user_salt: User-specific salt for address generation
            aud: JWT audience value
            
        Returns:
            Sui address (0x prefixed)
        """
        try:
            # Extract required fields
            iss = jwt_payload.get('iss', '')
            sub = jwt_payload.get('sub', '')
            
            # Normalize issuer
            if iss == 'https://accounts.google.com':
                provider = 'Google'
            elif iss == 'https://appleid.apple.com':  
                provider = 'Apple'
            else:
                provider = iss
            
            # Create address seed matching Sui's zkLogin spec
            # In production, this must exactly match Sui's algorithm
            seed_components = [
                provider,
                aud,
                sub,
                user_salt
            ]
            seed_string = ':'.join(seed_components)
            
            # Hash to derive address
            address_hash = hashlib.blake2b(
                seed_string.encode('utf-8'), 
                digest_size=32
            ).digest()
            
            # Apply zkLogin address flag (0x00)
            # Take first 31 bytes and prepend flag
            address_bytes = b'\x00' + address_hash[:31]
            
            return '0x' + address_bytes.hex()
            
        except Exception as e:
            logger.error(f"Error computing zkLogin address: {e}")
            raise
    
    @classmethod
    def verify_zklogin_address(
        cls,
        jwt_token: str,
        expected_address: str,
        user_salt: str
    ) -> bool:
        """
        Verify that a JWT token produces the expected zkLogin address
        
        Args:
            jwt_token: The JWT token
            expected_address: The expected Sui address
            user_salt: The user salt used
            
        Returns:
            True if address matches, False otherwise
        """
        try:
            # Decode JWT without verification (verification done elsewhere)
            import jwt
            payload = jwt.decode(jwt_token, options={"verify_signature": False})
            
            # Compute address
            computed_address = cls.compute_zklogin_address(
                jwt_payload=payload,
                user_salt=user_salt,
                aud=payload.get('aud', 'confio-abbda')
            )
            
            # Normalize addresses for comparison
            expected = expected_address.lower().replace('0x', '')
            computed = computed_address.lower().replace('0x', '')
            
            return expected == computed
            
        except Exception as e:
            logger.error(f"Error verifying zkLogin address: {e}")
            return False
    
    @classmethod
    def validate_zklogin_signature(
        cls,
        signature: str,
        tx_bytes: bytes,
        sender_address: str
    ) -> bool:
        """
        Basic validation of zkLogin signature format
        Full verification happens on-chain
        
        Args:
            signature: Base64 encoded zkLogin signature
            tx_bytes: Transaction bytes that were signed
            sender_address: Expected sender address
            
        Returns:
            True if signature format is valid
        """
        try:
            # Decode signature
            sig_bytes = base64.b64decode(signature)
            
            # Basic length check - zkLogin signatures are typically 200+ bytes
            if len(sig_bytes) < 100:
                logger.error(f"zkLogin signature too short: {len(sig_bytes)} bytes")
                return False
            
            # TODO: Add more validation once we have the exact zkLogin format spec
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating zkLogin signature: {e}")
            return False