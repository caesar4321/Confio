"""
Python client wrapper for Aptos Keyless Bridge Service

This client provides a convenient interface to interact with the TypeScript
Aptos Keyless Bridge service from Python applications.
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, Tuple
from dataclasses import dataclass, asdict
import aiohttp
from aiohttp import ClientSession, ClientTimeout


@dataclass
class EphemeralKeyPair:
    """Represents an ephemeral key pair for Keyless authentication"""
    private_key: str
    public_key: str
    expiry_date: str
    nonce: Optional[str] = None
    blinder: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API requests"""
        return {k: v for k, v in asdict(self).items() if v is not None}
    
    def is_expired(self) -> bool:
        """Check if the key pair has expired"""
        expiry = datetime.fromisoformat(self.expiry_date.replace('Z', '+00:00'))
        return datetime.now() >= expiry


@dataclass
class KeylessAccount:
    """Represents a Keyless account"""
    address: str
    public_key: str
    jwt: str
    ephemeral_key_pair: EphemeralKeyPair
    pepper: Optional[str] = None


class AptosKeylessClient:
    """Client for interacting with the Aptos Keyless Bridge Service"""
    
    def __init__(self, service_url: str = "http://localhost:3333", timeout: int = 30):
        """
        Initialize the Aptos Keyless Client
        
        Args:
            service_url: URL of the Keyless Bridge Service
            timeout: Request timeout in seconds
        """
        self.service_url = service_url.rstrip('/')
        self.timeout = ClientTimeout(total=timeout)
        self._session: Optional[ClientSession] = None
    
    async def __aenter__(self):
        """Async context manager entry"""
        self._session = ClientSession(timeout=self.timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self._session:
            await self._session.close()
    
    @property
    def session(self) -> ClientSession:
        """Get or create session"""
        if self._session is None:
            self._session = ClientSession(timeout=self.timeout)
        return self._session
    
    async def health_check(self) -> Dict[str, Any]:
        """Check if the Keyless Bridge Service is running"""
        async with self.session.get(f"{self.service_url}/api/keyless/health") as response:
            response.raise_for_status()
            return await response.json()
    
    async def generate_ephemeral_key_pair(self, expiry_hours: int = 24) -> EphemeralKeyPair:
        """
        Generate a new ephemeral key pair
        
        Args:
            expiry_hours: Number of hours until the key expires
            
        Returns:
            EphemeralKeyPair object
        """
        data = {"expiryHours": expiry_hours}
        
        async with self.session.post(
            f"{self.service_url}/api/keyless/ephemeral-key",
            json=data
        ) as response:
            response.raise_for_status()
            result = await response.json()
            
            if not result.get("success"):
                raise Exception(f"Failed to generate ephemeral key: {result}")
            
            key_data = result["data"]
            return EphemeralKeyPair(**key_data)
    
    async def generate_oauth_url(
        self,
        provider: str,
        client_id: str,
        redirect_uri: str,
        ephemeral_key_pair: EphemeralKeyPair
    ) -> str:
        """
        Generate OAuth login URL with ephemeral key commitment
        
        Args:
            provider: OAuth provider ('google' or 'apple')
            client_id: OAuth client ID
            redirect_uri: OAuth redirect URI
            ephemeral_key_pair: Ephemeral key pair for nonce
            
        Returns:
            OAuth login URL
        """
        data = {
            "provider": provider,
            "clientId": client_id,
            "redirectUri": redirect_uri,
            "ephemeralPublicKey": ephemeral_key_pair.public_key,
            "expiryDate": ephemeral_key_pair.expiry_date,
            "blinder": ephemeral_key_pair.blinder,
        }
        
        async with self.session.post(
            f"{self.service_url}/api/keyless/oauth-url",
            json=data
        ) as response:
            response.raise_for_status()
            result = await response.json()
            
            if not result.get("success"):
                raise Exception(f"Failed to generate OAuth URL: {result}")
            
            return result["data"]["url"]
    
    async def derive_keyless_account(
        self,
        jwt: str,
        ephemeral_key_pair: EphemeralKeyPair,
        pepper: Optional[str] = None
    ) -> KeylessAccount:
        """
        Derive a Keyless account from JWT and ephemeral key pair
        
        Args:
            jwt: JWT token from OAuth provider
            ephemeral_key_pair: Ephemeral key pair
            pepper: Optional pepper for additional privacy
            
        Returns:
            KeylessAccount object
        """
        data = {
            "jwt": jwt,
            "ephemeralKeyPair": ephemeral_key_pair.to_dict(),
            "pepper": pepper,
        }
        
        async with self.session.post(
            f"{self.service_url}/api/keyless/derive-account",
            json=data
        ) as response:
            response.raise_for_status()
            result = await response.json()
            
            if not result.get("success"):
                raise Exception(f"Failed to derive account: {result}")
            
            account_data = result["data"]
            return KeylessAccount(
                address=account_data["address"],
                public_key=account_data["publicKey"],
                jwt=account_data["jwt"],
                ephemeral_key_pair=ephemeral_key_pair,
                pepper=account_data.get("pepper")
            )
    
    async def sign_and_submit_transaction(
        self,
        jwt: str,
        ephemeral_key_pair: EphemeralKeyPair,
        transaction: Dict[str, Any],
        pepper: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Sign and submit a transaction using Keyless account
        
        Args:
            jwt: JWT token from OAuth provider
            ephemeral_key_pair: Ephemeral key pair
            transaction: Transaction payload
            pepper: Optional pepper
            
        Returns:
            Transaction result
        """
        data = {
            "jwt": jwt,
            "ephemeralKeyPair": ephemeral_key_pair.to_dict(),
            "transaction": transaction,
            "pepper": pepper,
        }
        
        async with self.session.post(
            f"{self.service_url}/api/keyless/sign-and-submit",
            json=data
        ) as response:
            response.raise_for_status()
            result = await response.json()
            
            if not result.get("success"):
                raise Exception(f"Failed to submit transaction: {result}")
            
            return result["data"]
    
    async def get_balance(self, address: str) -> Dict[str, str]:
        """
        Get account balance
        
        Args:
            address: Aptos account address
            
        Returns:
            Balance information
        """
        async with self.session.get(
            f"{self.service_url}/api/keyless/balance/{address}"
        ) as response:
            response.raise_for_status()
            result = await response.json()
            
            if not result.get("success"):
                raise Exception(f"Failed to get balance: {result}")
            
            return result["data"]
    
    async def close(self):
        """Close the HTTP session"""
        if self._session:
            await self._session.close()
            self._session = None


# Example usage and integration with existing code
async def migrate_from_zklogin(zklogin_jwt: str, oauth_provider: str = "google") -> KeylessAccount:
    """
    Example function showing how to migrate from zkLogin to Keyless
    
    Args:
        zklogin_jwt: JWT from zkLogin authentication
        oauth_provider: OAuth provider used
        
    Returns:
        KeylessAccount object
    """
    async with AptosKeylessClient() as client:
        # 1. Generate ephemeral key pair
        ephemeral_key = await client.generate_ephemeral_key_pair(expiry_hours=24)
        
        # 2. In a real scenario, user would need to re-authenticate
        # For migration, you'd need to handle the OAuth flow
        print(f"Ephemeral key generated: {ephemeral_key.public_key[:32]}...")
        
        # 3. After OAuth callback with new JWT, derive Keyless account
        # Note: This would be a new JWT from Aptos OAuth, not the zkLogin JWT
        # keyless_account = await client.derive_keyless_account(
        #     jwt=new_jwt_from_oauth,
        #     ephemeral_key_pair=ephemeral_key
        # )
        
        # For now, return a mock account
        return KeylessAccount(
            address="0x123...",
            public_key=ephemeral_key.public_key,
            jwt=zklogin_jwt,
            ephemeral_key_pair=ephemeral_key
        )


# Test function
async def test_keyless_client():
    """Test the Keyless client"""
    client = AptosKeylessClient()
    
    try:
        # Health check
        print("Testing health check...")
        health = await client.health_check()
        print(f"Service status: {health}")
        
        # Generate ephemeral key
        print("\nGenerating ephemeral key pair...")
        ephemeral_key = await client.generate_ephemeral_key_pair(expiry_hours=24)
        print(f"Public key: {ephemeral_key.public_key[:32]}...")
        print(f"Expires: {ephemeral_key.expiry_date}")
        
        # Generate OAuth URL
        print("\nGenerating OAuth URL...")
        oauth_url = await client.generate_oauth_url(
            provider="google",
            client_id="your-client-id",
            redirect_uri="http://localhost:3000/callback",
            ephemeral_key_pair=ephemeral_key
        )
        print(f"OAuth URL: {oauth_url[:80]}...")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await client.close()


if __name__ == "__main__":
    # Run test
    asyncio.run(test_keyless_client())