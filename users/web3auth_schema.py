import graphene
from graphene_django import DjangoObjectType
from django.contrib.auth import get_user_model
from django.db import transaction
import json
import logging
from datetime import datetime
from .models import Account

logger = logging.getLogger(__name__)
User = get_user_model()


class Web3AuthUserType(DjangoObjectType):
    algorand_address = graphene.String()
    
    class Meta:
        model = User
        fields = ['id', 'email', 'username', 'first_name', 'last_name', 'is_phone_verified']
    
    def resolve_algorand_address(self, info):
        try:
            account = self.accounts.filter(account_type='personal').first()
            # Temporarily using aptos_address field to store Algorand address
            return account.aptos_address if account else None
        except:
            return None


# Removed Web3AuthLoginMutation - we don't need it
# Users authenticate with existing Firebase flow
# Then add Algorand wallet with AddAlgorandWalletMutation


class AddAlgorandWalletMutation(graphene.Mutation):
    """
    Add Algorand wallet to an existing Firebase-authenticated user.
    This is called after the user has already signed in with Firebase
    and Web3Auth has generated their Algorand wallet.
    """
    class Arguments:
        algorand_address = graphene.String(required=True)
        web3auth_id = graphene.String()
        provider = graphene.String()
    
    success = graphene.Boolean()
    error = graphene.String()
    user = graphene.Field(Web3AuthUserType)
    is_new_wallet = graphene.Boolean()
    
    @classmethod
    def mutate(cls, root, info, algorand_address, web3auth_id=None, provider=None):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Validate Algorand address format
            if not algorand_address or len(algorand_address) != 58:
                return cls(success=False, error='Invalid Algorand address')
            
            # Get or create the user's personal account
            account, created = Account.objects.get_or_create(
                user=user,
                account_type='personal',
                defaults={}
            )
            
            # Check if this is a new wallet
            # Temporarily using aptos_address field to store Algorand address
            is_new = not account.aptos_address
            
            # Update wallet address (using aptos_address field temporarily)
            account.aptos_address = algorand_address
            if web3auth_id:
                account.web3auth_id = web3auth_id
            if provider:
                account.web3auth_provider = provider
            account.save()
            
            logger.info(f'{"Added" if is_new else "Updated"} Algorand wallet for user {user.firebase_uid}: {algorand_address}')
            
            return cls(
                success=True, 
                user=user,
                is_new_wallet=is_new
            )
            
        except Exception as e:
            logger.error(f'Add Algorand wallet error: {str(e)}')
            return cls(success=False, error=str(e))


class UpdateAlgorandAddressMutation(graphene.Mutation):
    class Arguments:
        algorand_address = graphene.String(required=True)
    
    success = graphene.Boolean()
    error = graphene.String()
    user = graphene.Field(Web3AuthUserType)
    
    @classmethod
    def mutate(cls, root, info, algorand_address):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            # Validate Algorand address format
            if not algorand_address or len(algorand_address) != 58:
                return cls(success=False, error='Invalid Algorand address')
            
            # Update the user's personal account
            # Temporarily using aptos_address field to store Algorand address
            account = user.accounts.filter(account_type='personal').first()
            if account:
                account.aptos_address = algorand_address
                account.save()
            else:
                # Create account if it doesn't exist
                Account.objects.create(
                    user=user,
                    account_type='personal',
                    aptos_address=algorand_address
                )
            
            return cls(success=True, user=user)
            
        except Exception as e:
            logger.error(f'Update Algorand address error: {str(e)}')
            return cls(success=False, error=str(e))


class VerifyAlgorandOwnershipMutation(graphene.Mutation):
    class Arguments:
        message = graphene.String(required=True)
        signature = graphene.String(required=True)
    
    success = graphene.Boolean()
    error = graphene.String()
    verified = graphene.Boolean()
    
    @classmethod
    def mutate(cls, root, info, message, signature):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            account = user.accounts.filter(account_type='personal').first()
            # Temporarily using aptos_address field to store Algorand address
            if not account or not account.aptos_address:
                return cls(success=False, error='No Algorand address found')
            
            # TODO: Implement actual Algorand signature verification
            # For now, we'll just return success for testing
            # In production, you would verify the signature against the message
            # using the Algorand SDK
            
            verified = True  # Placeholder
            
            if verified:
                # Mark account as verified
                account.algorand_verified = True
                account.algorand_verified_at = datetime.now()
                account.save()
            
            return cls(success=True, verified=verified)
            
        except Exception as e:
            logger.error(f'Verify Algorand ownership error: {str(e)}')
            return cls(success=False, error=str(e))


class CreateAlgorandTransactionMutation(graphene.Mutation):
    class Arguments:
        to = graphene.String(required=True)
        amount = graphene.Float(required=True)
        note = graphene.String()
    
    success = graphene.Boolean()
    error = graphene.String()
    transaction_id = graphene.String()
    status = graphene.String()
    
    @classmethod
    def mutate(cls, root, info, to, amount, note=None):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return cls(success=False, error='Not authenticated')
            
            account = user.accounts.filter(account_type='personal').first()
            # Temporarily using aptos_address field to store Algorand address
            if not account or not account.aptos_address:
                return cls(success=False, error='No Algorand address found')
            
            # TODO: Implement actual Algorand transaction creation
            # This would typically:
            # 1. Create the transaction on Algorand
            # 2. Store transaction details in database
            # 3. Return transaction ID
            
            # Placeholder for testing
            transaction_id = f'algo_tx_{datetime.now().timestamp()}'
            
            return cls(
                success=True,
                transaction_id=transaction_id,
                status='pending'
            )
            
        except Exception as e:
            logger.error(f'Create Algorand transaction error: {str(e)}')
            return cls(success=False, error=str(e))


class Web3AuthMutation(graphene.ObjectType):
    add_algorand_wallet = AddAlgorandWalletMutation.Field()
    update_algorand_address = UpdateAlgorandAddressMutation.Field()
    verify_algorand_ownership = VerifyAlgorandOwnershipMutation.Field()
    create_algorand_transaction = CreateAlgorandTransactionMutation.Field()


class Web3AuthQuery(graphene.ObjectType):
    algorand_balance = graphene.Float(address=graphene.String())
    algorand_transactions = graphene.List(graphene.JSONString, limit=graphene.Int())
    
    def resolve_algorand_balance(self, info, address=None):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return 0.0
            
            if not address:
                account = user.accounts.filter(account_type='personal').first()
                # Temporarily using aptos_address field to store Algorand address
                address = account.aptos_address if account else None
            
            if not address:
                return 0.0
            
            # TODO: Implement actual Algorand balance fetching
            # This would query the Algorand blockchain for the balance
            
            return 0.0  # Placeholder
            
        except Exception as e:
            logger.error(f'Get Algorand balance error: {str(e)}')
            return 0.0
    
    def resolve_algorand_transactions(self, info, limit=10):
        try:
            user = info.context.user
            if not user.is_authenticated:
                return []
            
            account = user.accounts.filter(account_type='personal').first()
            if not account or not account.algorand_address:
                return []
            
            # TODO: Implement actual Algorand transaction history fetching
            # This would query the Algorand blockchain for transactions
            
            return []  # Placeholder
            
        except Exception as e:
            logger.error(f'Get Algorand transactions error: {str(e)}')
            return []