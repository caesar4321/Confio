import graphene
from graphene_django import DjangoObjectType
from django.core.exceptions import ValidationError
from django.db import models
from .models import SendTransaction
from .validators import validate_transaction_amount, validate_recipient
from django.conf import settings
from django.utils import timezone
from django.contrib.auth import get_user_model
from users.models import Account

User = get_user_model()

class SendTransactionInput(graphene.InputObjectType):
    """Input type for creating a send transaction"""
    recipient_address = graphene.String(required=True, description="Sui address of the recipient")
    amount = graphene.String(required=True, description="Amount to send (e.g., '10.50')")
    token_type = graphene.String(required=True, description="Type of token to send (e.g., 'cUSD', 'CONFIO')")
    memo = graphene.String(description="Optional memo for the transaction")

class SendTransactionType(DjangoObjectType):
    """GraphQL type for SendTransaction model"""
    class Meta:
        model = SendTransaction
        fields = (
            'id',
            'sender_user', 
            'recipient_user',
            'sender_address',
            'recipient_address', 
            'amount', 
            'token_type', 
            'memo', 
            'status',
            'created_at', 
            'updated_at', 
            'transaction_hash'
        )

class CreateSendTransaction(graphene.Mutation):
    """Mutation for creating a new send transaction"""
    class Arguments:
        input = SendTransactionInput(required=True)

    send_transaction = graphene.Field(SendTransactionType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    def mutate(cls, root, info, input):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return CreateSendTransaction(
                send_transaction=None,
                success=False,
                errors=["Authentication required"]
            )

        try:
            # Validate the transaction
            validate_transaction_amount(input.amount)
            validate_recipient(input.recipient_address)

            # Get the sender's Sui address from their active account
            active_account = user.accounts.filter(
                account_type=info.context.active_account_type,
                account_index=info.context.active_account_index
            ).first()
            
            if not active_account or not active_account.sui_address:
                return CreateSendTransaction(
                    send_transaction=None,
                    success=False,
                    errors=["Sender's Sui address not found"]
                )
            
            sender_address = active_account.sui_address

            # Try to find recipient user by their Sui address
            try:
                recipient_account = Account.objects.get(sui_address=input.recipient_address)
                recipient_user = recipient_account.user
            except Account.DoesNotExist:
                recipient_user = None

            # Use amount as provided by frontend (no automatic conversion)
            amount_str = str(input.amount)
            
            # Create the send transaction
            send_transaction = SendTransaction.objects.create(
                sender_user=user,
                recipient_user=recipient_user,
                sender_address=sender_address,
                recipient_address=input.recipient_address,
                amount=amount_str,
                token_type=input.token_type,
                memo=input.memo,
                status='PENDING'
            )

            # TODO: Implement sponsored transaction logic here
            # This will be handled by a background task
            
            # TEMPORARY: Mark send transaction as CONFIRMED for testing
            # This ensures the UI shows the correct status
            send_transaction.status = 'CONFIRMED'
            # Generate a unique transaction hash using ID, microsecond timestamp, and UUID
            import time
            import uuid
            microsecond_timestamp = int(time.time() * 1000000)  # Microsecond precision
            unique_id = str(uuid.uuid4())[:8]  # First 8 characters of UUID
            send_transaction.transaction_hash = f"test_send_tx_{send_transaction.id}_{microsecond_timestamp}_{unique_id}"
            send_transaction.save()

            return CreateSendTransaction(
                send_transaction=send_transaction,
                success=True,
                errors=None
            )

        except ValidationError as e:
            return CreateSendTransaction(
                send_transaction=None,
                success=False,
                errors=[str(e)]
            )
        except Exception as e:
            return CreateSendTransaction(
                send_transaction=None,
                success=False,
                errors=[str(e)]
            )

class Query(graphene.ObjectType):
    """GraphQL queries for send transactions"""
    send_transactions = graphene.List(SendTransactionType)
    send_transaction = graphene.Field(SendTransactionType, id=graphene.ID(required=True))

    def resolve_send_transactions(self, info):
        """Resolve all send transactions for the authenticated user"""
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        
        return SendTransaction.objects.filter(
            models.Q(sender_user=user) | models.Q(recipient_user=user)
        ).order_by('-created_at')

    def resolve_send_transaction(self, info, id):
        """Resolve a specific send transaction by ID"""
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return None
        
        try:
            return SendTransaction.objects.get(
                models.Q(id=id) & (models.Q(sender_user=user) | models.Q(recipient_user=user))
            )
        except SendTransaction.DoesNotExist:
            return None

class Mutation(graphene.ObjectType):
    """GraphQL mutations for send transactions"""
    create_send_transaction = CreateSendTransaction.Field() 