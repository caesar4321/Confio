import graphene
from django.conf import settings
import requests
import logging

logger = logging.getLogger(__name__)

class ProverProofType(graphene.ObjectType):
    proof_points = graphene.JSONString()
    iss_base64_details = graphene.JSONString()
    header_base64 = graphene.String()
    address_seed = graphene.String()

class ProverResultType(graphene.ObjectType):
    sui_address = graphene.String()
    proof = graphene.Field(ProverProofType)
    error = graphene.String()
    details = graphene.String()

class ProverMutation(graphene.Mutation):
    class Arguments:
        jwt = graphene.String(required=True)
        max_epoch = graphene.Int(required=True)
        randomness = graphene.String(required=True)
        key_claim_name = graphene.String(required=True)
        extended_ephemeral_public_key = graphene.String(required=True)
        salt = graphene.String(required=True)
        audience = graphene.String(required=True)

    Output = ProverResultType

    def mutate(self, info, **kwargs):
        try:
            # Call the JS prover server
            prover_url = "http://localhost:8001/v1"
            payload = {
                "jwt": str(kwargs["jwt"]),
                "maxEpoch": int(kwargs["max_epoch"]),
                "randomness": str(kwargs["randomness"]),
                "keyClaimName": str(kwargs["key_claim_name"]),
                "extendedEphemeralPublicKey": str(kwargs["extended_ephemeral_public_key"]),
                "salt": str(kwargs["salt"]),
                "audience": str(kwargs["audience"])
            }

            response = requests.post(prover_url, json=payload)
            response.raise_for_status()
            result = response.json()

            return ProverResultType(
                sui_address=result.get("suiAddress"),
                proof=ProverProofType(
                    proof_points=result.get("proof", {}).get("proofPoints"),
                    iss_base64_details=result.get("proof", {}).get("issBase64Details"),
                    header_base64=result.get("proof", {}).get("headerBase64"),
                    address_seed=result.get("proof", {}).get("addressSeed")
                )
            )

        except Exception as e:
            logger.error(f"Prover error: {str(e)}")
            return ProverResultType(
                error="Prover error",
                details=str(e)
            )

class ServerMutation(graphene.ObjectType):
    generate_proof = ProverMutation.Field() 