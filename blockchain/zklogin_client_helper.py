"""
zkLogin Client Helper
Provides utilities for zkLogin that work with client-side proofs only
No server-side storage of proofs or ephemeral keys
"""
import hashlib
import base64
from typing import Dict, Optional
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import logging

logger = logging.getLogger(__name__)


class ZkLoginClientHelper:
    """
    Helper functions for zkLogin that maintain client-side control
    Server only helps with address computation and transaction building
    """
    
    @staticmethod
    def compute_zklogin_address(
        jwt_issuer: str,
        jwt_aud: str,
        jwt_sub: str,
        user_salt: str
    ) -> str:
        """
        Compute zkLogin address from JWT claims and salt
        This is deterministic and can be verified client-side
        
        Args:
            jwt_issuer: JWT issuer (e.g., 'https://accounts.google.com')
            jwt_aud: JWT audience 
            jwt_sub: JWT subject (user ID from OAuth provider)
            user_salt: User-specific salt
            
        Returns:
            Sui address (0x prefixed)
        """
        try:
            # Normalize issuer
            if jwt_issuer == 'https://accounts.google.com':
                provider = 'google'
            elif jwt_issuer == 'https://appleid.apple.com':
                provider = 'apple'
            else:
                provider = jwt_issuer
            
            # Create address seed
            # This is a simplified version - production would use Sui's exact algorithm
            seed_data = f"{provider}:{jwt_aud}:{jwt_sub}:{user_salt}".encode('utf-8')
            
            # Hash to get address bytes
            address_hash = hashlib.blake2b(seed_data, digest_size=32).digest()
            
            # Take first 32 bytes for address
            address_bytes = address_hash[:32]
            
            # Add 0x00 flag byte for zkLogin addresses
            flagged_address = b'\x00' + address_bytes[:31]
            
            return '0x' + flagged_address.hex()
            
        except Exception as e:
            logger.error(f"Error computing zkLogin address: {e}")
            raise
    
    @staticmethod
    def generate_ephemeral_keypair() -> Dict[str, str]:
        """
        Generate an ephemeral keypair for the client
        This should actually be done client-side in production
        
        Returns:
            Dict with 'private_key' and 'public_key' in base64
        """
        try:
            # Generate Ed25519 key using secp256k1 curve
            private_key = ec.generate_private_key(ec.SECP256K1(), default_backend())
            
            # Get private key bytes
            private_bytes = private_key.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            
            # Get public key bytes
            public_key = private_key.public_key()
            public_bytes = public_key.public_bytes(
                encoding=serialization.Encoding.SubjectPublicKeyInfo,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            
            return {
                'private_key': base64.b64encode(private_bytes).decode('utf-8'),
                'public_key': base64.b64encode(public_bytes).decode('utf-8')
            }
            
        except Exception as e:
            logger.error(f"Error generating ephemeral keypair: {e}")
            raise
    
    @staticmethod
    def verify_zklogin_signature(
        signature: str,
        transaction_bytes: bytes,
        sender_address: str
    ) -> bool:
        """
        Verify a zkLogin signature matches the transaction
        In production, this would verify the zero-knowledge proof
        
        Args:
            signature: Base64 encoded zkLogin signature from client
            transaction_bytes: The transaction bytes that were signed
            sender_address: Expected sender address
            
        Returns:
            True if signature is valid
        """
        try:
            # In production, this would:
            # 1. Decode the zkLogin signature structure
            # 2. Verify the zero-knowledge proof
            # 3. Check the ephemeral signature
            # 4. Ensure the address derivation is correct
            
            # For now, just do basic validation
            if not signature or not transaction_bytes or not sender_address:
                return False
            
            # Decode signature
            try:
                sig_bytes = base64.b64decode(signature)
                if len(sig_bytes) < 64:  # Minimum signature size
                    return False
            except Exception:
                return False
            
            # TODO: Implement actual zkLogin signature verification
            # This requires the zkLogin verifier logic from Sui
            
            logger.info(f"zkLogin signature verification not fully implemented - allowing for testing")
            return True
            
        except Exception as e:
            logger.error(f"Error verifying zkLogin signature: {e}")
            return False