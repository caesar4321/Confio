import graphene
from graphene_django import DjangoObjectType
from graphql_jwt.decorators import login_required
from firebase_admin import auth
import tempfile
import subprocess
import json
from .models import ZkLoginProof

class ZkLoginProofType(DjangoObjectType):
    class Meta:
        model = ZkLoginProof
        fields = ('id', 'user', 'max_epoch', 'firebase_uid', 'firebase_project_id', 
                 'created_at', 'verified_at', 'is_verified')

class GenerateProofInput(graphene.InputObjectType):
    jwt = graphene.String(required=True)
    max_epoch = graphene.Int(required=True)
    randomness = graphene.String(required=True)
    salt = graphene.String(required=True)

class GenerateProofMutation(graphene.Mutation):
    class Arguments:
        input = GenerateProofInput(required=True)

    proof = graphene.Field(ZkLoginProofType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @login_required
    def mutate(self, info, input):
        try:
            # Verify Firebase ID token
            decoded_token = auth.verify_id_token(input.jwt)
            
            # Extract required fields
            firebase_uid = decoded_token['sub']
            firebase_project_id = decoded_token['aud']
            
            # Generate zkLogin proof
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt') as jwt_file:
                jwt_file.write(input.jwt)
                jwt_file.flush()
                
                # Prepare zkLogin command
                cmd = [
                    'zklogin', 'generate-proof',
                    '--jwt-path', jwt_file.name,
                    '--max-epoch', str(input.max_epoch),
                    '--audience', firebase_project_id,
                    '--issuer', 'https://accounts.google.com',
                    '--key', input.randomness
                ]
                
                # Execute zkLogin command
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode != 0:
                    return GenerateProofMutation(
                        success=False,
                        errors=[f"zkLogin proof generation failed: {result.stderr}"]
                    )
                
                # Parse proof data
                proof_data = json.loads(result.stdout)
                
                # Create the proof
                proof = ZkLoginProof.objects.create(
                    user=info.context.user,
                    jwt=input.jwt,
                    max_epoch=input.max_epoch,
                    randomness=input.randomness,
                    salt=input.salt,
                    firebase_uid=firebase_uid,
                    firebase_project_id=firebase_project_id,
                    proof_data=proof_data
                )
                
                return GenerateProofMutation(proof=proof, success=True)
                
        except auth.InvalidIdTokenError as e:
            return GenerateProofMutation(
                success=False,
                errors=["Invalid Firebase ID token"]
            )
        except Exception as e:
            return GenerateProofMutation(
                success=False,
                errors=[str(e)]
            )

class VerifyProofMutation(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @login_required
    def mutate(self, info, id):
        try:
            proof = ZkLoginProof.objects.get(
                id=id,
                user=info.context.user
            )
            
            if proof.is_verified:
                return VerifyProofMutation(
                    success=False,
                    errors=["Proof already verified"]
                )
            
            # Verify the proof using zkLogin
            cmd = [
                'zklogin', 'verify-proof',
                '--proof', json.dumps(proof.proof_data),
                '--jwt', proof.jwt
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                return VerifyProofMutation(
                    success=False,
                    errors=[f"Proof verification failed: {result.stderr}"]
                )
            
            # Mark proof as verified
            proof.is_verified = True
            proof.save()
            
            return VerifyProofMutation(success=True)
            
        except ZkLoginProof.DoesNotExist:
            return VerifyProofMutation(
                success=False,
                errors=["Proof not found"]
            )
        except Exception as e:
            return VerifyProofMutation(
                success=False,
                errors=[str(e)]
            )

class Query(graphene.ObjectType):
    zk_login_proofs = graphene.List(ZkLoginProofType)
    zk_login_proof = graphene.Field(
        ZkLoginProofType,
        id=graphene.ID(required=True)
    )

    @login_required
    def resolve_zk_login_proofs(self, info):
        return ZkLoginProof.objects.filter(user=info.context.user)

    @login_required
    def resolve_zk_login_proof(self, info, id):
        return ZkLoginProof.objects.get(id=id, user=info.context.user)

class Mutation(graphene.ObjectType):
    generate_proof = GenerateProofMutation.Field()
    verify_proof = VerifyProofMutation.Field() 