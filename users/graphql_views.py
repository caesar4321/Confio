import graphene
from graphene_django import DjangoObjectType
from .models_views import UnifiedTransaction
from django.db.models import Q


class UnifiedTransactionType(DjangoObjectType):
    """GraphQL type for unified transaction view"""
    
    # Computed fields for the current user's perspective
    direction = graphene.String(description="Transaction direction from current user perspective")
    display_amount = graphene.String(description="Formatted amount with +/- based on direction")
    display_counterparty = graphene.String(description="Name of the counterparty from user perspective")
    display_description = graphene.String(description="Transaction description")
    
    class Meta:
        model = UnifiedTransaction
        fields = [
            'id',
            'transaction_type',
            'created_at',
            'updated_at',
            'amount',
            'token_type',
            'status',
            'transaction_hash',
            'error_message',
            'sender_user',
            'sender_business',
            'sender_type',
            'sender_display_name',
            'sender_phone',
            'sender_address',
            'counterparty_user',
            'counterparty_business',
            'counterparty_type',
            'counterparty_display_name',
            'counterparty_phone',
            'counterparty_address',
            'description',
            'invoice_id',
            'payment_transaction_id',
        ]
    
    def resolve_direction(self, info):
        """Resolve transaction direction based on current user's address"""
        # Get the user's address from the transaction context
        user_address = getattr(self, '_user_address', None)
        
        if user_address and hasattr(self, 'get_direction_for_address'):
            try:
                return self.get_direction_for_address(user_address)
            except Exception as e:
                print(f"Error in resolve_direction: {e}")
                return 'unknown'
        return 'unknown'
    
    def resolve_display_amount(self, info):
        """Resolve formatted amount based on direction"""
        try:
            # Get direction directly
            user_address = getattr(self, '_user_address', None)
            if user_address and hasattr(self, 'get_direction_for_address'):
                direction = self.get_direction_for_address(user_address)
                if direction == 'sent':
                    return f'-{self.amount}'
                elif direction == 'received':
                    return f'+{self.amount}'
        except Exception as e:
            print(f"Error in resolve_display_amount: {e}")
        return str(self.amount)
    
    def resolve_display_counterparty(self, info):
        """Resolve counterparty name based on direction"""
        try:
            # Get direction directly
            user_address = getattr(self, '_user_address', None)
            if user_address and hasattr(self, 'get_direction_for_address'):
                direction = self.get_direction_for_address(user_address)
                if direction == 'sent':
                    return self.counterparty_display_name or 'Unknown'
                elif direction == 'received':
                    return self.sender_display_name or 'Unknown'
        except Exception as e:
            print(f"Error in resolve_display_counterparty: {e}")
        return 'Unknown'
    
    def resolve_display_description(self, info):
        """Resolve description with proper context"""
        try:
            if self.transaction_type == 'payment':
                # Get direction directly
                user_address = getattr(self, '_user_address', None)
                if user_address and hasattr(self, 'get_direction_for_address'):
                    direction = self.get_direction_for_address(user_address)
                    if direction == 'sent':
                        return f"Pago a {self.counterparty_display_name or 'Unknown'}"
                    elif direction == 'received':
                        return f"Pago recibido de {self.sender_display_name or 'Unknown'}"
        except Exception as e:
            print(f"Error in resolve_display_description: {e}")
        return self.description or ''


class UnifiedTransactionQuery(graphene.ObjectType):
    """GraphQL queries for unified transactions"""
    
    unified_transactions = graphene.List(
        UnifiedTransactionType,
        account_type=graphene.String(required=True),
        account_index=graphene.Int(required=True),
        limit=graphene.Int(default_value=50),
        offset=graphene.Int(default_value=0),
        token_types=graphene.List(graphene.String),
        description="Get unified transactions for a specific account"
    )
    
    def resolve_unified_transactions(self, info, account_type, account_index, 
                                   limit=50, offset=0, token_types=None):
        """Resolve unified transactions for the current user's account"""
        user = info.context.user
        if not user.is_authenticated:
            return []
        
        # Get the account
        from users.models import Account
        try:
            account = Account.objects.get(
                user=user,
                account_type=account_type,
                account_index=account_index
            )
        except Account.DoesNotExist:
            return []
        
        # Base query - all transactions involving this address
        queryset = UnifiedTransaction.objects.filter(
            Q(sender_address=account.sui_address) | 
            Q(counterparty_address=account.sui_address)
        )
        
        # Filter by token types if provided
        if token_types:
            queryset = queryset.filter(token_type__in=token_types)
        
        # Apply pagination and add user address to each transaction for direction calculation
        transactions = list(queryset[offset:offset + limit])
        
        # Set the user's address on each transaction for the resolvers
        for transaction in transactions:
            transaction._user_address = account.sui_address
            
        return transactions