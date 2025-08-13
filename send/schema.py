import graphene
from graphene_django import DjangoObjectType
from send.models import SendTransaction
from django.contrib.auth import get_user_model
from graphql_jwt.decorators import login_required
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from decimal import Decimal
from typing import List, Optional

User = get_user_model()

class SendTransactionType(DjangoObjectType):
    """GraphQL type for SendTransaction model"""
    class Meta:
        model = SendTransaction
        fields = (
            'id',
            'sender_user',
            'recipient_user',
            'amount',
            'token_type',
            'sender_address',
            'recipient_address',
            'memo',
            'status',
            'transaction_hash',
            'error_message',
            'created_at',
            'updated_at',
            'sender_business',
            'recipient_business',
            'sender_type',
            'recipient_type',
            'sender_display_name',
            'recipient_display_name',
            'sender_phone',
            'recipient_phone',
            'idempotency_key',
            'is_invitation',
            'invitation_claimed',
            'invitation_reverted',
            'invitation_expires_at'
        )

class Query(graphene.ObjectType):
    """GraphQL queries for send transactions"""
    send_transactions = graphene.List(SendTransactionType)
    send_transaction = graphene.Field(SendTransactionType, id=graphene.ID(required=True))
    send_transactions_with_friend = graphene.List(
        SendTransactionType,
        friend_user_id=graphene.ID(required=False),
        friend_phone=graphene.String(required=False),
        limit=graphene.Int()
    )

    @login_required
    def resolve_send_transactions(self, info, **kwargs):
        """Get all send transactions for the current user"""
        from users.jwt_context import get_jwt_business_context_with_validation
        
        user = info.context.user
        jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_context:
            return []
        
        # Get the account
        try:
            from users.models import Account
            
            account_type = jwt_context['account_type']
            account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')
            
            # Determine the account based on JWT context
            if account_type == 'business' and business_id:
                from users.models import Business
                business = Business.objects.get(id=business_id)
                account = Account.objects.get(
                    business=business,
                    account_type='business'
                )
            else:
                account = Account.objects.get(
                    user=user,
                    account_type=account_type,
                    account_index=account_index,
                    deleted_at__isnull=True
                )
                
            # Return transactions for this account (both as sender and recipient)
            return SendTransaction.objects.filter(
                Q(sender_account=account) | Q(recipient_account=account)
            ).order_by('-created_at')
        except Account.DoesNotExist:
            pass
            
        # Fallback to user-based lookup for backwards compatibility
        return SendTransaction.objects.filter(
            Q(sender_user=user) | Q(recipient_user=user)
        ).order_by('-created_at')

    @login_required
    def resolve_send_transaction(self, info, id):
        """Get a specific send transaction by ID"""
        user = info.context.user
        
        try:
            return SendTransaction.objects.get(
                id=id,
                sender_user=user
            )
        except SendTransaction.DoesNotExist:
            return None

    @login_required
    def resolve_send_transactions_with_friend(self, info, friend_user_id=None, friend_phone=None, limit=None):
        """Get send transactions with a specific friend"""
        user = info.context.user
        from users.jwt_context import get_jwt_business_context_with_validation
        
        jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_context:
            return []
        
        # Get the user's active account
        try:
            from users.models import Account
            
            account_type = jwt_context['account_type']
            account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')
            
            if account_type == 'business' and business_id:
                from users.models import Business
                business = Business.objects.get(id=business_id)
                account = Account.objects.get(
                    business=business,
                    account_type='business'
                )
            else:
                account = Account.objects.get(
                    user=user,
                    account_type=account_type,
                    account_index=account_index,
                    deleted_at__isnull=True
                )
                
        except Account.DoesNotExist:
            return []
        
        # Build query for transactions with friend
        if friend_user_id:
            # Find transactions with specific user
            try:
                friend = User.objects.get(id=friend_user_id)
                friend_accounts = friend.accounts.all()
                
                transactions = SendTransaction.objects.filter(
                    Q(sender_account=account, recipient_account__in=friend_accounts) |
                    Q(sender_account__in=friend_accounts, recipient_account=account)
                ).order_by('-created_at')
                
            except User.DoesNotExist:
                return []
                
        elif friend_phone:
            # Find transactions with phone number
            transactions = SendTransaction.objects.filter(
                Q(sender_account=account, recipient_phone=friend_phone) |
                Q(sender_phone=friend_phone, recipient_account=account)
            ).order_by('-created_at')
        else:
            return []
        
        # Apply limit if provided
        if limit:
            transactions = transactions[:limit]
            
        return transactions


class Mutation(graphene.ObjectType):
    """GraphQL mutations for send transactions"""
    # Note: Send transactions are now handled by Algorand mutations in blockchain/mutations.py
    # The old CreateSendTransaction, PrepareTransaction, and ExecuteTransaction mutations
    # have been removed as they are no longer used.
    pass