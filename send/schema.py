import graphene
from graphene_django import DjangoObjectType
from django.core.exceptions import ValidationError
from .models import Transaction
from .validators import validate_transaction_amount, validate_recipient
from django.conf import settings

class TransactionInput(graphene.InputObjectType):
    """Input type for creating a new transaction"""
    recipient_address = graphene.String(required=True, description="Sui address of the recipient")
    amount = graphene.String(required=True, description="Amount to send (in smallest unit, e.g., 1000000 for 1 cUSD)")
    token_type = graphene.String(required=True, description="Type of token to send (e.g., 'cUSD', 'CONFIO')")
    memo = graphene.String(description="Optional memo for the transaction")

class TransactionType(DjangoObjectType):
    """GraphQL type for Transaction model"""
    class Meta:
        model = Transaction
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

class CreateTransaction(graphene.Mutation):
    """Mutation for creating a new transaction"""
    class Arguments:
        input = TransactionInput(required=True)

    transaction = graphene.Field(TransactionType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    def mutate(cls, root, info, input):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return CreateTransaction(
                transaction=None,
                success=False,
                errors=["Authentication required"]
            )

        try:
            # Validate the transaction
            validate_transaction_amount(input.amount)
            validate_recipient(input.recipient_address)

            # Get the sender's Sui address from their profile
            sender_address = user.sui_address
            if not sender_address:
                return CreateTransaction(
                    transaction=None,
                    success=False,
                    errors=["Sender's Sui address not found"]
                )

            # Try to find recipient user by their Sui address
            try:
                recipient_user = settings.AUTH_USER_MODEL.objects.get(sui_address=input.recipient_address)
            except settings.AUTH_USER_MODEL.DoesNotExist:
                recipient_user = None

            # Create the transaction
            transaction = Transaction.objects.create(
                sender_user=user,
                recipient_user=recipient_user,
                sender_address=sender_address,
                recipient_address=input.recipient_address,
                amount=input.amount,
                token_type=input.token_type,
                memo=input.memo,
                status='PENDING'
            )

            # TODO: Implement sponsored transaction logic here
            # This will be handled by a background task

            return CreateTransaction(
                transaction=transaction,
                success=True,
                errors=None
            )

        except ValidationError as e:
            return CreateTransaction(
                transaction=None,
                success=False,
                errors=[str(e)]
            )
        except Exception as e:
            return CreateTransaction(
                transaction=None,
                success=False,
                errors=[str(e)]
            )

class Query(graphene.ObjectType):
    """Query definitions for transactions"""
    transaction = graphene.Field(TransactionType, id=graphene.ID())
    transactions = graphene.List(TransactionType)

    def resolve_transaction(self, info, id):
        # Ensure users can only view their own transactions
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return None
        return Transaction.objects.get(
            id=id,
            sender_user=user
        )

    def resolve_transactions(self, info):
        # Users can only view their own transactions
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        return Transaction.objects.filter(
            sender_user=user
        )

class Mutation(graphene.ObjectType):
    """Mutation definitions for transactions"""
    create_transaction = CreateTransaction.Field() 