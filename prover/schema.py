import graphene
from graphene_django import DjangoObjectType
from graphene_django.converter import convert_django_field
from django.db import models
from .models import ZkLoginProof
from users.models import UserProfile, User
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
import graphql_jwt
from graphql_jwt.middleware import JSONWebTokenMiddleware
import jwt
from datetime import datetime, timedelta
from telegram_verification.schema import validate_country_code, get_country_code
from telegram_verification.models import TelegramVerification

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
    authAccessToken = graphene.String()
    authRefreshToken = graphene.String()

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

            # Validate firebase_uid
            if not firebase_uid:
                logger.error("firebase_uid is blank or None! Cannot create or fetch user.")
                return InitializeZkLogin(success=False, error="firebase_uid is missing from Firebase token.")
            logger.info(f"Proceeding to get_or_create user with firebase_uid: {firebase_uid}")

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
            
            # Generate a unique random UUID for username
            max_attempts = 5
            for attempt in range(max_attempts):
                random_username = f"user_{uuid.uuid4().hex[:8]}"  # Shorter, more readable username
                if not User.objects.filter(username=random_username).exists():
                    break
            else:
                logger.error("Failed to generate a unique username after multiple attempts.")
                return InitializeZkLogin(success=False, error="Could not generate a unique username. Please try again.")

            with transaction.atomic():
                # First, try to get the user by firebase_uid
                try:
                    user = User.objects.get(firebase_uid=firebase_uid)
                    logger.info(f"Found existing user: id={user.id}, username={user.username}, auth_token_version={user.auth_token_version}")
                except User.DoesNotExist:
                    # If user doesn't exist, create a new one
                    user = User.objects.create(
                        username=random_username,
                        email=email,
                        first_name=first_name,
                        last_name=last_name,
                        firebase_uid=firebase_uid,
                        is_active=True
                    )
                    logger.info(f"Created new user: id={user.id}, username={user.username}")

                # Generate tokens using JWT directly
                access_token_payload = {
                    'user_id': user.id,
                    'exp': datetime.utcnow() + timedelta(hours=1),  # 1 hour expiration
                    'origIat': datetime.utcnow().timestamp(),
                    'type': 'access',
                    'auth_token_version': user.auth_token_version
                }
                token = jwt.encode(
                    access_token_payload,
                    settings.SECRET_KEY,
                    algorithm='HS256'
                )
                logger.info(f"Generated access token with expiration: {access_token_payload['exp']}")

                # Create refresh token
                refresh_token_payload = {
                    'user_id': user.id,
                    'exp': datetime.utcnow() + timedelta(days=365),  # One year expiration
                    'origIat': datetime.utcnow().timestamp(),
                    'type': 'refresh',
                    'auth_token_version': user.auth_token_version
                }
                refresh_token = jwt.encode(
                    refresh_token_payload,
                    settings.SECRET_KEY,
                    algorithm='HS256'
                )
                logger.info(f"Generated refresh token with expiration: {refresh_token_payload['exp']}")

                # Get current epoch
                current_epoch = get_current_epoch()
                max_epoch = str(current_epoch + 100)  # Set max epoch to 100 epochs from now

                # Generate randomness (32 bytes)
                randomness_bytes = secrets.token_bytes(32)  # Generate 32 random bytes
                randomness = base64.b64encode(randomness_bytes).decode('utf-8')  # Convert to base64 string

            return InitializeZkLogin(
                success=True,
                    maxEpoch=max_epoch,
                    randomness=randomness,
                    authAccessToken=token,
                    authRefreshToken=refresh_token
            )

        except Exception as e:
            logger.error(f"Error in InitializeZkLogin: {str(e)}")
            logger.error(traceback.format_exc())
            return InitializeZkLogin(success=False, error=str(e))

class FinalizeZkLoginInput(graphene.InputObjectType):
    maxEpoch = graphene.String(required=True)
    randomness = graphene.String(required=True)
    extendedEphemeralPublicKey = graphene.String(required=True)
    userSignature = graphene.String(required=True)
    jwt = graphene.String(required=True)
    keyClaimName = graphene.String(required=True)
    audience = graphene.String(required=True)
    firebaseToken = graphene.String(required=True)
    salt = graphene.String(required=True)

class FinalizeZkLoginPayload(graphene.ObjectType):
    success = graphene.Boolean()
    zkProof = graphene.Field(ProofPointsType)
    suiAddress = graphene.String()
    error = graphene.String()
    isPhoneVerified = graphene.Boolean()

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
        
        # Find user profile by Firebase UID
        try:
            # Get the Firebase UID from the Firebase token
            decoded_token = auth.verify_id_token(input.firebaseToken)
            firebase_uid = decoded_token.get('uid')
            
            # Find the user profile by firebase_uid field
            profile = UserProfile.objects.get(user__firebase_uid=firebase_uid)
            logger.info("Found user profile for Firebase UID: %s", firebase_uid)
        except UserProfile.DoesNotExist:
            logger.error("User profile not found for Firebase UID: %s", firebase_uid)
            return FinalizeZkLoginPayload(
                success=False,
                error="User profile not found"
            )

        # Prepare prover payload
        prover_payload = {
            "jwt": input.jwt,
            "extendedEphemeralPublicKey": input.extendedEphemeralPublicKey,
            "maxEpoch": input.maxEpoch,
            "randomness": input.randomness,
            "userSignature": input.userSignature,
            "keyClaimName": input.keyClaimName,
            "audience": input.audience,
            "salt": input.salt
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

            # Verify the Sui address was saved
            profile.refresh_from_db()
            if not profile.sui_address:
                logger.error("Failed to save Sui address to profile")
                return FinalizeZkLoginPayload(
                    success=False,
                    error="Failed to save Sui address"
                )

            # Calculate is_phone_verified based on phone_number and phone_country
            is_phone_verified = bool(profile.user.phone_number and profile.user.phone_country)
            logger.info(f"Phone verification status: {is_phone_verified} (phone_number: {bool(profile.user.phone_number)}, phone_country: {bool(profile.user.phone_country)})")

            return FinalizeZkLoginPayload(
                success=True,
                zkProof=result['proof'],
                suiAddress=result['suiAddress'],
                isPhoneVerified=is_phone_verified
            )

        except Exception as e:
            logger.error(f"Error in finalize_zk_login: {str(e)}")
            logger.error(traceback.format_exc())
            return FinalizeZkLoginPayload(
                success=False,
                error=str(e)
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

class InitiateTelegramVerification(graphene.Mutation):
    class Arguments:
        phoneNumber = graphene.String(required=True)
        countryCode = graphene.String(required=True)

    class Meta:
        description = "Initiate Telegram verification process"

    success = graphene.Boolean()
    error = graphene.String()

    @staticmethod
    def mutate(root, info, phoneNumber, countryCode):
        try:
            # Check if user is authenticated
            if not info.context.user.is_authenticated:
                logger.error("User not authenticated")
                return InitiateTelegramVerification(
                    success=False,
                    error="Authentication required"
                )

            # Log user details from context
            user = info.context.user
            logger.info(f"User from context - ID: {user.id}, Username: {user.username}, Is authenticated: {user.is_authenticated}")

            # Validate country code
            if not validate_country_code(countryCode):
                logger.error(f"Invalid country code: {countryCode}")
                return InitiateTelegramVerification(
                    success=False,
                    error="Invalid country code"
                )

            # Get numeric country code
            numeric_code = get_country_code(countryCode)
            if not numeric_code:
                logger.error(f"Could not find numeric code for ISO: {countryCode}")
                return InitiateTelegramVerification(
                    success=False,
                    error="Invalid country code"
                )

            # Format phone number to E.164
            formatted_phone = f"+{numeric_code}{phoneNumber}"
            logger.info(f"Formatted phone number: {formatted_phone}")

            # Check if user exists in database
            try:
                db_user = User.objects.get(id=user.id)
                logger.info(f"Found user in database - ID: {db_user.id}, Username: {db_user.username}")
                user = db_user  # Use the database user
            except User.DoesNotExist:
                logger.error(f"User not found in database: id={user.id}")
                return InitiateTelegramVerification(
                    success=False,
                    error="User not found. Please log in again."
                )

            # Get Telegram API token from settings
            TELEGRAM_GATEWAY_TOKEN = settings.TELEGRAM_API_TOKEN
            logger.info(f"Telegram API Token available: {bool(TELEGRAM_GATEWAY_TOKEN)}")
            ttl = 600  # 10 minutes

            logger.info(f"Initiating Telegram verification for phone number: {formatted_phone}")
            logger.info(f"Using Telegram Gateway Token: {TELEGRAM_GATEWAY_TOKEN[:10] if TELEGRAM_GATEWAY_TOKEN else 'None'}...")

            try:
                request_url = 'https://gatewayapi.telegram.org/sendVerificationMessage'
                request_headers = {'Authorization': f'Bearer {TELEGRAM_GATEWAY_TOKEN}'}
                request_data = {
                    'phone_number': formatted_phone,
                    'ttl': ttl,
                    'code_length': 6  # Set code length to 6 digits
                }

                logger.info('Sending request to Telegram API:')
                logger.info(f'URL: {request_url}')
                logger.info(f'Headers: {request_headers}')
                logger.info(f'Data: {request_data}')

                response = requests.post(
                    request_url,
                    headers=request_headers,
                    json=request_data
                )

                logger.info(f'Telegram API Response Status Code: {response.status_code}')
                logger.info(f'Telegram API Response Headers: {dict(response.headers)}')
                logger.info(f'Telegram API Response Body: {response.text}')

                data = response.json()
                if not data.get('ok'):
                    error_msg = data.get('error', 'Unknown error')
                    logger.error(f'Telegram API error: {error_msg}')
                    return InitiateTelegramVerification(success=False, error=error_msg)

                request_id = data['result']['request_id']
                expires_at = timezone.now() + timedelta(seconds=ttl)

                logger.info('Creating TelegramVerification record:')
                logger.info(f'Request ID: {request_id}')
                logger.info(f'Expires at: {expires_at}')

                TelegramVerification.objects.create(
                    user=user,
                    phone_number=formatted_phone,
                    request_id=request_id,
                    expires_at=expires_at
                )

                logger.info('Telegram verification initiated successfully')
                return InitiateTelegramVerification(success=True, error=None)

            except Exception as e:
                logger.exception(f'Failed to send verification: {str(e)}')
                return InitiateTelegramVerification(
                    success=False,
                    error=f"Failed to send verification: {str(e)}"
                )

        except Exception as e:
            logger.error(f"Error in initiate_telegram_verification: {str(e)}")
            return InitiateTelegramVerification(
                success=False,
                error=str(e)
            )

class Mutation(graphene.ObjectType):
    initialize_zk_login = InitializeZkLogin.Field()
    finalize_zk_login = FinalizeZkLogin.Field()
    token_auth = graphql_jwt.ObtainJSONWebToken.Field()
    verify_token = graphql_jwt.Verify.Field()
    refresh_token = graphql_jwt.Refresh.Field()
    initiate_telegram_verification = InitiateTelegramVerification.Field()

class Query(graphene.ObjectType):
    zk_login_proof = graphene.Field(ZkLoginProofType, id=graphene.ID())
    zk_login_proofs = graphene.List(ZkLoginProofType)
    ping = graphene.String()
    currentEpoch = graphene.Int()

    def resolve_zk_login_proof(self, info, id):
        return ZkLoginProof.objects.get(id=id)

    def resolve_zk_login_proofs(self, info):
        return ZkLoginProof.objects.all()

    def resolve_ping(self, info):
        return "pong"
        
    def resolve_currentEpoch(self, info):
        try:
            return get_current_epoch()
        except Exception as e:
            logger.error(f"Error getting current epoch: {str(e)}")
            raise Exception("Failed to get current epoch")

# Create the schema
schema = graphene.Schema(
    query=Query,
    mutation=Mutation,
    types=[UserProfileType, ZkLoginProofType]
)

# Add JWT middleware
schema.middleware = [JSONWebTokenMiddleware()] 