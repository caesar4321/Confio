"""
Aptos Keyless Service for Django Backend
Communicates with the TypeScript bridge service to handle Keyless operations
"""
import aiohttp
import json
from typing import Dict, Any, Optional
from django.conf import settings

class AptosKeylessService:
    def __init__(self):
        # The bridge URL should be configured in Django settings
        self.bridge_url = getattr(settings, 'APTOS_KEYLESS_BRIDGE_URL', 'http://localhost:3333')
    
    async def generate_ephemeral_key(self, expiry_hours: int = 24) -> Dict[str, Any]:
        """Generate ephemeral key pair"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self.bridge_url}/api/keyless/ephemeral-key",
                    json={"expiryHours": expiry_hours},
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(f"Bridge error: {error_text}")
                    
                    result = await response.json()
                    if result.get('success'):
                        return result['data']
                    else:
                        raise Exception(result.get('error', 'Unknown error'))
            except Exception as e:
                print(f"Error generating ephemeral key: {e}")
                raise
    
    async def derive_keyless_account(self, jwt: str, ephemeral_key_pair: Dict[str, Any], pepper: Optional[str] = None) -> Dict[str, Any]:
        """Derive Keyless account from JWT"""
        print(f"[AptosKeylessService] derive_keyless_account called")
        print(f"[AptosKeylessService] JWT provided: {bool(jwt)} (length: {len(jwt) if jwt else 0})")
        print(f"[AptosKeylessService] ephemeral_key_pair type: {type(ephemeral_key_pair)}")
        print(f"[AptosKeylessService] ephemeral_key_pair keys: {list(ephemeral_key_pair.keys()) if isinstance(ephemeral_key_pair, dict) else 'Not a dict'}")
        print(f"[AptosKeylessService] Pepper provided: {bool(pepper)} (length: {len(pepper) if pepper else 0})")
        
        async with aiohttp.ClientSession() as session:
            try:
                request_data = {
                    "jwt": jwt,
                    "ephemeralKeyPair": ephemeral_key_pair,
                    "pepper": pepper
                }
                print(f"[AptosKeylessService] Sending to bridge: {json.dumps(request_data, indent=2)[:500]}...")
                
                async with session.post(
                    f"{self.bridge_url}/api/keyless/derive-account",
                    json=request_data,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(f"Bridge error: {error_text}")
                    
                    result = await response.json()
                    if result.get('success'):
                        return result['data']
                    else:
                        raise Exception(result.get('error', 'Unknown error'))
            except Exception as e:
                print(f"Error deriving keyless account: {e}")
                raise
    
    async def sign_and_submit_transaction(
        self, 
        jwt: str, 
        ephemeral_key_pair: Dict[str, Any],
        transaction: Dict[str, Any],
        pepper: Optional[str] = None
    ) -> str:
        """Sign and submit transaction"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self.bridge_url}/api/keyless/sign-and-submit",
                    json={
                        "jwt": jwt,
                        "ephemeralKeyPair": ephemeral_key_pair,
                        "transaction": transaction,
                        "pepper": pepper
                    },
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(f"Bridge error: {error_text}")
                    
                    result = await response.json()
                    if result.get('success'):
                        return result['data']['transactionHash']
                    else:
                        raise Exception(result.get('error', 'Unknown error'))
            except Exception as e:
                print(f"Error submitting transaction: {e}")
                raise
    
    async def get_balance(self, address: str) -> Dict[str, str]:
        """Get account balance"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    f"{self.bridge_url}/api/keyless/balance/{address}"
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(f"Bridge error: {error_text}")
                    
                    result = await response.json()
                    if result.get('success'):
                        return result['data']
                    else:
                        raise Exception(result.get('error', 'Unknown error'))
            except Exception as e:
                print(f"Error getting balance: {e}")
                raise

# Singleton instance
keyless_service = AptosKeylessService()