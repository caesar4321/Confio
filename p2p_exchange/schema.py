import graphene
from graphene_django import DjangoObjectType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth import get_user_model
from channels.layers import get_channel_layer
import json
from .models import (
    P2PPaymentMethod, 
    P2POffer, 
    P2PTrade, 
    P2PMessage, 
    P2PUserStats, 
    P2PEscrow
)
from .default_payment_methods import get_payment_methods_for_country

User = get_user_model()

class P2PPaymentMethodType(graphene.ObjectType):
    id = graphene.ID()
    name = graphene.String()
    display_name = graphene.String()
    icon = graphene.String()
    is_active = graphene.Boolean()

class P2PUserStatsType(DjangoObjectType):
    # Add computed fields for better frontend integration
    stats_type = graphene.String()
    stats_display_name = graphene.String()
    
    class Meta:
        model = P2PUserStats
        fields = (
            'id',
            # New direct relationship fields
            'stats_user', 'stats_business',
            # Keep old fields for backward compatibility
            'user',
            'total_trades', 'completed_trades', 'cancelled_trades',
            'disputed_trades', 'success_rate', 'avg_response_time', 'last_seen_online',
            'total_volume_cusd', 'total_volume_confio', 'is_verified', 'verification_level'
        )
    
    def resolve_stats_type(self, info):
        """Returns 'user' or 'business' for the stats owner"""
        return self.stats_type
    
    def resolve_stats_display_name(self, info):
        """Returns display name for the stats owner"""
        return self.stats_display_name

class P2POfferType(DjangoObjectType):
    payment_methods = graphene.List(P2PPaymentMethodType)
    user_stats = graphene.Field(P2PUserStatsType)
    # Add computed fields for better frontend integration
    offer_type = graphene.String()
    offer_display_name = graphene.String()
    
    class Meta:
        model = P2POffer
        fields = (
            'id', 
            # New direct relationship fields
            'offer_user', 'offer_business',
            # Keep old fields for backward compatibility (but marked as deprecated)
            'user', 'account', 
            'exchange_type', 'token_type', 'rate', 'min_amount',
            'max_amount', 'available_amount', 'payment_methods', 'country_code', 'terms',
            'response_time_minutes', 'status', 'auto_complete_enabled',
            'auto_complete_time_minutes', 'created_at', 'updated_at'
        )
    
    def resolve_user_stats(self, info):
        # Use the offer entity (new or old) to get user stats
        user = self.offer_user if self.offer_user else self.user
        if user:
            stats, created = P2PUserStats.objects.get_or_create(user=user)
            return stats
        return None
    
    def resolve_offer_type(self, info):
        """Returns 'user' or 'business' for the offer creator"""
        return self.offer_type
    
    def resolve_offer_display_name(self, info):
        """Returns display name for the offer creator"""
        return self.offer_display_name
    
    def resolve_payment_methods(self, info):
        """Resolve payment methods for this offer, converting DB records to our GraphQL type"""
        try:
            db_payment_methods = self.payment_methods.all()
            payment_methods = []
            
            for i, db_method in enumerate(db_payment_methods):
                # Create a simple object that matches P2PPaymentMethodType fields
                payment_method = type('PaymentMethod', (), {
                    'id': str(i + 1),  # Simple sequential ID
                    'name': db_method.name,
                    'display_name': db_method.display_name,
                    'icon': db_method.icon,
                    'is_active': db_method.is_active
                })()
                payment_methods.append(payment_method)
            
            return payment_methods
        except Exception as e:
            # Return empty list if there's any issue with payment methods
            return []

class P2PTradeType(DjangoObjectType):
    payment_method = graphene.Field(P2PPaymentMethodType)
    # Add computed fields for better frontend integration
    buyer_type = graphene.String()
    seller_type = graphene.String()
    buyer_display_name = graphene.String()
    seller_display_name = graphene.String()
    
    class Meta:
        model = P2PTrade
        fields = (
            'id', 'offer', 
            # New direct relationship fields
            'buyer_user', 'buyer_business', 'seller_user', 'seller_business',
            # Keep old fields for backward compatibility (but marked as deprecated)
            'buyer', 'seller', 'buyer_account', 'seller_account', 
            'crypto_amount', 'fiat_amount', 'rate_used', 'payment_method', 'status', 
            'expires_at', 'payment_reference', 'payment_notes', 'crypto_transaction_hash', 
            'completed_at', 'dispute_reason', 'disputed_at', 'resolved_at', 'created_at', 'updated_at'
        )
    
    def resolve_payment_method(self, info):
        """Custom resolver for payment_method to ensure it's properly serialized"""
        if self.payment_method:
            return type('PaymentMethod', (), {
                'id': str(self.payment_method.id),
                'name': self.payment_method.name,
                'display_name': self.payment_method.display_name,
                'icon': self.payment_method.icon,
                'is_active': self.payment_method.is_active
            })()
        return None
    
    def resolve_buyer_type(self, info):
        """Returns 'user' or 'business' for the buyer"""
        return self.buyer_type
    
    def resolve_seller_type(self, info):
        """Returns 'user' or 'business' for the seller"""
        return self.seller_type
    
    def resolve_buyer_display_name(self, info):
        """Returns display name for the buyer"""
        return self.buyer_display_name
    
    def resolve_seller_display_name(self, info):
        """Returns display name for the seller"""
        return self.seller_display_name

class P2PMessageType(DjangoObjectType):
    # Add computed fields for better frontend integration
    sender_type = graphene.String()
    sender_display_name = graphene.String()
    
    class Meta:
        model = P2PMessage
        fields = (
            'id', 'trade',
            # New direct relationship fields
            'sender_user', 'sender_business',
            # Keep old fields for backward compatibility
            'sender',
            'message_type', 'content', 'attachment_url',
            'attachment_type', 'is_read', 'read_at', 'created_at'
        )
    
    def resolve_sender_type(self, info):
        """Returns 'user' or 'business' for the sender"""
        return self.sender_type
    
    def resolve_sender_display_name(self, info):
        """Returns display name for the sender"""
        return self.sender_display_name

# Input Types
class CreateP2POfferInput(graphene.InputObjectType):
    exchange_type = graphene.String(required=True)
    token_type = graphene.String(required=True)
    rate = graphene.Decimal(required=True)
    min_amount = graphene.Decimal(required=True)
    max_amount = graphene.Decimal(required=True)
    available_amount = graphene.Decimal(required=True)
    payment_method_ids = graphene.List(graphene.ID, required=True)
    country_code = graphene.String(required=True)  # Required country code for the offer
    terms = graphene.String()
    response_time_minutes = graphene.Int()
    account_id = graphene.ID(required=False)  # Optional: specify which account to use

class CreateP2PTradeInput(graphene.InputObjectType):
    offerId = graphene.ID(required=True)
    cryptoAmount = graphene.Decimal(required=True)
    paymentMethodId = graphene.ID(required=True)
    accountId = graphene.ID(required=False)  # Optional: specify which account to use

class UpdateP2PTradeStatusInput(graphene.InputObjectType):
    trade_id = graphene.ID(required=True)
    status = graphene.String(required=True)
    payment_reference = graphene.String()
    payment_notes = graphene.String()

class SendP2PMessageInput(graphene.InputObjectType):
    trade_id = graphene.ID(required=True)
    content = graphene.String(required=True)
    message_type = graphene.String()
    attachment_url = graphene.String()
    attachment_type = graphene.String()

# Mutations
class CreateP2POffer(graphene.Mutation):
    class Arguments:
        input = CreateP2POfferInput(required=True)

    offer = graphene.Field(P2POfferType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    def mutate(cls, root, info, input):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return CreateP2POffer(
                offer=None,
                success=False,
                errors=["Authentication required"]
            )

        try:
            # Validate exchange type and token type
            if input.exchange_type not in ['BUY', 'SELL']:
                return CreateP2POffer(
                    offer=None,
                    success=False,
                    errors=["Invalid exchange type"]
                )
            
            if input.token_type not in ['cUSD', 'CONFIO']:
                return CreateP2POffer(
                    offer=None,
                    success=False,
                    errors=["Invalid token type"]
                )

            # For SELL offers, validate the user has enough balance
            if input.exchange_type == 'SELL':
                # Get user's current balance for the token they want to sell
                user_balance = _get_user_balance(user, input.token_type)
                
                if user_balance < input.available_amount:
                    return CreateP2POffer(
                        offer=None,
                        success=False,
                        errors=[f"Saldo insuficiente. Tienes {user_balance} {input.token_type} pero intentas vender {input.available_amount}"]
                    )

            # Validate and get/create payment methods for database storage
            if not input.payment_method_ids:
                return CreateP2POffer(
                    offer=None,
                    success=False,
                    errors=["No payment methods provided"]
                )
            
            # Get all available payment methods from hardcoded data to validate
            all_country_methods = []
            for country_code in ['VE', 'US', 'AS', 'AR', 'CO', 'PE', 'MX', '']:  # Include global methods
                all_country_methods.extend(get_payment_methods_for_country(country_code))
            
            # Create a lookup of valid method names
            valid_methods_lookup = {method['name']: method for method in all_country_methods}
            
            # Validate payment method IDs and get or create database records
            payment_methods = []
            for method_id in input.payment_method_ids:
                try:
                    # Convert ID to index (IDs are 1-based, convert to 0-based)
                    method_index = int(method_id) - 1
                    
                    # Get the method data by index from the same list we serve to frontend
                    # Use the country code from the input to get the exact same list
                    all_methods_data = get_payment_methods_for_country(input.country_code or '')
                    
                    if method_index < 0 or method_index >= len(all_methods_data):
                        return CreateP2POffer(
                            offer=None,
                            success=False,
                            errors=[f"ID de método de pago inválido: {method_id}. País: {input.country_code or 'global'}, métodos disponibles: {len(all_methods_data)}"]
                        )
                    
                    method_data = all_methods_data[method_index]
                    
                    # Get or create the payment method in database for offer linking
                    payment_method, created = P2PPaymentMethod.objects.get_or_create(
                        name=method_data['name'],
                        defaults={
                            'display_name': method_data['display_name'],
                            'icon': method_data['icon'],
                            'is_active': method_data['is_active'],
                        }
                    )
                    payment_methods.append(payment_method)
                    
                except (ValueError, IndexError):
                    return CreateP2POffer(
                        offer=None,
                        success=False,
                        errors=[f"Invalid payment method ID: {method_id}"]
                    )
            
            if not payment_methods:
                return CreateP2POffer(
                    offer=None,
                    success=False,
                    errors=["No valid payment methods provided"]
                )

            # Determine offer entity based on account context
            offer_kwargs = {
                'exchange_type': input.exchange_type,
                'token_type': input.token_type,
                'rate': input.rate,
                'min_amount': input.min_amount,
                'max_amount': input.max_amount,
                'available_amount': input.available_amount,
                'country_code': input.country_code,
                'terms': input.terms or '',
                'response_time_minutes': input.response_time_minutes or 15,
                # Keep old fields for backward compatibility
                'user': user,
            }

            if input.account_id:
                from users.models import Account
                try:
                    account = Account.objects.get(id=input.account_id, user=user)
                    offer_kwargs['account'] = account
                    
                    if account.account_type == 'business' and account.business:
                        # Business offer
                        offer_kwargs['offer_business'] = account.business
                    else:
                        # Personal offer
                        offer_kwargs['offer_user'] = user
                except Account.DoesNotExist:
                    return CreateP2POffer(
                        offer=None,
                        success=False,
                        errors=["Account not found or access denied"]
                    )
            else:
                # Default to personal offer
                offer_kwargs['offer_user'] = user

            # Create offer with new direct relationships
            offer = P2POffer.objects.create(**offer_kwargs)
            
            offer.payment_methods.set(payment_methods)

            return CreateP2POffer(
                offer=offer,
                success=True,
                errors=None
            )

        except Exception as e:
            return CreateP2POffer(
                offer=None,
                success=False,
                errors=[str(e)]
            )
    
def _get_user_balance(user, token_type):
    """Get user's balance for a specific token type"""
    # Normalize token type
    normalized_token_type = token_type.upper()
    if normalized_token_type == 'CUSD':
        normalized_token_type = 'cUSD'
    
    # For now, return mock balances based on token type
    # In a real implementation, this would query the blockchain or a balance service
    mock_balances = {
        'cUSD': '2850.35',
        'CONFIO': '234.18',
        'USDC': '458.22'
    }
    
    balance_str = mock_balances.get(normalized_token_type, '0')
    return float(balance_str)

class CreateP2PTrade(graphene.Mutation):
    class Arguments:
        input = CreateP2PTradeInput(required=True)

    trade = graphene.Field(P2PTradeType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    def mutate(cls, root, info, input):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return CreateP2PTrade(
                trade=None,
                success=False,
                errors=["Authentication required"]
            )

        try:
            # Get offer
            offer = P2POffer.objects.get(id=input.offerId, status='ACTIVE')
            
            # Validate user can't trade with themselves
            if offer.user == user:
                return CreateP2PTrade(
                    trade=None,
                    success=False,
                    errors=["Cannot trade with yourself"]
                )

            # Validate amount
            if input.cryptoAmount < offer.min_amount or input.cryptoAmount > offer.max_amount:
                return CreateP2PTrade(
                    trade=None,
                    success=False,
                    errors=[f"Amount must be between {offer.min_amount} and {offer.max_amount}"]
                )

            if input.cryptoAmount > offer.available_amount:
                return CreateP2PTrade(
                    trade=None,
                    success=False,
                    errors=["Insufficient available amount"]
                )

            # Validate payment method - convert sequential ID to actual database ID
            # The frontend sends sequential IDs (1, 2, 3) but we need actual DB IDs
            try:
                payment_method_index = int(input.paymentMethodId) - 1  # Convert to 0-based index
                offer_payment_methods = list(offer.payment_methods.all())
                
                if payment_method_index < 0 or payment_method_index >= len(offer_payment_methods):
                    return CreateP2PTrade(
                        trade=None,
                        success=False,
                        errors=["Payment method not found"]
                    )
                
                payment_method = offer_payment_methods[payment_method_index]
                
            except (ValueError, IndexError):
                return CreateP2PTrade(
                    trade=None,
                    success=False,
                    errors=["Payment method not found"]
                )

            # Calculate fiat amount
            fiat_amount = input.cryptoAmount * offer.rate

            # Get user's account if specified and determine entity type
            user_entity = user  # Default to user for personal trades
            user_entity_type = 'user'
            offer_entity = offer.user  # Default to user for personal trades
            offer_entity_type = 'user'
            user_account = None  # Initialize user_account
            
            if input.accountId:
                from users.models import Account
                try:
                    user_account = Account.objects.get(id=input.accountId, user=user)
                    if user_account.account_type == 'business' and user_account.business:
                        user_entity = user_account.business
                        user_entity_type = 'business'
                except Account.DoesNotExist:
                    return CreateP2PTrade(
                        trade=None,
                        success=False,
                        errors=["Account not found or access denied"]
                    )
            
            # Check offer's account type
            if offer.account and offer.account.account_type == 'business' and offer.account.business:
                offer_entity = offer.account.business
                offer_entity_type = 'business'

            # Determine buyer and seller entities based on offer type
            trade_kwargs = {
                'offer': offer,
                'crypto_amount': input.cryptoAmount,
                'fiat_amount': fiat_amount,
                'rate_used': offer.rate,
                'payment_method': payment_method,
                'expires_at': timezone.now() + timedelta(minutes=30),
                # Keep old fields for backward compatibility
                'buyer': user if offer.exchange_type == 'SELL' else offer.user,
                'seller': offer.user if offer.exchange_type == 'SELL' else user,
                'buyer_account': user_account if input.accountId and offer.exchange_type == 'SELL' else offer.account,
                'seller_account': offer.account if offer.exchange_type == 'SELL' else (user_account if input.accountId else None),
            }
            
            if offer.exchange_type == 'SELL':
                # Offer owner is selling crypto, trade initiator is buying
                if user_entity_type == 'business':
                    trade_kwargs['buyer_business'] = user_entity
                else:
                    trade_kwargs['buyer_user'] = user_entity
                    
                if offer_entity_type == 'business':
                    trade_kwargs['seller_business'] = offer_entity
                else:
                    trade_kwargs['seller_user'] = offer_entity
            else:
                # Offer owner is buying crypto, trade initiator is selling
                if offer_entity_type == 'business':
                    trade_kwargs['buyer_business'] = offer_entity
                else:
                    trade_kwargs['buyer_user'] = offer_entity
                    
                if user_entity_type == 'business':
                    trade_kwargs['seller_business'] = user_entity
                else:
                    trade_kwargs['seller_user'] = user_entity

            # Create trade with new direct relationships
            trade = P2PTrade.objects.create(**trade_kwargs)

            # Update offer available amount
            offer.available_amount -= input.cryptoAmount
            offer.save()

            return CreateP2PTrade(
                trade=trade,
                success=True,
                errors=None
            )

        except P2POffer.DoesNotExist:
            return CreateP2PTrade(
                trade=None,
                success=False,
                errors=["Offer not found or not active"]
            )
        except P2PPaymentMethod.DoesNotExist:
            return CreateP2PTrade(
                trade=None,
                success=False,
                errors=["Payment method not found"]
            )
        except Exception as e:
            return CreateP2PTrade(
                trade=None,
                success=False,
                errors=[str(e)]
            )

class UpdateP2PTradeStatus(graphene.Mutation):
    class Arguments:
        input = UpdateP2PTradeStatusInput(required=True)

    trade = graphene.Field(P2PTradeType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    def mutate(cls, root, info, input):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return UpdateP2PTradeStatus(
                trade=None,
                success=False,
                errors=["Authentication required"]
            )

        try:
            # Get trade and verify user is part of it
            trade = P2PTrade.objects.filter(
                id=input.trade_id
            ).filter(
                models.Q(buyer=user) | models.Q(seller=user)
            ).get()

            # Validate status transition
            valid_statuses = [choice[0] for choice in P2PTrade.STATUS_CHOICES]
            if input.status not in valid_statuses:
                return UpdateP2PTradeStatus(
                    trade=None,
                    success=False,
                    errors=["Invalid status"]
                )

            # Update trade
            trade.status = input.status
            if input.payment_reference:
                trade.payment_reference = input.payment_reference
            if input.payment_notes:
                trade.payment_notes = input.payment_notes

            if input.status == 'COMPLETED':
                trade.completed_at = timezone.now()

            trade.save()

            return UpdateP2PTradeStatus(
                trade=trade,
                success=True,
                errors=None
            )

        except P2PTrade.DoesNotExist:
            return UpdateP2PTradeStatus(
                trade=None,
                success=False,
                errors=["Trade not found or access denied"]
            )
        except Exception as e:
            return UpdateP2PTradeStatus(
                trade=None,
                success=False,
                errors=[str(e)]
            )

class SendP2PMessage(graphene.Mutation):
    class Arguments:
        input = SendP2PMessageInput(required=True)

    message = graphene.Field(P2PMessageType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    @classmethod
    def mutate(cls, root, info, input):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return SendP2PMessage(
                message=None,
                success=False,
                errors=["Authentication required"]
            )

        try:
            # Get trade and verify user is part of it
            trade = P2PTrade.objects.filter(
                id=input.trade_id
            ).filter(
                models.Q(buyer=user) | models.Q(seller=user)
            ).get()

            # Determine sender entity based on the trade context
            message_kwargs = {
                'trade': trade,
                'content': input.content,
                'message_type': input.message_type or 'TEXT',
                'attachment_url': input.attachment_url or '',
                'attachment_type': input.attachment_type or '',
                # Keep old field for backward compatibility
                'sender': user,
            }
            
            # Check if user is participating as a business or personal account
            if trade.buyer_user == user:
                message_kwargs['sender_user'] = user
            elif trade.buyer_business and hasattr(trade.buyer_business, 'accounts'):
                # Check if user has access to this business
                if trade.buyer_business.accounts.filter(user=user).exists():
                    message_kwargs['sender_business'] = trade.buyer_business
                else:
                    message_kwargs['sender_user'] = user
            elif trade.seller_user == user:
                message_kwargs['sender_user'] = user
            elif trade.seller_business and hasattr(trade.seller_business, 'accounts'):
                # Check if user has access to this business
                if trade.seller_business.accounts.filter(user=user).exists():
                    message_kwargs['sender_business'] = trade.seller_business
                else:
                    message_kwargs['sender_user'] = user
            else:
                # Default to personal user
                message_kwargs['sender_user'] = user

            # Create message with new direct relationships
            message = P2PMessage.objects.create(**message_kwargs)

            # Broadcast message via channel layer for GraphQL subscriptions
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            
            if channel_layer:
                # Format sender info similar to subscription consumer
                sender_info = {}
                if message.sender_user:
                    sender_info = {
                        'id': str(message.sender_user.id),
                        'username': message.sender_user.username,
                        'firstName': message.sender_user.first_name,
                        'lastName': message.sender_user.last_name,
                        'type': 'user'
                    }
                elif message.sender_business:
                    business_account = message.sender_business.accounts.first()
                    if business_account:
                        sender_info = {
                            'id': str(business_account.user.id),
                            'username': business_account.user.username,
                            'firstName': business_account.user.first_name,
                            'lastName': business_account.user.last_name,
                            'type': 'business',
                            'businessName': message.sender_business.name,
                            'businessId': str(message.sender_business.id)
                        }
                else:
                    # Fallback
                    sender_info = {
                        'id': str(message.sender.id),
                        'username': message.sender.username,
                        'firstName': message.sender.first_name,
                        'lastName': message.sender.last_name,
                        'type': 'user'
                    }
                
                # Broadcast to GraphQL subscription group
                group_name = f'trade_chat_{trade.id}'
                message_data = {
                    'id': message.id,
                    'sender': sender_info,
                    'content': message.content,
                    'messageType': message.message_type,
                    'createdAt': message.created_at.isoformat(),
                    'isRead': message.is_read,
                }
                
                async_to_sync(channel_layer.group_send)(
                    group_name,
                    {
                        'type': 'chat_message',
                        'trade_id': trade.id,
                        'message': message_data
                    }
                )

            return SendP2PMessage(
                message=message,
                success=True,
                errors=None
            )

        except P2PTrade.DoesNotExist:
            return SendP2PMessage(
                message=None,
                success=False,
                errors=["Trade not found or access denied"]
            )
        except Exception as e:
            return SendP2PMessage(
                message=None,
                success=False,
                errors=[str(e)]
            )

# Queries
class Query(graphene.ObjectType):
    p2p_offers = graphene.List(
        P2POfferType,
        exchange_type=graphene.String(),
        token_type=graphene.String(),
        payment_method=graphene.String(),
        country_code=graphene.String()
    )
    p2p_offer = graphene.Field(P2POfferType, id=graphene.ID(required=True))
    my_p2p_offers = graphene.List(P2POfferType)
    my_p2p_trades = graphene.List(P2PTradeType, account_id=graphene.ID())
    p2p_trade = graphene.Field(P2PTradeType, id=graphene.ID(required=True))
    p2p_trade_messages = graphene.List(P2PMessageType, trade_id=graphene.ID(required=True))
    p2p_payment_methods = graphene.List(P2PPaymentMethodType, country_code=graphene.String())

    def resolve_p2p_offers(self, info, exchange_type=None, token_type=None, payment_method=None, country_code=None):
        queryset = P2POffer.objects.filter(status='ACTIVE').select_related('user')
        
        if exchange_type:
            queryset = queryset.filter(exchange_type=exchange_type)
        if token_type:
            queryset = queryset.filter(token_type=token_type)
        if payment_method:
            queryset = queryset.filter(payment_methods__name=payment_method)
        
        # Filter by country: only show offers created for that specific country
        if country_code:
            queryset = queryset.filter(country_code=country_code)
        
        return queryset.order_by('-created_at')

    def resolve_p2p_offer(self, info, id):
        try:
            return P2POffer.objects.get(id=id)
        except P2POffer.DoesNotExist:
            return None

    def resolve_my_p2p_offers(self, info):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        
        return P2POffer.objects.filter(user=user).order_by('-created_at')

    def resolve_my_p2p_trades(self, info, account_id=None):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        
        if account_id:
            # Filter trades for a specific account context
            from users.models import Account
            try:
                account = Account.objects.get(id=account_id, user=user)
                if account.account_type == 'business' and account.business:
                    # Show only business trades for this specific business
                    return P2PTrade.objects.filter(
                        models.Q(buyer_business=account.business) | models.Q(seller_business=account.business)
                    ).order_by('-created_at')
                else:
                    # Show only personal trades for this user
                    return P2PTrade.objects.filter(
                        models.Q(buyer_user=user) | models.Q(seller_user=user)
                    ).order_by('-created_at')
            except Account.DoesNotExist:
                return []
        else:
            # No account filter - show all trades for this user (all accounts)
            from users.models import Business
            user_businesses = Business.objects.filter(accounts__user=user)
            
            # Find trades where user is involved as a person OR through their businesses
            # NEW: Use direct relationships for cleaner semantics
            return P2PTrade.objects.filter(
                models.Q(buyer_user=user) | models.Q(seller_user=user) |
                models.Q(buyer_business__in=user_businesses) | models.Q(seller_business__in=user_businesses)
            ).order_by('-created_at')

    def resolve_p2p_trade(self, info, id):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return None
        
        try:
            return P2PTrade.objects.filter(
                id=id
            ).filter(
                models.Q(buyer=user) | models.Q(seller=user)
            ).get()
        except P2PTrade.DoesNotExist:
            return None

    def resolve_p2p_trade_messages(self, info, trade_id):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        
        try:
            trade = P2PTrade.objects.filter(
                id=trade_id
            ).filter(
                models.Q(buyer=user) | models.Q(seller=user)
            ).get()
            return P2PMessage.objects.filter(trade=trade).order_by('created_at')
        except P2PTrade.DoesNotExist:
            return []

    def resolve_p2p_payment_methods(self, info, country_code=None):
        import datetime
        import random
        request_id = random.randint(1000, 9999)
        print(f"🔍 DEBUG [{datetime.datetime.now()}] REQ-{request_id}: resolve_p2p_payment_methods called with country_code: '{country_code}'")
        
        # Force fresh import to avoid caching issues
        import importlib
        from . import default_payment_methods
        importlib.reload(default_payment_methods)
        
        # Get payment methods directly from Python file (hardcoded data)
        methods_data = default_payment_methods.get_payment_methods_for_country(country_code or '')
        print(f"📋 DEBUG REQ-{request_id}: get_payment_methods_for_country('{country_code or ''}') returned {len(methods_data)} methods:")
        for method in methods_data:
            print(f"   - {method['display_name']} ({method['name']})")
        
        # Convert to GraphQL objects with simple sequential IDs
        payment_methods = []
        for i, method_data in enumerate(methods_data):
            # Create a simple object that matches P2PPaymentMethodType fields
            payment_method = type('PaymentMethod', (), {
                'id': str(i + 1),  # Simple sequential ID
                'name': method_data['name'],
                'display_name': method_data['display_name'],
                'icon': method_data['icon'],
                'is_active': method_data['is_active']
            })()
            payment_methods.append(payment_method)
        
        print(f"✅ DEBUG REQ-{request_id}: Returning {len(payment_methods)} payment methods to GraphQL")
        print(f"🚀 DEBUG REQ-{request_id}: Final GraphQL objects being returned:")
        for i, pm in enumerate(payment_methods):
            print(f"   {i+1}. {pm.display_name} ({pm.name}) - ID: {pm.id}")
        
        # Don't sort to maintain consistent IDs - sorting changes the order and breaks ID mapping
        return payment_methods

# Mutations
class Mutation(graphene.ObjectType):
    create_p2p_offer = CreateP2POffer.Field()
    create_p2p_trade = CreateP2PTrade.Field()
    update_p2p_trade_status = UpdateP2PTradeStatus.Field()
    send_p2p_message = SendP2PMessage.Field()

# Subscriptions
class TradeChatMessageSubscription(graphene.ObjectType):
    """Subscription for new chat messages in a trade"""
    trade_id = graphene.ID(required=True)
    message = graphene.Field(P2PMessageType)

class TradeStatusSubscription(graphene.ObjectType):
    """Subscription for trade status updates"""
    trade_id = graphene.ID(required=True) 
    trade = graphene.Field(P2PTradeType)
    status = graphene.String()
    updated_by = graphene.ID()

class TypingIndicatorSubscription(graphene.ObjectType):
    """Subscription for typing indicators"""
    trade_id = graphene.ID(required=True)
    user_id = graphene.ID()
    username = graphene.String()
    is_typing = graphene.Boolean()

class Subscription(graphene.ObjectType):
    """GraphQL Subscriptions for P2P Exchange"""
    
    trade_chat_message = graphene.Field(
        TradeChatMessageSubscription,
        trade_id=graphene.ID(required=True)
    )
    
    trade_status_update = graphene.Field(
        TradeStatusSubscription,
        trade_id=graphene.ID(required=True)
    )
    
    typing_indicator = graphene.Field(
        TypingIndicatorSubscription,
        trade_id=graphene.ID(required=True)
    )

    def resolve_trade_chat_message(self, info, trade_id):
        """Subscribe to chat messages for a specific trade"""
        # Check if user has access to this trade
        user = info.context.user
        if not user or not user.is_authenticated:
            raise ValidationError("Authentication required")
        
        try:
            trade = P2PTrade.objects.get(id=trade_id)
            # Check access using new direct relationships
            has_access = (
                trade.buyer_user == user or 
                trade.seller_user == user or
                # Also check business relationships
                (trade.buyer_business and trade.buyer_business.accounts.filter(user=user).exists()) or
                (trade.seller_business and trade.seller_business.accounts.filter(user=user).exists()) or
                # Fallback to old system for backward compatibility
                trade.buyer == user or 
                trade.seller == user
            )
            if not has_access:
                raise ValidationError("Access denied to this trade")
        except P2PTrade.DoesNotExist:
            raise ValidationError("Trade not found")
            
        # Return subscription generator
        return self._trade_chat_message_generator(trade_id)
    
    def resolve_trade_status_update(self, info, trade_id):
        """Subscribe to status updates for a specific trade"""
        # Similar access check as above
        user = info.context.user
        if not user or not user.is_authenticated:
            raise ValidationError("Authentication required")
        
        try:
            trade = P2PTrade.objects.get(id=trade_id)
            has_access = (
                trade.buyer_user == user or 
                trade.seller_user == user or
                (trade.buyer_business and trade.buyer_business.accounts.filter(user=user).exists()) or
                (trade.seller_business and trade.seller_business.accounts.filter(user=user).exists()) or
                trade.buyer == user or 
                trade.seller == user
            )
            if not has_access:
                raise ValidationError("Access denied to this trade")
        except P2PTrade.DoesNotExist:
            raise ValidationError("Trade not found")
            
        return self._trade_status_update_generator(trade_id)
    
    def resolve_typing_indicator(self, info, trade_id):
        """Subscribe to typing indicators for a specific trade"""
        # Similar access check
        user = info.context.user
        if not user or not user.is_authenticated:
            raise ValidationError("Authentication required")
        
        try:
            trade = P2PTrade.objects.get(id=trade_id)
            has_access = (
                trade.buyer_user == user or 
                trade.seller_user == user or
                (trade.buyer_business and trade.buyer_business.accounts.filter(user=user).exists()) or
                (trade.seller_business and trade.seller_business.accounts.filter(user=user).exists()) or
                trade.buyer == user or 
                trade.seller == user
            )
            if not has_access:
                raise ValidationError("Access denied to this trade")
        except P2PTrade.DoesNotExist:
            raise ValidationError("Trade not found")
            
        return self._typing_indicator_generator(trade_id)
    
    def _trade_chat_message_generator(self, trade_id):
        """Generator for chat message subscription"""
        # This will be implemented with channels layer integration
        channel_layer = get_channel_layer()
        group_name = f'trade_chat_{trade_id}'
        
        # For now, return empty generator - will be properly implemented with channels
        return iter([])
    
    def _trade_status_update_generator(self, trade_id):
        """Generator for trade status update subscription"""
        channel_layer = get_channel_layer()
        group_name = f'trade_status_{trade_id}'
        return iter([])
    
    def _typing_indicator_generator(self, trade_id):
        """Generator for typing indicator subscription"""
        channel_layer = get_channel_layer()
        group_name = f'trade_typing_{trade_id}'
        return iter([])