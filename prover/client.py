import graphene
from django.conf import settings
import requests
import nacl.signing
import base64
import logging
import secrets

logger = logging.getLogger(__name__)

class ZkLoginDataType(graphene.ObjectType):
    zkProof = graphene.JSONString()
    suiAddress = graphene.String()
    ephemeralPublicKey = graphene.String()
    maxEpoch = graphene.Int()
    randomness = graphene.String()
    salt = graphene.String()

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
            # Call zkLogin Prover service
            prover_url = "http://localhost:3001/generate-proof"  # Update this to your prover service URL
            payload = {
                "jwt": str(input.jwt),
                "maxEpoch": int(input.max_epoch),
                "randomness": str(input.randomness),
                "keyClaimName": str(input.key_claim_name),
                "extendedEphemeralPublicKey": str(input.extended_ephemeral_public_key),
                "salt": str(input.salt),
                "audience": str(input.audience)
            }

            response = requests.post(prover_url, json=payload)
            response.raise_for_status()
            zk_proof = response.json()

            # The prover service should return the Sui address
            sui_address = zk_proof.get('suiAddress')

            return ZkLoginResult(
                zk_proof=zk_proof,
                sui_address=sui_address
            )

        except Exception as e:
            logger.error(f"zkLogin error: {str(e)}")
            return ZkLoginResult(
                error="zkLogin error",
                details=str(e)
            )

class ClientMutation(graphene.ObjectType):
    zk_login = ZkLoginMutation.Field() 