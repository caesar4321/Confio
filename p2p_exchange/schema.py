import graphene
from graphene_django import DjangoObjectType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth import get_user_model
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
    class Meta:
        model = P2PUserStats
        fields = (
            'id', 'user', 'total_trades', 'completed_trades', 'cancelled_trades',
            'disputed_trades', 'success_rate', 'avg_response_time', 'last_seen_online',
            'total_volume_cusd', 'total_volume_confio', 'is_verified', 'verification_level'
        )

class P2POfferType(DjangoObjectType):
    payment_methods = graphene.List(P2PPaymentMethodType)
    user_stats = graphene.Field(P2PUserStatsType)
    
    class Meta:
        model = P2POffer
        fields = (
            'id', 'user', 'exchange_type', 'token_type', 'rate', 'min_amount',
            'max_amount', 'available_amount', 'payment_methods', 'country_code', 'terms',
            'response_time_minutes', 'status', 'auto_complete_enabled',
            'auto_complete_time_minutes', 'created_at', 'updated_at'
        )
    
    def resolve_user_stats(self, info):
        stats, created = P2PUserStats.objects.get_or_create(user=self.user)
        return stats
    
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
    class Meta:
        model = P2PTrade
        fields = (
            'id', 'offer', 'buyer', 'seller', 'crypto_amount', 'fiat_amount',
            'rate_used', 'payment_method', 'status', 'expires_at', 'payment_reference',
            'payment_notes', 'crypto_transaction_hash', 'completed_at', 'dispute_reason',
            'disputed_at', 'resolved_at', 'created_at', 'updated_at'
        )

class P2PMessageType(DjangoObjectType):
    class Meta:
        model = P2PMessage
        fields = (
            'id', 'trade', 'sender', 'message_type', 'content', 'attachment_url',
            'attachment_type', 'is_read', 'read_at', 'created_at'
        )

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

class CreateP2PTradeInput(graphene.InputObjectType):
    offer_id = graphene.ID(required=True)
    crypto_amount = graphene.Decimal(required=True)
    payment_method_id = graphene.ID(required=True)

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

            # Create offer
            offer = P2POffer.objects.create(
                user=user,
                exchange_type=input.exchange_type,
                token_type=input.token_type,
                rate=input.rate,
                min_amount=input.min_amount,
                max_amount=input.max_amount,
                available_amount=input.available_amount,
                country_code=input.country_code,
                terms=input.terms or '',
                response_time_minutes=input.response_time_minutes or 15
            )
            
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
            offer = P2POffer.objects.get(id=input.offer_id, status='ACTIVE')
            
            # Validate user can't trade with themselves
            if offer.user == user:
                return CreateP2PTrade(
                    trade=None,
                    success=False,
                    errors=["Cannot trade with yourself"]
                )

            # Validate amount
            if input.crypto_amount < offer.min_amount or input.crypto_amount > offer.max_amount:
                return CreateP2PTrade(
                    trade=None,
                    success=False,
                    errors=[f"Amount must be between {offer.min_amount} and {offer.max_amount}"]
                )

            if input.crypto_amount > offer.available_amount:
                return CreateP2PTrade(
                    trade=None,
                    success=False,
                    errors=["Insufficient available amount"]
                )

            # Validate payment method
            payment_method = P2PPaymentMethod.objects.get(id=input.payment_method_id)
            if payment_method not in offer.payment_methods.all():
                return CreateP2PTrade(
                    trade=None,
                    success=False,
                    errors=["Payment method not accepted for this offer"]
                )

            # Calculate fiat amount
            fiat_amount = input.crypto_amount * offer.rate

            # Determine buyer and seller based on offer type
            if offer.exchange_type == 'SELL':
                # Offer owner is selling crypto, trade initiator is buying
                buyer = user
                seller = offer.user
            else:
                # Offer owner is buying crypto, trade initiator is selling
                buyer = offer.user
                seller = user

            # Create trade
            trade = P2PTrade.objects.create(
                offer=offer,
                buyer=buyer,
                seller=seller,
                crypto_amount=input.crypto_amount,
                fiat_amount=fiat_amount,
                rate_used=offer.rate,
                payment_method=payment_method,
                expires_at=timezone.now() + timedelta(minutes=30)
            )

            # Update offer available amount
            offer.available_amount -= input.crypto_amount
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

            # Create message
            message = P2PMessage.objects.create(
                trade=trade,
                sender=user,
                content=input.content,
                message_type=input.message_type or 'TEXT',
                attachment_url=input.attachment_url or '',
                attachment_type=input.attachment_type or ''
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
    my_p2p_trades = graphene.List(P2PTradeType)
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

    def resolve_my_p2p_trades(self, info):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        
        return P2PTrade.objects.filter(
            models.Q(buyer=user) | models.Q(seller=user)
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