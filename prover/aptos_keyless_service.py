"""
Aptos Keyless Service for Django Backend
Direct implementation using Aptos SDK - no bridge service needed
"""
import json
import hashlib
from typing import Dict, Any, Optional
from django.conf import settings

class AptosKeylessService:
    def __init__(self):
        # Network configuration
        self.network = getattr(settings, 'APTOS_NETWORK', 'testnet')
        self.aptos_client = None
    
    async def generate_ephemeral_key(self, expiry_hours: int = 24) -> Dict[str, Any]:
        """DISABLED: Generate ephemeral key pair - client must provide keys"""
        raise Exception("Server-side ephemeral key generation is disabled. Use client-generated keys only.")
    
    async def derive_keyless_account(self, jwt: str, ephemeral_key_pair: Dict[str, Any], pepper: Optional[str] = None) -> Dict[str, Any]:
        """Derive Keyless account from JWT using direct SDK implementation"""
        print(f"[AptosKeylessService] derive_keyless_account called")
        print(f"[AptosKeylessService] JWT provided: {bool(jwt)} (length: {len(jwt) if jwt else 0})")
        print(f"[AptosKeylessService] ephemeral_key_pair type: {type(ephemeral_key_pair)}")
        print(f"[AptosKeylessService] ephemeral_key_pair keys: {list(ephemeral_key_pair.keys()) if isinstance(ephemeral_key_pair, dict) else 'Not a dict'}")
        print(f"[AptosKeylessService] Pepper provided: {bool(pepper)} (length: {len(pepper) if pepper else 0})")
        
        try:
            # Import only what we need
            import jwt as pyjwt
            import base64
            
            # Decode JWT to get claims
            decoded_jwt = pyjwt.decode(jwt, options={"verify_signature": False})
            
            # Extract required fields
            iss = decoded_jwt.get('iss')  # issuer (e.g., https://accounts.google.com)
            sub = decoded_jwt.get('sub')  # subject (user ID)
            aud = decoded_jwt.get('aud')  # audience (client ID)
            nonce = decoded_jwt.get('nonce')  # nonce from ephemeral key
            
            print(f"[AptosKeylessService] JWT claims - iss: {iss}, sub: {sub}, aud: {aud}, nonce: {nonce}")
            
            # Validate that we have the required ephemeral key data
            ephemeral_public_key = ephemeral_key_pair.get('publicKey')
            ephemeral_nonce = ephemeral_key_pair.get('nonce')
            ephemeral_expiry = ephemeral_key_pair.get('expiryDate')
            client_address = ephemeral_key_pair.get('clientAddress')
            
            if not ephemeral_public_key or not ephemeral_nonce:
                raise Exception("Missing required ephemeral key data (publicKey, nonce)")
            
            # Verify nonce matches
            if str(nonce) != str(ephemeral_nonce):
                raise Exception(f"JWT nonce ({nonce}) does not match ephemeral key nonce ({ephemeral_nonce})")
            
            # ENFORCE CLIENT-SIDE ADDRESS DERIVATION ONLY
            if not client_address:
                print(f"[AptosKeylessService] CRITICAL ERROR: No client address provided")
                print(f"[AptosKeylessService] Backend is configured to NEVER derive addresses")
                print(f"[AptosKeylessService] All address derivation must be done client-side using official Aptos SDK")
                raise Exception(
                    "Client address required. Backend does not derive addresses to prevent inconsistencies. "
                    "Client must derive address using official Aptos SDK and provide it to backend."
                )
            
            print(f"[AptosKeylessService] ✅ Using client-provided keyless address: {client_address}")
            print(f"[AptosKeylessService] ✅ Backend NEVER derives addresses - client-only derivation enforced")
            aptos_address = client_address
            
            print(f"[AptosKeylessService] Derived address: {aptos_address}")
            print(f"[AptosKeylessService] JWT claims used: iss={iss}, sub={sub}, aud={aud}")
            
            return {
                'address': aptos_address,
                'publicKey': ephemeral_public_key,
                'pepper': pepper
            }
            
        except Exception as e:
            print(f"[AptosKeylessService] Error deriving keyless account: {e}")
            raise Exception(f"Failed to derive keyless account: {str(e)}")
    
    async def sign_and_submit_transaction(
        self, 
        jwt: str, 
        ephemeral_key_pair: Dict[str, Any],
        transaction: Dict[str, Any],
        pepper: Optional[str] = None
    ) -> str:
        """Sign and submit transaction - NOT IMPLEMENTED (client handles this)"""
        raise Exception("Transaction signing is handled client-side. Use client aptosKeylessService.signAndSubmitTransaction()")
    
    async def get_balance(self, address: str) -> Dict[str, str]:
        """Get account balance - direct Aptos REST API call"""
        import aiohttp
        
        # Use Aptos REST API directly
        aptos_url = "https://fullnode.testnet.aptoslabs.com/v1" if self.network == 'testnet' else "https://fullnode.mainnet.aptoslabs.com/v1"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{aptos_url}/accounts/{address}/resource/0x1::coin::CoinStore<0x1::aptos_coin::AptosCoin>") as response:
                    if response.status == 200:
                        data = await response.json()
                        coin_data = data.get('data', {})
                        coin_value = coin_data.get('coin', {}).get('value', '0')
                        # Convert from octas to APT (1 APT = 10^8 octas)
                        apt_balance = str(int(coin_value) / 100000000)
                        return {'apt': apt_balance}
                    else:
                        # Account might not exist or have no APT
                        return {'apt': '0'}
            except Exception as e:
                print(f"Error getting balance: {e}")
                return {'apt': '0'}

# Singleton instance
keyless_service = AptosKeylessService()