import graphene
from graphene_django import DjangoObjectType
from django.core.exceptions import ValidationError
from django.db import models, transaction
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
    idempotency_key = graphene.String(description="Optional idempotency key to prevent duplicate sends")

class SendTransactionType(DjangoObjectType):
    """GraphQL type for SendTransaction model"""
    class Meta:
        model = SendTransaction
        fields = (
            'id',
            'sender_user', 
            'recipient_user',
            'sender_business',
            'recipient_business',
            'sender_type',
            'recipient_type',
            'sender_display_name',
            'recipient_display_name',
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

        # Debug logging
        print(f"CreateSendTransaction: User {user.id} attempting send")
        print(f"CreateSendTransaction: Input received: {input}")
        print(f"CreateSendTransaction: Idempotency key: {getattr(input, 'idempotency_key', 'NOT PROVIDED')}")

        # Use atomic transaction with SELECT FOR UPDATE to prevent race conditions
        try:
            with transaction.atomic():
                # Check for existing transaction with same idempotency key
                if hasattr(input, 'idempotency_key') and input.idempotency_key:
                    print(f"CreateSendTransaction: Checking for existing transaction with idempotency key: {input.idempotency_key}")
                    existing_transaction = SendTransaction.objects.filter(
                        sender_user=user,
                        idempotency_key=input.idempotency_key
                    ).first()
                    
                    if existing_transaction:
                        print(f"CreateSendTransaction: Found existing transaction {existing_transaction.id}, returning it")
                        # Return existing transaction to prevent duplicate
                        return CreateSendTransaction(
                            send_transaction=existing_transaction,
                            success=True,
                            errors=None
                        )
                    else:
                        print(f"CreateSendTransaction: No existing transaction found, proceeding with creation")
                else:
                    print(f"CreateSendTransaction: No idempotency key provided")

                # Validate the transaction
                validate_transaction_amount(input.amount)
                validate_recipient(input.recipient_address)

                # Get the sender's active account with row-level locking
                active_account = user.accounts.select_for_update().filter(
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

                # Determine sender type and business details
                sender_business = None
                sender_type = 'user'  # default to personal
                sender_display_name = f"{user.first_name} {user.last_name}".strip() or user.username
                
                if active_account.account_type == 'business' and active_account.business:
                    sender_business = active_account.business
                    sender_type = 'business'
                    sender_display_name = active_account.business.name

                # Determine recipient type and business details
                recipient_business = None
                recipient_type = 'user'  # default to personal
                recipient_display_name = "External Address"
                
                if recipient_user:
                    recipient_display_name = f"{recipient_user.first_name} {recipient_user.last_name}".strip() or recipient_user.username
                    # Check if recipient has business account for this address
                    if recipient_account.account_type == 'business' and recipient_account.business:
                        recipient_business = recipient_account.business
                        recipient_type = 'business'
                        recipient_display_name = recipient_account.business.name

                # Use amount as provided by frontend (no automatic conversion)
                amount_str = str(input.amount)
                
                # Create the send transaction
                send_transaction = SendTransaction.objects.create(
                    # Legacy user fields (kept for compatibility)
                    sender_user=user,
                    recipient_user=recipient_user,
                    
                    # NEW: Business fields based on account type
                    sender_business=sender_business,
                    recipient_business=recipient_business,
                    sender_type=sender_type,
                    recipient_type=recipient_type,
                    sender_display_name=sender_display_name,
                    recipient_display_name=recipient_display_name,
                    
                    # Transaction details
                    sender_address=sender_address,
                    recipient_address=input.recipient_address,
                    amount=amount_str,
                    token_type=input.token_type,
                    memo=input.memo or '',
                    status='PENDING',
                    idempotency_key=input.idempotency_key
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