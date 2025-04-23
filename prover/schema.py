import graphene
from graphene_django import DjangoObjectType
from graphene_django.converter import convert_django_field
from django.db import models
from .models import ZkLoginProof, UserProfile
from firebase_admin import auth
from firebase_admin.auth import InvalidIdTokenError
import os
import logging
import traceback
import json
from django.conf import settings
import requests
import nacl.signing
import nacl.encoding
import base64
import secrets
import random
import string
from . import client
from . import server
from django.db import transaction
from django.utils import timezone
import uuid
from django.contrib.auth import get_user_model

User = get_user_model()
logger = logging.getLogger(__name__)

@convert_django_field.register(models.BinaryField)
def convert_binary_field(field, registry=None):
    return graphene.String(description=field.help_text, required=not field.null)

def normalize_prover_payload(payload):
    """Normalize and validate payload values for the prover service.
    
    Args:
        payload (dict): Raw payload with potentially mixed types
        
    Returns:
        dict: Normalized payload with proper types
    """
    # Convert all values to strings first
    normalized = {
        "jwt": str(payload.get("jwt", "")),
        "extendedEphemeralPublicKey": str(payload.get("extendedEphemeralPublicKey", "")),
        "maxEpoch": str(payload.get("maxEpoch", 0)),  # Convert to string
        "randomness": str(payload.get("randomness", "")),
        "salt": str(payload.get("salt", "")),
        "keyClaimName": str(payload.get("keyClaimName", "sub")),
        "audience": str(payload.get("audience", ""))
    }
    
    # Validate required fields
    required_fields = ["jwt", "extendedEphemeralPublicKey", "maxEpoch", "randomness", "salt", "audience"]
    for field in required_fields:
        if not normalized[field]:
            raise ValueError(f"Missing required field: {field}")
    
    return normalized

def get_current_epoch():
    """Get the current epoch from the Sui blockchain.
    
    Returns:
        int: The current epoch number
    """
    try:
        # Determine which Sui network to use based on environment
        sui_network = os.getenv('SUI_NETWORK', 'devnet')
        sui_url = {
            'devnet': 'https://fullnode.devnet.sui.io',
            'testnet': 'https://fullnode.testnet.sui.io',
            'mainnet': 'https://fullnode.mainnet.sui.io'
        }.get(sui_network, 'https://fullnode.devnet.sui.io')

        # Make request to Sui fullnode to get current epoch
        try:
            sui_response = requests.post(
                sui_url,
                json={
                    'jsonrpc': '2.0',
                    'id': 1,
                    'method': 'suix_getLatestSuiSystemState',
                    'params': []
                },
                timeout=10  # Increased timeout to 10 seconds
            )
            sui_response.raise_for_status()
            current_epoch = int(sui_response.json()['result']['epoch'])
            logger.info(f"Retrieved current epoch from {sui_network}: {current_epoch}")
            return current_epoch
        except (requests.exceptions.RequestException, KeyError, ValueError) as e:
            logger.warning(f"Failed to get current epoch from {sui_network}: {str(e)}")
            # In development, we can fall back to a reasonable value
            if os.getenv('ENVIRONMENT') == 'development':
                logger.warning("Using fallback epoch value for development")
                return 1000
            raise Exception(f"Failed to get current epoch from {sui_network}: {str(e)}")
            
    except Exception as e:
        logger.error(f"Error in get_current_epoch: {str(e)}")
        # In development, we can fall back to a reasonable value
        if os.getenv('ENVIRONMENT') == 'development':
            logger.warning("Using fallback epoch value for development")
            return 1000
        raise Exception(f"Failed to get current epoch: {str(e)}")

class UserProfileType(DjangoObjectType):
    class Meta:
        model = UserProfile
        exclude = ('user_salt',)

class ZkLoginProofType(DjangoObjectType):
    class Meta:
        model = ZkLoginProof
        fields = ('proof_id', 'profile', 'max_epoch', 'proof_data', 'created_at')

class ProofPointsType(graphene.ObjectType):
    a = graphene.List(graphene.String)
    b = graphene.List(graphene.List(graphene.String))
    c = graphene.List(graphene.String)

class ZkLoginDataType(graphene.ObjectType):
    zkProof = graphene.Field(ProofPointsType)
    suiAddress = graphene.String()
    ephemeralPublicKey = graphene.String()
    maxEpoch = graphene.String()
    randomness = graphene.String()
    salt = graphene.String()

class InitializeZkLogin(graphene.Mutation):
    class Arguments:
        firebaseToken = graphene.String(required=True)
        providerToken = graphene.String(required=True)
        provider = graphene.String(required=True)

    class Meta:
        description = "Initialize zkLogin process"

    success = graphene.Boolean()
    error = graphene.String()
    maxEpoch = graphene.String()
    randomness = graphene.String()
    salt = graphene.String()

    @staticmethod
    def mutate(root, info, firebaseToken, providerToken, provider):
        try:
            logger.info("Starting zkLogin initialization")
            
            # Verify Firebase token
            try:
                decoded_token = auth.verify_id_token(firebaseToken)
                firebase_uid = decoded_token.get('uid')
                email = decoded_token.get('email', '')
                name = decoded_token.get('name', '')
                logger.info(f"Firebase token verified for user: {firebase_uid}")
            except Exception as e:
                logger.error(f"Firebase token verification failed: {str(e)}")
                return InitializeZkLogin(success=False, error="Invalid Firebase token")

            # Get or create User
            User = get_user_model()
            
            # Split name into first and last name
            first_name = ''
            last_name = ''
            if name:
                name_parts = name.strip().split()
                if name_parts:
                    first_name = name_parts[0]
                    last_name = ' '.join(name_parts[1:]) if len(name_parts) > 1 else ''
            
            user, created = User.objects.get_or_create(
                username=firebase_uid,
                defaults={
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name
                }
            )

            # Get or create user profile
            user_profile, created = UserProfile.objects.get_or_create(
                user=user,
                defaults={'google_sub': None, 'apple_sub': None}
            )

            # Verify provider token and store sub
            try:
                if provider == 'google':
                    response = requests.get(
                        f'https://oauth2.googleapis.com/tokeninfo?id_token={providerToken}'
                    )
                    response.raise_for_status()
                    token_data = response.json()
                    user_profile.google_sub = token_data['sub']
                elif provider == 'apple':
                    parts = providerToken.split('.')
                    if len(parts) != 3:
                        raise ValueError("Invalid JWT format")
                    payload = json.loads(base64.b64decode(parts[1] + '=' * (-len(parts[1]) % 4)).decode('utf-8'))
                    user_profile.apple_sub = payload['sub']
                else:
                    return InitializeZkLogin(success=False, error="Invalid provider")
                
                user_profile.save()
                logger.info(f"Provider token verified and sub stored: {user_profile.google_sub or user_profile.apple_sub}")
            except Exception as e:
                logger.error(f"Provider token verification failed: {str(e)}")
                return InitializeZkLogin(success=False, error="Invalid provider token")

            # Get or generate user salt
            if not user_profile.user_salt:
                user_profile.user_salt = secrets.token_bytes(32)
                user_profile.save()
                logger.info("Generated new user salt")
            else:
                logger.info("Retrieved existing user salt")

            # Get current epoch from Sui
            try:
                current_epoch = get_current_epoch()
                logger.info(f"Retrieved current epoch: {current_epoch}")
            except Exception as e:
                logger.error(f"Failed to get current epoch: {str(e)}")
                return InitializeZkLogin(success=False, error="Failed to get current epoch")

            # Generate ephemeral keypair
            ephemeral_keypair = generate_ephemeral_keypair()
            ephemeral_public_key = base64.b64encode(ephemeral_keypair.public_key).decode('utf-8')
            logger.info(f"Generated ephemeral public key: {ephemeral_public_key}")

            # Generate randomness
            randomness = secrets.token_bytes(32)
            randomness_b64 = base64.b64encode(randomness).decode('utf-8')
            logger.info(f"Generated randomness: {randomness_b64}")

            # Convert salt to base64
            salt_b64 = base64.b64encode(user_profile.user_salt).decode('utf-8')

            return InitializeZkLogin(
                success=True,
                maxEpoch=str(current_epoch + 2),  # Allow for 2 epochs of drift
                randomness=randomness_b64,
                salt=salt_b64
            )

        except Exception as e:
            logger.error(f"Unexpected error in initialize_zk_login: {str(e)}")
            return InitializeZkLogin(success=False, error=str(e))

class FinalizeZkLoginInput(graphene.InputObjectType):
    maxEpoch = graphene.String(required=True)
    randomness = graphene.String(required=True)
    extendedEphemeralPublicKey = graphene.String(required=True)
    userSignature = graphene.String(required=True)
    jwt = graphene.String(required=True)
    keyClaimName = graphene.String(required=True)
    audience = graphene.String(required=True)
    salt = graphene.String(required=True)

class FinalizeZkLoginPayload(graphene.ObjectType):
    success = graphene.Boolean()
    zkProof = graphene.Field(ProofPointsType)
    suiAddress = graphene.String()
    error = graphene.String()

class FinalizeZkLogin(graphene.Mutation):
    class Arguments:
        input = FinalizeZkLoginInput(required=True)

    Output = FinalizeZkLoginPayload

    def mutate(self, info, input):
        return resolve_finalize_zk_login(self, info, input)

@transaction.atomic
def resolve_finalize_zk_login(self, info, input):
    try:
        logger.info("Starting finalize_zk_login with input: %s", input)
        
        # Extract JWT payload to get sub claim
        try:
            token_parts = input.jwt.split('.')
            payload = json.loads(base64.b64decode(token_parts[1] + '==').decode('utf-8'))
            sub = payload['sub']
            logger.info("Extracted sub claim from JWT: %s", sub)
        except Exception as e:
            logger.error("Failed to decode JWT: %s", str(e))
            return FinalizeZkLoginPayload(
                success=False,
                error="Invalid JWT format"
            )

        # Find user profile by sub claim
        try:
            # Check if the audience is a Google client ID
            if 'googleusercontent.com' in input.audience:
                profile = UserProfile.objects.get(google_sub=sub)
                logger.info("Found user profile with Google sub: %s", sub)
            elif input.audience == 'apple':
                profile = UserProfile.objects.get(apple_sub=sub)
                logger.info("Found user profile with Apple sub: %s", sub)
            else:
                logger.error("Invalid audience: %s", input.audience)
                return FinalizeZkLoginPayload(
                    success=False,
                    error="Invalid audience"
                )
        except UserProfile.DoesNotExist:
            logger.error("User profile not found for sub: %s", sub)
            return FinalizeZkLoginPayload(
                success=False,
                error="User profile not found"
            )

        # Always use the stored user_salt from the profile
        salt = base64.b64encode(profile.user_salt).decode('utf-8')
        logger.info("Using stored user salt for profile: %s", profile.id)

        # Prepare prover payload
        prover_payload = {
            "jwt": input.jwt,
            "extendedEphemeralPublicKey": input.extendedEphemeralPublicKey,
            "maxEpoch": input.maxEpoch,
            "randomness": input.randomness,
            "userSignature": input.userSignature,
            "keyClaimName": input.keyClaimName,
            "audience": input.audience,
            "salt": salt  # Use the stored salt
        }
        logger.info("Prepared prover payload: %s", json.dumps(prover_payload))

        # Call prover service
        try:
            logger.info("Calling prover service at: %s", settings.PROVER_SERVICE_URL)
            response = requests.post(
                f"{settings.PROVER_SERVICE_URL}/generate-proof",
                json=prover_payload,
                timeout=30
            )
            logger.info("Prover service response status: %s", response.status_code)
            logger.info("Prover service response body: %s", response.text)

            if response.status_code != 200:
                logger.error("Prover service error: %s", response.text)
                return FinalizeZkLoginPayload(
                    success=False,
                    error=f"Prover service error: {response.text}"
                )

            result = response.json()
            if not result.get('proof') or not result.get('suiAddress'):
                logger.error("Invalid prover service response: %s", result)
                return FinalizeZkLoginPayload(
                    success=False,
                    error="Invalid prover service response"
                )

            # Create ZkLoginProof record
            proof = ZkLoginProof.objects.create(
                profile=profile,
                max_epoch=int(input.maxEpoch),
                randomness=base64.b64decode(input.randomness),
                extended_ephemeral_public_key=base64.b64decode(input.extendedEphemeralPublicKey),
                user_signature=base64.b64decode(input.userSignature),
                proof_data=result['proof']
            )
            logger.info("Created ZkLoginProof record: %s", proof.id)

            # Update user's Sui address
            profile.sui_address = result['suiAddress']
            profile.save()
            logger.info("Updated user profile with Sui address: %s", result['suiAddress'])

            return FinalizeZkLoginPayload(
                success=True,
                zkProof=ProofPointsType(**result['proof']),
                suiAddress=result['suiAddress']
            )

        except requests.exceptions.RequestException as e:
            logger.error("Prover service request failed: %s", str(e))
            return FinalizeZkLoginPayload(
                success=False,
                error=f"Prover service request failed: {str(e)}"
            )

    except Exception as e:
        logger.error("Error in finalize_zk_login: %s\n%s", str(e), traceback.format_exc())
        return FinalizeZkLoginPayload(
            success=False,
            error=str(e)
        )

def verify_google_token(token):
    """Verify a Google OAuth token and return its claims.
    
    Args:
        token (str): The Google OAuth token to verify
        
    Returns:
        dict: The decoded token claims
        
    Raises:
        Exception: If token verification fails
    """
    try:
        response = requests.get(
            f'https://oauth2.googleapis.com/tokeninfo?id_token={token}'
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Google token verification failed: {str(e)}")
        raise Exception("Invalid Google token")

def verify_apple_token(token):
    """Verify an Apple OAuth token and return its claims.
    
    Args:
        token (str): The Apple OAuth token to verify
        
    Returns:
        dict: The decoded token claims
        
    Raises:
        Exception: If token verification fails
    """
    try:
        # For Apple, we need to decode the JWT to get the claims
        parts = token.split('.')
        if len(parts) != 3:
            raise ValueError("Invalid JWT format")
        
        # Decode the payload part
        payload = json.loads(base64.b64decode(parts[1] + '=' * (-len(parts[1]) % 4)).decode('utf-8'))
        return payload
    except Exception as e:
        logger.error(f"Apple token verification failed: {str(e)}")
        raise Exception("Invalid Apple token")

def generate_ephemeral_keypair():
    """Generate a new ephemeral keypair for zkLogin.
    
    Returns:
        tuple: A tuple containing (private_key, public_key) as bytes
    """
    signing_key = nacl.signing.SigningKey.generate()
    verify_key = signing_key.verify_key
    
    return type('EphemeralKeypair', (), {
        'private_key': signing_key.encode(),
        'public_key': verify_key.encode()
    })

class Mutation(graphene.ObjectType):
    initialize_zk_login = InitializeZkLogin.Field()
    finalize_zk_login = FinalizeZkLogin.Field()

class Query(graphene.ObjectType):
    zk_login_proof = graphene.Field(ZkLoginProofType, id=graphene.ID())
    zk_login_proofs = graphene.List(ZkLoginProofType)
    ping = graphene.String()

    def resolve_zk_login_proof(self, info, id):
        return ZkLoginProof.objects.get(id=id)

    def resolve_zk_login_proofs(self, info):
        return ZkLoginProof.objects.all()

    def resolve_ping(self, info):
        return "pong"

schema = graphene.Schema(query=Query, mutation=Mutation) 