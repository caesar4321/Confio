import graphene
from graphene_django import DjangoObjectType
from .models_unified import UnifiedTransactionTable
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
    
    # P2P Trade ID for navigation
    p2p_trade_id = graphene.String(description="P2P Trade ID if this is an exchange transaction")
    
    class Meta:
        model = UnifiedTransactionTable
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
        
        # P2P exchanges need special handling as they don't have blockchain addresses
        if self.transaction_type == 'exchange':
            user = info.context.user if info.context else None
            if user and user.is_authenticated:
                # Check if user is sender (seller in the trade)
                if (self.sender_user and self.sender_user.id == user.id) or \
                   (self.sender_business and user.accounts.filter(business_id=self.sender_business.id).exists()):
                    return 'sent'
                # Check if user is counterparty (buyer in the trade)
                elif (self.counterparty_user and self.counterparty_user.id == user.id) or \
                     (self.counterparty_business and user.accounts.filter(business_id=self.counterparty_business.id).exists()):
                    return 'received'
            return 'unknown'
            
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
            
            # Handle P2P exchanges
            if self.transaction_type == 'exchange':
                user = info.context.user if info.context else None
                if user and user.is_authenticated:
                    # Check if user is sender (seller in the trade)
                    if (self.sender_user and self.sender_user.id == user.id) or \
                       (self.sender_business and user.accounts.filter(business_id=self.sender_business.id).exists()):
                        return f'-{self.amount}'
                    # Check if user is counterparty (buyer in the trade)
                    elif (self.counterparty_user and self.counterparty_user.id == user.id) or \
                         (self.counterparty_business and user.accounts.filter(business_id=self.counterparty_business.id).exists()):
                        return f'+{self.amount}'
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
            
            # Handle P2P exchanges
            if self.transaction_type == 'exchange':
                user = info.context.user if info.context else None
                if user and user.is_authenticated:
                    # Check if user is sender (seller in the trade)
                    if (self.sender_user and self.sender_user.id == user.id) or \
                       (self.sender_business and user.accounts.filter(business_id=self.sender_business.id).exists()):
                        return self.counterparty_display_name or 'Unknown'
                    # Check if user is counterparty (buyer in the trade)
                    elif (self.counterparty_user and self.counterparty_user.id == user.id) or \
                         (self.counterparty_business and user.accounts.filter(business_id=self.counterparty_business.id).exists()):
                        return self.sender_display_name or 'Unknown'
                return 'Unknown'
                
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
            
            # Handle P2P exchanges with their description
            if self.transaction_type == 'exchange':
                return self.description or 'Intercambio P2P'
                
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
    
    def resolve_p2p_trade_id(self, info):
        """Return P2P Trade ID if this is an exchange transaction"""
        if self.transaction_type == 'exchange' and self.p2p_trade_id:
            return str(self.p2p_trade_id)
        return None


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
    
    unified_transactions_with_friend = graphene.List(
        UnifiedTransactionType,
        friend_user_id=graphene.ID(),
        friend_phone=graphene.String(),
        limit=graphene.Int(default_value=50),
        offset=graphene.Int(default_value=0),
        description="Get unified transactions between current user and a specific friend"
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
            queryset = UnifiedTransactionTable.objects.filter(
                Q(sender_business=account.business) | 
                Q(counterparty_business=account.business)
            )
        else:
            # For personal accounts, filter by user relationships BUT exclude business transactions
            queryset = UnifiedTransactionTable.objects.filter(
                Q(
                    Q(sender_user=user) & Q(sender_business__isnull=True)
                ) | 
                Q(
                    Q(counterparty_user=user) & Q(counterparty_business__isnull=True)
                )
            )
        
        # Filter by token types if provided
        if token_types:
            queryset = queryset.filter(token_type__in=token_types)
        
        # Order by created_at descending to show newest first
        queryset = queryset.order_by('-created_at')
        
        # Apply pagination and add user address to each transaction for direction calculation
        transactions = list(queryset[offset:offset + limit])
        
        # Set the user's address on each transaction for the resolvers
        for transaction in transactions:
            transaction._user_address = account.sui_address
            
        return transactions
    
    def resolve_unified_transactions_with_friend(self, info, friend_user_id=None, friend_phone=None, 
                                               limit=50, offset=0):
        """Resolve unified transactions between current user and a specific friend"""
        user = info.context.user
        if not user.is_authenticated:
            return []
        
        # Must have either friend_user_id or friend_phone
        if not friend_user_id and not friend_phone:
            return []
        
        # Get the current user's personal account (assuming friends are always personal)
        from users.models import Account
        try:
            account = Account.objects.get(
                user=user,
                account_type='personal',
                account_index=0
            )
        except Account.DoesNotExist:
            return []
        
        # Base query - transactions involving the current user
        queryset = UnifiedTransactionTable.objects.filter(
            Q(
                Q(sender_user=user) & Q(sender_business__isnull=True)
            ) | 
            Q(
                Q(counterparty_user=user) & Q(counterparty_business__isnull=True)
            )
        )
        
        # Filter by friend criteria
        friend_conditions = Q()
        
        if friend_user_id:
            # Filter by friend user ID
            friend_conditions |= Q(
                Q(sender_user_id=friend_user_id) | Q(counterparty_user_id=friend_user_id)
            )
        
        if friend_phone:
            # Filter by friend phone number
            friend_conditions |= Q(
                Q(sender_phone=friend_phone) | Q(counterparty_phone=friend_phone)
            )
        
        # Apply friend filter
        queryset = queryset.filter(friend_conditions)
        
        # Order by created_at descending to show newest first
        queryset = queryset.order_by('-created_at')
        
        # Apply pagination and add user address to each transaction for direction calculation
        transactions = list(queryset[offset:offset + limit])
        
        # Set the user's address on each transaction for the resolvers
        for transaction in transactions:
            transaction._user_address = account.sui_address
            
        return transactions