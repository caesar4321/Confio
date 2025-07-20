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

User = get_user_model()

class P2PPaymentMethodType(DjangoObjectType):
    class Meta:
        model = P2PPaymentMethod
        fields = ('id', 'name', 'display_name', 'is_active', 'icon')

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
            'max_amount', 'available_amount', 'payment_methods', 'terms',
            'response_time_minutes', 'status', 'auto_complete_enabled',
            'auto_complete_time_minutes', 'created_at', 'updated_at'
        )
    
    def resolve_user_stats(self, info):
        stats, created = P2PUserStats.objects.get_or_create(user=self.user)
        return stats

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

            # Validate payment methods
            payment_methods = P2PPaymentMethod.objects.filter(
                id__in=input.payment_method_ids,
                is_active=True
            )
            if not payment_methods.exists():
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
        payment_method=graphene.String()
    )
    p2p_offer = graphene.Field(P2POfferType, id=graphene.ID(required=True))
    my_p2p_offers = graphene.List(P2POfferType)
    my_p2p_trades = graphene.List(P2PTradeType)
    p2p_trade = graphene.Field(P2PTradeType, id=graphene.ID(required=True))
    p2p_trade_messages = graphene.List(P2PMessageType, trade_id=graphene.ID(required=True))
    p2p_payment_methods = graphene.List(P2PPaymentMethodType)

    def resolve_p2p_offers(self, info, exchange_type=None, token_type=None, payment_method=None):
        queryset = P2POffer.objects.filter(status='ACTIVE').select_related('user')
        
        if exchange_type:
            queryset = queryset.filter(exchange_type=exchange_type)
        if token_type:
            queryset = queryset.filter(token_type=token_type)
        if payment_method:
            queryset = queryset.filter(payment_methods__name=payment_method)
        
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

    def resolve_p2p_payment_methods(self, info):
        return P2PPaymentMethod.objects.filter(is_active=True)

# Mutations
class Mutation(graphene.ObjectType):
    create_p2p_offer = CreateP2POffer.Field()
    create_p2p_trade = CreateP2PTrade.Field()
    update_p2p_trade_status = UpdateP2PTradeStatus.Field()
    send_p2p_message = SendP2PMessage.Field()