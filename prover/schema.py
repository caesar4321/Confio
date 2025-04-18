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

class UserProfileType(DjangoObjectType):
    class Meta:
        model = UserProfile
        exclude = ('user_salt',)

class ZkLoginProofType(DjangoObjectType):
    class Meta:
        model = ZkLoginProof
        exclude = ('randomness', 'salt', 'user_salt', 'extended_ephemeral_public_key', 'user_signature')

    # Add computed fields for binary data
    randomness = graphene.String()
    salt = graphene.String()
    user_salt = graphene.String()
    extended_ephemeral_public_key = graphene.String()
    user_signature = graphene.String()

    def resolve_randomness(self, info):
        return base64.b64encode(self.randomness).decode('utf-8') if self.randomness else None

    def resolve_salt(self, info):
        return base64.b64encode(self.salt).decode('utf-8') if self.salt else None

    def resolve_user_salt(self, info):
        return base64.b64encode(self.user_salt).decode('utf-8') if self.user_salt else None

    def resolve_extended_ephemeral_public_key(self, info):
        return base64.b64encode(self.extended_ephemeral_public_key).decode('utf-8') if self.extended_ephemeral_public_key else None

    def resolve_user_signature(self, info):
        return base64.b64encode(self.user_signature).decode('utf-8') if self.user_signature else None

class GenerateZkLoginProof(graphene.Mutation):
    class Arguments:
        jwt = graphene.String(required=True)
        max_epoch = graphene.Int(required=True)
        randomness = graphene.String(required=True)
        salt = graphene.String(required=True)

    proof = graphene.Field(ZkLoginProofType)
    error = graphene.String()

    def mutate(self, info, jwt, max_epoch, randomness, salt):
        try:
            # TODO: Implement actual zkLogin proof generation
            # This is a placeholder for the actual implementation
            proof = ZkLoginProof.objects.create(
                jwt=jwt,
                max_epoch=max_epoch,
                randomness=randomness,
                salt=salt,
                proof_data="{}"  # Placeholder for actual proof data
            )
            return GenerateZkLoginProof(proof=proof)
        except Exception as e:
            return GenerateZkLoginProof(error=str(e))

class VerifyZkLoginProof(graphene.Mutation):
    class Arguments:
        proof_id = graphene.ID(required=True)

    success = graphene.Boolean()
    error = graphene.String()

    def mutate(self, info, proof_id):
        try:
            proof = ZkLoginProof.objects.get(id=proof_id)
            # TODO: Implement actual proof verification
            # This is a placeholder for the actual implementation
            return VerifyZkLoginProof(success=True)
        except ZkLoginProof.DoesNotExist:
            return VerifyZkLoginProof(error="Proof not found")
        except Exception as e:
            return VerifyZkLoginProof(error=str(e))

class TokenVerificationType(graphene.ObjectType):
    sub = graphene.String()
    aud = graphene.String()
    iss = graphene.String()
    email = graphene.String()
    email_verified = graphene.Boolean()
    name = graphene.String()
    picture = graphene.String()

class FirebaseUserType(graphene.ObjectType):
    uid = graphene.String()
    email = graphene.String()
    name = graphene.String()
    picture = graphene.String()

class GoogleTokenDataType(graphene.ObjectType):
    sub = graphene.String()
    aud = graphene.String()
    iss = graphene.String()
    email = graphene.String()
    email_verified = graphene.Boolean()
    name = graphene.String()
    picture = graphene.String()

class ProofPointsType(graphene.ObjectType):
    a = graphene.List(graphene.String, required=True)
    b = graphene.List(graphene.List(graphene.String), required=True)
    c = graphene.List(graphene.String, required=True)

class ZkLoginDataType(graphene.ObjectType):
    zkProof = graphene.Field(ProofPointsType)
    suiAddress = graphene.String()
    ephemeralPublicKey = graphene.String()
    maxEpoch = graphene.String()
    randomness = graphene.String()
    salt = graphene.String()

class VerifyToken(graphene.Mutation):
    class Arguments:
        firebaseToken = graphene.String(required=True)
        googleToken = graphene.String(required=True)

    success = graphene.Boolean()
    error = graphene.String()
    details = graphene.String()
    firebaseUser = graphene.Field(FirebaseUserType)
    googleTokenData = graphene.Field(GoogleTokenDataType)
    zkLoginData = graphene.Field(ZkLoginDataType)

    def mutate(self, info, firebaseToken, googleToken):
        try:
            logger.info("Starting token verification process")
            logger.debug(f"Firebase token (first 20 chars): {firebaseToken[:20]}...")
            logger.debug(f"Google token (first 20 chars): {googleToken[:20]}...")
            
            # Validate input tokens
            if not firebaseToken or not googleToken:
                logger.error("Missing required tokens")
                return VerifyToken(
                    success=False,
                    error="Missing required tokens",
                    details="Both firebaseToken and googleToken are required"
                )

            # Verify Firebase token using Admin SDK
            logger.info("Verifying Firebase token")
            try:
                decoded_token = auth.verify_id_token(firebaseToken)
                logger.debug(f"Firebase token decoded: {json.dumps(decoded_token, indent=2)}")
                logger.info("Firebase token verified successfully")
            except auth.InvalidIdTokenError as e:
                logger.error(f"Firebase token verification failed: {str(e)}")
                return VerifyToken(
                    success=False,
                    error="Firebase token verification failed",
                    details=str(e)
                )

            # Verify Google token
            logger.info("Verifying Google token")
            try:
                google_response = requests.get(
                    f'https://oauth2.googleapis.com/tokeninfo?id_token={googleToken}'
                )
                google_response.raise_for_status()
                google_data = google_response.json()
                logger.debug(f"Google token response: {json.dumps(google_data, indent=2)}")
                logger.info("Google token verified successfully")
            except requests.exceptions.RequestException as e:
                logger.error(f"Google token verification failed: {str(e)}")
                return VerifyToken(
                    success=False,
                    error="Google token verification failed",
                    details=str(e)
                )

            # Generate zkLogin inputs
            logger.info("Generating zkLogin inputs")
            try:
                # 1. Generate user salt
                user_salt = base64.b64encode(os.urandom(32)).decode()
                logger.info(f"Generated user salt: {user_salt}")

                # 2. Get current epoch from Sui
                sui_response = requests.post(
                    'https://fullnode.devnet.sui.io',
                    json={
                        'jsonrpc': '2.0',
                        'id': 1,
                        'method': 'suix_getLatestSuiSystemState',
                        'params': []
                    }
                )
                sui_response.raise_for_status()
                current_epoch = int(sui_response.json()['result']['epoch'])  # Convert to int
                logger.info(f"Retrieved current epoch: {current_epoch}")

                # 3. Generate ephemeral keypair
                signing_key = nacl.signing.SigningKey.generate()
                ephemeral_public_key = base64.b64encode(signing_key.verify_key.encode()).decode()
                logger.info(f"Generated ephemeral public key: {ephemeral_public_key}")

                # 4. Generate randomness
                randomness = base64.b64encode(os.urandom(32)).decode()
                logger.info(f"Generated randomness: {randomness}")

                # 5. Call zkLogin Prover service
                raw_payload = {
                    'jwt': googleToken,
                    'extendedEphemeralPublicKey': ephemeral_public_key,
                    'maxEpoch': str(current_epoch + 2),
                    'randomness': randomness,
                    'salt': user_salt,
                    'keyClaimName': 'sub',
                    'audience': google_data.get('aud', '')
                }
                # this will cast every value to str and blow up if any required key is missing
                prover_payload = normalize_prover_payload(raw_payload)
                logger.debug(f"Prover service payload (all strings):\n{json.dumps(prover_payload, indent=2)}")

                prover_response = requests.post(
                    'http://localhost:3001/generate-proof',
                    json=prover_payload
                )
                prover_response.raise_for_status()
                prover_data = prover_response.json()
                logger.debug(f"Prover service response: {json.dumps(prover_data, indent=2)}")
                logger.info("Generated zkLogin proof successfully")

            except Exception as e:
                logger.exception("Failed to generate zkLogin inputs")
                return VerifyToken(
                    success=False,
                    error="Failed to generate zkLogin inputs",
                    details=f"Internal error: {str(e)}",
                    firebaseUser=None,
                    googleTokenData=None,
                    zkLoginData=None
                )

            # Return success response
            logger.info("Token verification process completed successfully")
            return VerifyToken(
                success=True,
                error=None,
                details=None,
                firebaseUser=FirebaseUserType(
                    uid=decoded_token['uid'],
                    email=decoded_token.get('email', ''),
                    name=decoded_token.get('name', ''),
                    picture=decoded_token.get('picture', '')
                ),
                googleTokenData=GoogleTokenDataType(
                    sub=google_data['sub'],
                    aud=google_data['aud'],
                    iss=google_data['iss'],
                    email=google_data['email'],
                    email_verified=google_data['email_verified'] == 'true',
                    name=google_data.get('name', ''),
                    picture=google_data.get('picture', '')
                ),
                zkLoginData=ZkLoginDataType(
                    zkProof=ProofPointsType(
                        a=prover_data['proof']['a'],
                        b=prover_data['proof']['b'],
                        c=prover_data['proof']['c']
                    ),
                    suiAddress=prover_data['suiAddress'],
                    ephemeralPublicKey=ephemeral_public_key,
                    maxEpoch=str(current_epoch + 2),
                    randomness=randomness,
                    salt=user_salt
                )
            )

        except Exception as e:
            logger.error(f"Unexpected error in VerifyToken mutation: {str(e)}", exc_info=True)
            return VerifyToken(
                success=False,
                error="Unexpected error",
                details=str(e)
            )

class ZkLoginInput(graphene.InputObjectType):
    jwt = graphene.String(required=True)
    max_epoch = graphene.Int(required=True)
    randomness = graphene.String(required=True)
    key_claim_name = graphene.String(required=True)
    extended_ephemeral_public_key = graphene.String(required=True)
    salt = graphene.String(required=True)
    audience = graphene.String(required=True)

class ZkLoginResult(graphene.ObjectType):
    zk_proof = graphene.JSONString()
    sui_address = graphene.String()
    error = graphene.String()
    details = graphene.String()

class ZkLoginMutation(graphene.Mutation):
    class Arguments:
        input = ZkLoginInput(required=True)

    Output = ZkLoginResult

    def mutate(self, info, input):
        try:
            # Verify Google token
            google_info = id_token.verify_oauth2_token(
                input.jwt,
                google_requests.Request(),
                input.audience
            )

            # Call zkLogin Prover service
            prover_url = "http://localhost:3001"  # Base URL without endpoint
            payload = {
                "jwt": input.jwt,
                "maxEpoch": str(input.max_epoch),  # Convert to string
                "jwtRandomness": input.randomness,
                "keyClaimName": input.key_claim_name,
                "extendedEphemeralPublicKey": input.extended_ephemeral_public_key,
                "salt": input.salt,
                "audience": input.audience
            }

            response = requests.post(prover_url + "/generate-proof", json=payload)
            response.raise_for_status()
            zk_proof = response.json()

            # The prover service should return the Sui address
            sui_address = zk_proof.get('suiAddress')

            return ZkLoginResult(
                zk_proof=zk_proof['proof'],
                sui_address=sui_address
            )

        except Exception as e:
            return ZkLoginResult(
                error="zkLogin error",
                details=str(e)
            )

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

class FirebaseLoginPayload(graphene.ObjectType):
    success = graphene.Boolean()
    error = graphene.String()
    user_profile = graphene.Field(UserProfileType)

class FirebaseLogin(graphene.Mutation):
    class Arguments:
        firebase_token = graphene.String(required=True)

    Output = FirebaseLoginPayload

    def mutate(self, info, firebase_token):
        try:
            # Verify Firebase token
            try:
                decoded_token = auth.verify_id_token(firebase_token)
                firebase_uid = decoded_token['uid']
                email = decoded_token.get('email', '')
                name = decoded_token.get('name', '')
            except Exception as e:
                logger.error(f"Firebase token verification failed: {str(e)}")
                return FirebaseLoginPayload(
                    success=False,
                    error=f"Invalid Firebase token: {str(e)}"
                )

            # Create or update Django User
            with transaction.atomic():
                user, created = User.objects.get_or_create(
                    username=firebase_uid,
                    defaults={
                        'email': email,
                        'first_name': name.split()[0] if name else '',
                        'last_name': ' '.join(name.split()[1:]) if name and len(name.split()) > 1 else ''
                    }
                )
                
                if not created:
                    # Update existing user's information
                    user.email = email
                    if name:
                        user.first_name = name.split()[0]
                        user.last_name = ' '.join(name.split()[1:]) if len(name.split()) > 1 else ''
                    user.save()

                # Create or update UserProfile
                profile, profile_created = UserProfile.objects.get_or_create(
                    user=user,
                    defaults={
                        'created_at': timezone.now()
                    }
                )
                
                # Update last login
                profile.last_login_at = timezone.now()
                profile.save()

            logger.info(f"User login successful: {firebase_uid}")
            return FirebaseLoginPayload(
                success=True,
                user_profile=profile
            )

        except Exception as e:
            logger.error(f"Error in FirebaseLogin: {str(e)}")
            return FirebaseLoginPayload(
                success=False,
                error=str(e)
            )

class InitializeZkLogin(graphene.Mutation):
    class Arguments:
        firebase_token = graphene.String(required=True)
        provider_token = graphene.String(required=True)
        provider = graphene.String(required=True)  # 'google' or 'apple'

    maxEpoch = graphene.Int()
    randomness = graphene.String()
    salt = graphene.String()

    def mutate(self, info, firebase_token, provider_token, provider):
        try:
            # Verify Firebase token and get user
            decoded_token = auth.verify_id_token(firebase_token)
            firebase_uid = decoded_token['uid']
            email = decoded_token.get('email', '')
            name = decoded_token.get('name', '')
            
            # Verify provider token based on provider type
            if provider == 'google':
                try:
                    google_response = requests.get(
                        f'https://oauth2.googleapis.com/tokeninfo?id_token={provider_token}'
                    )
                    google_response.raise_for_status()
                    provider_data = google_response.json()
                    provider_sub = provider_data['sub']
                except requests.exceptions.RequestException as e:
                    logger.error(f"Google token verification failed: {str(e)}")
                    raise Exception("Invalid Google token")
            elif provider == 'apple':
                try:
                    # Apple token verification
                    token_parts = provider_token.split('.')
                    if len(token_parts) != 3:
                        raise Exception("Invalid Apple token format")
                    
                    # Decode the payload (second part)
                    payload = json.loads(base64.urlsafe_b64decode(token_parts[1] + '=' * (-len(token_parts[1]) % 4)).decode())
                    provider_sub = payload.get('sub')
                    if not provider_sub:
                        raise Exception("Missing sub claim in Apple token")
                except Exception as e:
                    logger.error(f"Apple token verification failed: {str(e)}")
                    raise Exception("Invalid Apple token")
            else:
                raise Exception(f"Unsupported provider: {provider}")
            
            # Create or get user profile
            with transaction.atomic():
                user, created = User.objects.get_or_create(
                    username=firebase_uid,
                    defaults={
                        'email': email,
                        'first_name': name.split()[0] if name else '',
                        'last_name': ' '.join(name.split()[1:]) if name and len(name.split()) > 1 else ''
                    }
                )
                
                if not created:
                    # Update existing user's information
                    user.email = email
                    if name:
                        user.first_name = name.split()[0]
                        user.last_name = ' '.join(name.split()[1:]) if len(name.split()) > 1 else ''
                    user.save()

                # Create or get UserProfile
                profile, profile_created = UserProfile.objects.get_or_create(
                    user=user,
                    defaults={
                        'created_at': timezone.now()
                    }
                )
                
                # Store provider sub in profile for Sui operations
                if provider == 'google':
                    profile.google_sub = provider_sub
                elif provider == 'apple':
                    profile.apple_sub = provider_sub
                profile.save()
                
                # Generate user salt if it doesn't exist
                if not profile.user_salt:
                    profile.user_salt = os.urandom(32)
                    profile.save()
            
            # Generate randomness
            randomness_bytes = os.urandom(32)
            base64_randomness = base64.b64encode(randomness_bytes).decode('utf-8')
            
            # Get current epoch from Sui blockchain
            try:
                max_epoch = get_current_epoch()
            except Exception as e:
                if os.getenv('ENVIRONMENT', 'development') == 'development':
                    logger.warning(f"Using fallback epoch value due to error: {str(e)}")
                    max_epoch = 1000
                else:
                    raise Exception(f"Failed to get current epoch: {str(e)}")
            
            logger.info(f"Initialized zkLogin for user {firebase_uid} with provider {provider}")
            
            return InitializeZkLogin(
                maxEpoch=max_epoch,
                randomness=base64_randomness,
                salt=base64.b64encode(profile.user_salt).decode('utf-8') if profile.user_salt else None
            )
            
        except Exception as e:
            logger.error(f"Error in InitializeZkLogin: {str(e)}")
            raise Exception(f"Failed to initialize zkLogin: {str(e)}")

class InitializeAppleZkLogin(graphene.Mutation):
    class Arguments:
        firebase_token = graphene.String(required=True)
        apple_token = graphene.String(required=True)

    maxEpoch = graphene.Int()
    randomness = graphene.String()
    salt = graphene.String()

    def mutate(self, info, firebase_token, apple_token):
        try:
            # Verify Firebase token and get user
            decoded_token = auth.verify_id_token(firebase_token)
            firebase_uid = decoded_token['uid']
            email = decoded_token.get('email', '')
            name = decoded_token.get('name', '')
            
            # Verify Apple token
            try:
                # Apple token verification is different from Google
                # We'll need to implement proper Apple token verification
                # For now, we'll just decode the token to get the claims
                import jwt
                apple_data = jwt.decode(apple_token, options={"verify_signature": False})
                
                # Verify that the Apple token matches the Firebase user
                if apple_data['sub'] != decoded_token['firebase']['identities']['apple.com'][0]:
                    raise Exception("Apple token does not match Firebase user")
                    
            except Exception as e:
                logger.error(f"Apple token verification failed: {str(e)}")
                raise Exception("Invalid Apple token")
            
            # Create or get user profile
            with transaction.atomic():
                user, created = User.objects.get_or_create(
                    username=firebase_uid,
                    defaults={
                        'email': email,
                        'first_name': name.split()[0] if name else '',
                        'last_name': ' '.join(name.split()[1:]) if name and len(name.split()) > 1 else ''
                    }
                )
                
                if not created:
                    # Update existing user's information
                    user.email = email
                    if name:
                        user.first_name = name.split()[0]
                        user.last_name = ' '.join(name.split()[1:]) if len(name.split()) > 1 else ''
                    user.save()

                # Create or get UserProfile
                profile, profile_created = UserProfile.objects.get_or_create(
                    user=user,
                    defaults={
                        'created_at': timezone.now()
                    }
                )
                
                # Generate user salt if it doesn't exist
                if not profile.user_salt:
                    profile.user_salt = os.urandom(32)
                    profile.save()
            
            # Generate randomness
            randomness_bytes = os.urandom(32)
            base64_randomness = base64.b64encode(randomness_bytes).decode('utf-8')
            
            # Get current epoch from Sui blockchain
            try:
                max_epoch = get_current_epoch()
            except Exception as e:
                if os.getenv('ENVIRONMENT', 'development') == 'development':
                    logger.warning(f"Using fallback epoch value due to error: {str(e)}")
                    max_epoch = 1000
                else:
                    raise Exception(f"Failed to get current epoch: {str(e)}")
            
            logger.info(f"Initialized Apple zkLogin for user {firebase_uid}")
            
            return InitializeAppleZkLogin(
                maxEpoch=max_epoch,
                randomness=base64_randomness,
                salt=base64.b64encode(profile.user_salt).decode('utf-8') if profile.user_salt else None
            )
            
        except Exception as e:
            logger.error(f"Error in InitializeAppleZkLogin: {str(e)}")
            raise Exception(f"Failed to initialize Apple zkLogin: {str(e)}")

class FinalizeZkLoginInput(graphene.InputObjectType):
    maxEpoch = graphene.String(required=True)
    randomness = graphene.String(required=True)
    salt = graphene.String(required=True)
    extendedEphemeralPublicKey = graphene.String(required=True)
    userSignature = graphene.String(required=True)
    jwt = graphene.String(required=True)
    keyClaimName = graphene.String(required=True)
    audience = graphene.String(required=True)

class FinalizeZkLoginPayload(graphene.ObjectType):
    success = graphene.Boolean()
    zkProof = graphene.Field(ProofPointsType)
    suiAddress = graphene.String()
    error = graphene.String()

def resolve_finalize_zk_login(self, info, input):
    try:
        # Get the JWT and audience from input
        jwt_token = input.get('jwt')
        audience = input.get('audience')
        if not jwt_token or not audience:
            raise Exception("JWT and audience are required")
        
        # Verify the token based on audience
        if audience == 'apple':
            try:
                # Apple token verification
                token_parts = jwt_token.split('.')
                if len(token_parts) != 3:
                    raise Exception("Invalid Apple token format")
                
                # Decode the payload (second part)
                payload = json.loads(base64.urlsafe_b64decode(token_parts[1] + '=' * (-len(token_parts[1]) % 4)).decode())
                provider_sub = payload.get('sub')
                if not provider_sub:
                    raise Exception("Missing sub claim in Apple token")
                
                # Get user from provider sub
                try:
                    profile = UserProfile.objects.get(apple_sub=provider_sub)
                    user = profile.user
                except UserProfile.DoesNotExist:
                    raise Exception("User must be created through Firebase login first")
                
            except Exception as e:
                logger.error(f"Error verifying Apple token or getting user: {str(e)}")
                raise Exception("Invalid Apple token or user not found")
        else:
            try:
                # Google token verification
                google_response = requests.get(
                    f'https://oauth2.googleapis.com/tokeninfo?id_token={jwt_token}'
                )
                google_response.raise_for_status()
                google_data = google_response.json()
                
                # Verify audience matches
                if google_data.get('aud') != audience:
                    raise Exception(f"Invalid audience. Expected {audience}, got {google_data.get('aud')}")
                
                # Get Google sub claim for Sui operations
                provider_sub = google_data.get('sub')
                if not provider_sub:
                    raise Exception("Missing sub claim in Google token")
                
                # Get user from provider sub
                try:
                    profile = UserProfile.objects.get(google_sub=provider_sub)
                    user = profile.user
                except UserProfile.DoesNotExist:
                    raise Exception("User must be created through Firebase login first")
                
            except Exception as e:
                logger.error(f"Error verifying Google token or getting user: {str(e)}")
                raise Exception("Invalid Google token or user not found")

        # Prepare the request to the prover service
        prover_url = "http://localhost:3001"  # Base URL without endpoint
        request_body = {
            'jwt': jwt_token,
            'maxEpoch': input.get('maxEpoch'),
            'randomness': input.get('randomness'),
            'salt': input.get('salt'),
            'extendedEphemeralPublicKey': input.get('extendedEphemeralPublicKey'),
            'userSignature': input.get('userSignature'),
            'keyClaimName': input.get('keyClaimName'),
            'audience': audience
        }
        
        logger.info(f"Sending request to prover service: {request_body}")
        
        # Make the request to the prover service
        response = requests.post(
            f"{prover_url}/generate-proof",  # Append endpoint here
            json=request_body,
            timeout=30
        )
        
        if response.status_code != 200:
            logger.error(f"Prover service error: {response.text}")
            raise Exception(f"Prover service error: {response.text}")
        
        prover_response = response.json()
        
        # Validate the response structure
        if 'proof' not in prover_response or 'suiAddress' not in prover_response:
            logger.error(f"Invalid prover response structure: {prover_response}")
            raise Exception("Invalid response from prover service")
        
        # Create the ZkLoginProof record
        proof = ZkLoginProof.objects.create(
            proof_id=str(uuid.uuid4()),
            jwt=jwt_token,
            max_epoch=input.get('maxEpoch'),
            randomness=base64.b64decode(input.get('randomness')),
            salt=base64.b64decode(input.get('salt')),
            user_salt=base64.b64decode(input.get('userSignature')),
            extended_ephemeral_public_key=base64.b64decode(input.get('extendedEphemeralPublicKey')),
            user_signature=base64.b64decode(input.get('userSignature')),
            proof=prover_response['proof'],
            user=user
        )
        
        # Update user profile with Sui address
        profile.sui_address = prover_response['suiAddress']
        profile.save()
        
        return FinalizeZkLoginPayload(
            success=True,
            zkProof=ProofPointsType(
                a=prover_response['proof']['a'],
                b=prover_response['proof']['b'],
                c=prover_response['proof']['c']
            ),
            suiAddress=prover_response['suiAddress']
        )
        
    except Exception as e:
        logger.error(f"Error in finalize_zk_login: {str(e)}")
        return FinalizeZkLoginPayload(
            success=False,
            error=str(e)
        )

class Mutation(client.ClientMutation, server.ServerMutation, graphene.ObjectType):
    firebase_login = FirebaseLogin.Field()
    generate_zk_login_proof = GenerateZkLoginProof.Field()
    verify_zk_login_proof = VerifyZkLoginProof.Field()
    verify_token = VerifyToken.Field()
    zk_login = ZkLoginMutation.Field()
    initialize_zk_login = InitializeZkLogin.Field()
    initialize_apple_zk_login = InitializeAppleZkLogin.Field()
    finalize_zk_login = graphene.Field(
        FinalizeZkLoginPayload,
        input=FinalizeZkLoginInput(required=True),
        resolver=resolve_finalize_zk_login
    )

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