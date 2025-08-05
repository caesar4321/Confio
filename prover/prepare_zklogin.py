"""
Mutation to prepare zkLogin parameters before OAuth sign-in
This allows the client to get the necessary parameters to compute the nonce
BEFORE initiating OAuth flow
"""

import graphene
import secrets
import base64
from prover.schema import get_current_epoch

class PrepareZkLogin(graphene.Mutation):
    """
    Prepare zkLogin parameters before OAuth sign-in.
    This mutation is PUBLIC (no authentication required).
    
    Returns:
    - maxEpoch: The maximum epoch for the zkLogin proof
    - randomness: 16-byte randomness for nonce computation (base64)
    
    The client should:
    1. Call this mutation first
    2. Generate salt and ephemeral keypair locally
    3. Compute zkLogin nonce using these parameters
    4. Pass the nonce to OAuth provider
    5. Complete OAuth flow with correct nonce in JWT
    """
    
    class Meta:
        description = "Prepare zkLogin parameters before OAuth sign-in (PUBLIC)"
    
    success = graphene.Boolean()
    maxEpoch = graphene.String()
    randomness = graphene.String()
    error = graphene.String()
    
    @staticmethod
    def mutate(root, info):
        try:
            # Get current epoch
            current_epoch = get_current_epoch()
            max_epoch = str(current_epoch + 100)  # 100 epochs from now
            
            # Generate 16-byte randomness for Mysten prover compatibility
            randomness_bytes = secrets.token_bytes(16)
            randomness = base64.b64encode(randomness_bytes).decode('utf-8')
            
            return PrepareZkLogin(
                success=True,
                maxEpoch=max_epoch,
                randomness=randomness
            )
            
        except Exception as e:
            return PrepareZkLogin(
                success=False,
                error=str(e)
            )