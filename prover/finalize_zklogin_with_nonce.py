"""
New FinalizeZkLoginWithNonce mutation that properly handles the Apple nonce flow.

This mutation:
1. Accepts the JWT that already has the correct nonce (SHA256 for Apple, plain for Google)
2. Verifies Firebase auth and creates/updates user
3. Calls the prover with the correct payload
4. Returns auth tokens and zkProof
"""

import graphene
import json
import base64
import requests
import logging
from django.contrib.auth import get_user_model
from django.conf import settings
from firebase_admin import auth as firebase_auth
from users.models import Account
from users.utils import (
    generate_access_token,
    generate_refresh_token,
    track_device_fingerprint,
    check_phone_verification
)

logger = logging.getLogger(__name__)
User = get_user_model()

class ZkProofType(graphene.ObjectType):
    a = graphene.List(graphene.String)
    b = graphene.List(graphene.List(graphene.String))
    c = graphene.List(graphene.String)

class FinalizeZkLoginWithNonce(graphene.Mutation):
    """
    New mutation that handles the correct zkLogin flow where the nonce
    is passed to the OAuth provider BEFORE authentication.
    """
    
    class Arguments:
        firebase_token = graphene.String(required=True)
        provider_token = graphene.String(required=True)
        provider = graphene.String(required=True)
        extended_ephemeral_public_key = graphene.String(required=True)
        max_epoch = graphene.String(required=True)
        randomness = graphene.String(required=True)
        salt = graphene.String(required=True)
        user_signature = graphene.String(required=True)
        key_claim_name = graphene.String(required=True)
        account_type = graphene.String()
        account_index = graphene.Int()
        device_fingerprint = graphene.JSONString()
    
    success = graphene.Boolean()
    zk_proof = graphene.Field(ZkProofType)
    aptos_address = graphene.String()
    auth_access_token = graphene.String()
    auth_refresh_token = graphene.String()
    is_phone_verified = graphene.Boolean()
    error = graphene.String()
    
    @staticmethod
    def mutate(root, info, firebase_token, provider_token, provider, 
               extended_ephemeral_public_key, max_epoch, randomness, salt,
               user_signature, key_claim_name, account_type=None, 
               account_index=None, device_fingerprint=None):
        try:
            logger.info(f"Starting FinalizeZkLoginWithNonce for provider: {provider}")
            
            # Verify Firebase token
            try:
                decoded_firebase = firebase_auth.verify_id_token(firebase_token)
                firebase_uid = decoded_firebase['uid']
                logger.info(f"Firebase token verified for user: {firebase_uid}")
            except Exception as e:
                logger.error(f"Firebase token verification failed: {str(e)}")
                return FinalizeZkLoginWithNonce(
                    success=False,
                    error=f"Firebase authentication failed: {str(e)}"
                )
            
            # Get or create user
            email = decoded_firebase.get('email', '')
            user, created = User.objects.get_or_create(
                firebase_uid=firebase_uid,
                defaults={
                    'username': email.split('@')[0] if email else firebase_uid[:30],
                    'email': email,
                    'is_active': True
                }
            )
            
            if created:
                logger.info(f"Created new user: {user.username}")
            else:
                logger.info(f"Found existing user: {user.username}")
            
            # Track device fingerprint
            if device_fingerprint:
                try:
                    fingerprint_data = json.loads(device_fingerprint) if isinstance(device_fingerprint, str) else device_fingerprint
                    track_device_fingerprint(user, fingerprint_data, info.context)
                except Exception as e:
                    logger.error(f"Error tracking device fingerprint: {str(e)}")
            
            # Check phone verification status
            is_phone_verified = check_phone_verification(user)
            
            # Generate auth tokens
            access_token = generate_access_token(user)
            refresh_token = generate_refresh_token(user)
            
            # Prepare prover payload - JWT already has the correct nonce!
            prover_payload = {
                "jwt": provider_token,  # This JWT already has the correct nonce
                "extendedEphemeralPublicKey": extended_ephemeral_public_key,
                "maxEpoch": max_epoch,
                "jwtRandomness": randomness,
                "userSignature": user_signature,
                "keyClaimName": key_claim_name,
                "audience": provider,
                "salt": salt
            }
            
            logger.info(f"Calling prover service with payload for {provider}")
            
            # Call the prover service
            prover_url = f"{settings.PROVER_SERVICE_URL}/v1"
            headers = {"Content-Type": "application/json"}
            
            response = requests.post(prover_url, json=prover_payload, headers=headers)
            
            if response.status_code != 200:
                error_msg = response.text
                logger.error(f"Prover service error: {error_msg}")
                return FinalizeZkLoginWithNonce(
                    success=False,
                    error=f"Prover service error: {error_msg}"
                )
            
            prover_result = response.json()
            logger.info("Prover service returned successful proof")
            
            # Extract proof and address
            zk_proof = ZkProofType(
                a=prover_result['zkProof']['a'],
                b=prover_result['zkProof']['b'],
                c=prover_result['zkProof']['c']
            )
            aptos_address = prover_result['suiAddress']
            
            # Get or create account
            account_type = account_type or 'personal'
            account_index = account_index or 0
            account_id = f"{account_type}_{account_index}"
            
            account, _ = Account.objects.get_or_create(
                user=user,
                account_id=account_id,
                defaults={
                    'account_type': account_type,
                    'account_index': account_index,
                    'aptos_address': aptos_address,
                    'is_active': True
                }
            )
            
            # Update Aptos address if changed
            if account.aptos_address != aptos_address:
                account.aptos_address = aptos_address
                account.save()
            
            logger.info(f"Account {account_id} ready with Aptos address: {aptos_address}")
            
            return FinalizeZkLoginWithNonce(
                success=True,
                zk_proof=zk_proof,
                aptos_address=aptos_address,
                auth_access_token=access_token,
                auth_refresh_token=refresh_token,
                is_phone_verified=is_phone_verified
            )
            
        except Exception as e:
            logger.error(f"Error in FinalizeZkLoginWithNonce: {str(e)}")
            return FinalizeZkLoginWithNonce(
                success=False,
                error=str(e)
            )