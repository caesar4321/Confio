import graphene
import asyncio
from graphene import ObjectType, String, Boolean, Field, Int, InputObjectType
from .aptos_keyless_service import keyless_service

# GraphQL Types
class EphemeralKeyPairType(ObjectType):
    private_key = String()
    public_key = String()
    expiry_date = String()
    nonce = String()
    blinder = String()

class EphemeralKeyPairInput(InputObjectType):
    private_key = String(required=True)
    public_key = String(required=True)
    expiry_date = String(required=True)
    nonce = String()
    blinder = String()

class KeylessAccountType(ObjectType):
    address = String()
    public_key = String()
    jwt = String()
    pepper = String()

class TransactionInput(InputObjectType):
    function = String(required=True)
    type_arguments = graphene.List(String)
    arguments = graphene.List(String)

# Mutations
class GenerateEphemeralKey(graphene.Mutation):
    class Arguments:
        expiry_hours = Int(default_value=24)
    
    ephemeral_key_pair = Field(EphemeralKeyPairType)
    success = Boolean()
    error = String()
    
    def mutate(self, info, expiry_hours=24):
        try:
            # Run async operation in sync context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            ephemeral_key = loop.run_until_complete(keyless_service.generate_ephemeral_key(expiry_hours))
            
            return GenerateEphemeralKey(
                ephemeral_key_pair=EphemeralKeyPairType(
                    private_key=ephemeral_key.get('privateKey'),
                    public_key=ephemeral_key.get('publicKey'),
                    expiry_date=ephemeral_key.get('expiryDate'),
                    nonce=ephemeral_key.get('nonce'),
                    blinder=ephemeral_key.get('blinder')
                ),
                success=True
            )
        except Exception as e:
            return GenerateEphemeralKey(
                success=False,
                error=str(e)
            )

class DeriveKeylessAccount(graphene.Mutation):
    class Arguments:
        jwt = String(required=True)
        ephemeral_key_pair = EphemeralKeyPairInput(required=True)
        pepper = String()  # Optional pepper for deterministic address generation
    
    keyless_account = Field(KeylessAccountType)
    success = Boolean()
    error = String()
    
    def mutate(self, info, jwt, ephemeral_key_pair, pepper=None):
        try:
            # Convert input to dict (handle both object and dict inputs)
            if isinstance(ephemeral_key_pair, dict):
                # Remove __typename if present
                ephemeral_key_pair = {k: v for k, v in ephemeral_key_pair.items() if k != '__typename'}
                ephemeral_dict = {
                    'privateKey': ephemeral_key_pair.get('privateKey'),
                    'publicKey': ephemeral_key_pair.get('publicKey'),
                    'expiryDate': ephemeral_key_pair.get('expiryDate'),
                    'nonce': ephemeral_key_pair.get('nonce'),
                    'blinder': ephemeral_key_pair.get('blinder')
                }
            else:
                ephemeral_dict = {
                    'privateKey': ephemeral_key_pair.private_key,
                    'publicKey': ephemeral_key_pair.public_key,
                    'expiryDate': ephemeral_key_pair.expiry_date,
                    'nonce': ephemeral_key_pair.nonce,
                    'blinder': ephemeral_key_pair.blinder
                }
            
            # Run async operation
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            account = loop.run_until_complete(keyless_service.derive_keyless_account(jwt, ephemeral_dict, pepper))
            
            return DeriveKeylessAccount(
                keyless_account=KeylessAccountType(
                    address=account.get('address'),
                    public_key=account.get('publicKey'),
                    jwt=jwt,
                    pepper=account.get('pepper')
                ),
                success=True
            )
        except Exception as e:
            return DeriveKeylessAccount(
                success=False,
                error=str(e)
            )

class SignAndSubmitTransaction(graphene.Mutation):
    class Arguments:
        jwt = String(required=True)
        ephemeral_key_pair = EphemeralKeyPairInput(required=True)
        transaction = TransactionInput(required=True)
        pepper = String()
    
    transaction_hash = String()
    success = Boolean()
    error = String()
    
    def mutate(self, info, jwt, ephemeral_key_pair, transaction, pepper=None):
        try:
            # Convert inputs to dicts
            ephemeral_dict = {
                'privateKey': ephemeral_key_pair.private_key,
                'publicKey': ephemeral_key_pair.public_key,
                'expiryDate': ephemeral_key_pair.expiry_date,
                'nonce': ephemeral_key_pair.nonce,
                'blinder': ephemeral_key_pair.blinder
            }
            
            transaction_dict = {
                'function': transaction.function,
                'typeArguments': transaction.type_arguments or [],
                'arguments': transaction.arguments or []
            }
            
            # Run async operation
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            tx_hash = loop.run_until_complete(
                keyless_service.sign_and_submit_transaction(
                    jwt, ephemeral_dict, transaction_dict, pepper
                )
            )
            
            return SignAndSubmitTransaction(
                transaction_hash=tx_hash,
                success=True
            )
        except Exception as e:
            return SignAndSubmitTransaction(
                success=False,
                error=str(e)
            )

# Query for balance
class KeylessBalanceType(ObjectType):
    apt = String()
    success = Boolean()
    error = String()

class KeylessQuery(ObjectType):
    keyless_balance = Field(
        KeylessBalanceType,
        address=String(required=True)
    )
    
    def resolve_keyless_balance(self, info, address):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            balance = loop.run_until_complete(keyless_service.get_balance(address))
            
            return KeylessBalanceType(
                apt=balance.get('apt', '0'),
                success=True
            )
        except Exception as e:
            return KeylessBalanceType(
                success=False,
                error=str(e)
            )

# Add mutations to your main Mutation class
class KeylessMutations(ObjectType):
    generate_ephemeral_key = GenerateEphemeralKey.Field()
    derive_keyless_account = DeriveKeylessAccount.Field()
    sign_and_submit_transaction = SignAndSubmitTransaction.Field()