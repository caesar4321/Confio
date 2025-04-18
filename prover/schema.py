import graphene
from graphene_django import DjangoObjectType
from .models import ZkLoginProof
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

logger = logging.getLogger(__name__)

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

class ZkLoginProofType(DjangoObjectType):
    class Meta:
        model = ZkLoginProof
        fields = '__all__'

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

class ZkLoginDataType(graphene.ObjectType):
    zkProof = graphene.String()
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
                user_salt = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
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
                randomness = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
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
                    zkProof=prover_data['proof'],
                    suiAddress=prover_data['suiAddress'],
                    ephemeralPublicKey=ephemeral_public_key,
                    maxEpoch=str(current_epoch + 2),  # Convert to string here
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
            prover_url = "http://localhost:3002/v1"  # Updated to use port 3002
            payload = {
                "jwt": input.jwt,
                "maxEpoch": str(input.max_epoch),  # Convert to string
                "jwtRandomness": input.randomness,
                "keyClaimName": input.key_claim_name,
                "extendedEphemeralPublicKey": input.extended_ephemeral_public_key,
                "salt": input.salt,
                "audience": input.audience
            }

            response = requests.post(prover_url, json=payload)
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

class Mutation(client.ClientMutation, server.ServerMutation, graphene.ObjectType):
    generate_zk_login_proof = GenerateZkLoginProof.Field()
    verify_zk_login_proof = VerifyZkLoginProof.Field()
    verify_token = VerifyToken.Field()
    zk_login = ZkLoginMutation.Field()

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