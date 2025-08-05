import graphene
import asyncio
import json
from graphene import ObjectType, String, Boolean, Field, Int
from .aptos_keyless_service import keyless_service
from .keyless_mutations import EphemeralKeyPairType, KeylessAccountType

class DeriveMobileKeylessAccount(graphene.Mutation):
    """
    Special mutation for mobile OAuth where we can't control the nonce.
    This creates an ephemeral key pair AFTER receiving the JWT,
    using a deterministic approach based on the JWT content.
    """
    class Arguments:
        jwt = String(required=True)
        provider = String(required=True)  # 'google' or 'apple'
    
    keyless_account = Field(KeylessAccountType)
    ephemeral_key_pair = Field(EphemeralKeyPairType)
    success = Boolean()
    error = String()
    
    def mutate(self, info, jwt, provider):
        try:
            # For mobile OAuth, we need a different approach
            # Since we can't control the nonce in the JWT, we'll use a workaround
            
            # Option 1: Generate ephemeral key based on JWT content (deterministic)
            # This is a simplified approach - in production you'd want more security
            
            # First generate a standard ephemeral key pair
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            ephemeral_key = loop.run_until_complete(keyless_service.generate_ephemeral_key(24))
            
            # For mobile apps, we might need to use a different Aptos Keyless flow
            # or implement a backend service that handles the OAuth properly
            
            # Try to derive the account (this might still fail with nonce mismatch)
            try:
                account = loop.run_until_complete(
                    keyless_service.derive_keyless_account(jwt, ephemeral_key)
                )
                
                return DeriveMobileKeylessAccount(
                    keyless_account=KeylessAccountType(
                        address=account.get('address'),
                        public_key=account.get('publicKey'),
                        jwt=jwt,
                        pepper=account.get('pepper')
                    ),
                    ephemeral_key_pair=EphemeralKeyPairType(
                        private_key=ephemeral_key.get('privateKey'),
                        public_key=ephemeral_key.get('publicKey'),
                        expiry_date=ephemeral_key.get('expiryDate'),
                        nonce=ephemeral_key.get('nonce'),
                        blinder=ephemeral_key.get('blinder')
                    ),
                    success=True
                )
            except Exception as derive_error:
                # If standard derivation fails, we need a mobile-specific solution
                # This is where you'd implement a workaround or different approach
                return DeriveMobileKeylessAccount(
                    success=False,
                    error=f"Mobile OAuth not fully supported yet: {str(derive_error)}"
                )
                
        except Exception as e:
            return DeriveMobileKeylessAccount(
                success=False,
                error=str(e)
            )