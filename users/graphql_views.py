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
    
    # Override nullable fields
    error_message = graphene.String(description="Error message if transaction failed")
    sender_phone = graphene.String(description="Sender phone number")
    counterparty_phone = graphene.String(description="Counterparty phone number")
    description = graphene.String(description="Transaction description")
    invoice_id = graphene.String(description="Invoice ID for payments")
    payment_transaction_id = graphene.String(description="Payment transaction ID")
    transaction_hash = graphene.String(description="Transaction hash on blockchain")
    
    # Add conversion-specific computed fields
    conversion_type = graphene.String(description="Conversion type (usdc_to_cusd or cusd_to_usdc)")
    from_amount = graphene.String(description="Amount being converted from")
    to_amount = graphene.String(description="Amount being converted to")
    from_token = graphene.String(description="Token being converted from")
    to_token = graphene.String(description="Token being converted to")
    
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
            'sender_user',
            'sender_business',
            'sender_type',
            'sender_display_name',
            'sender_address',
            'counterparty_user',
            'counterparty_business',
            'counterparty_type',
            'counterparty_display_name',
            'counterparty_address',
            'is_invitation',
            'invitation_claimed',
            'invitation_reverted',
            'invitation_expires_at',
        ]
    
    def resolve_direction(self, info):
        """Resolve transaction direction based on current user's address"""
        # Conversions are always "self" transactions
        if self.transaction_type == 'conversion':
            return 'conversion'
            
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
            # Handle conversions
            if self.transaction_type == 'conversion':
                return str(self.amount)
                
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
            # Handle conversions (no counterparty)
            if self.transaction_type == 'conversion':
                return 'Confío System'
                
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
            # Handle conversions with their description
            if self.transaction_type == 'conversion':
                return self.description or 'Conversión'
                
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
    
    def resolve_conversion_type(self, info):
        """Extract conversion type from description"""
        return self.get_conversion_type()
    
    def resolve_from_amount(self, info):
        """For conversions, this is the amount field"""
        return self.get_from_amount()
    
    def resolve_to_amount(self, info):
        """Extract to_amount from conversion description"""
        return self.get_to_amount()
    
    def resolve_from_token(self, info):
        """For conversions, determine from token"""
        return self.get_from_token()
    
    def resolve_to_token(self, info):
        """For conversions, determine to token"""
        return self.get_to_token()


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
        
        # Base query - all transactions involving this account
        if account.account_type == 'business' and account.business:
            # For business accounts, filter by business relationships
            queryset = UnifiedTransaction.objects.filter(
                Q(sender_business=account.business) | 
                Q(counterparty_business=account.business)
            )
        else:
            # For personal accounts, filter by user relationships
            queryset = UnifiedTransaction.objects.filter(
                Q(sender_user=user) | 
                Q(counterparty_user=user)
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