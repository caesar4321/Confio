import graphene
from graphene_django import DjangoObjectType
from django.utils import timezone
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
    P2PEscrow,
    P2PTradeRating,
    P2PTradeConfirmation,
    P2PDispute,
    P2PFavoriteTrader
)
from .default_payment_methods import get_payment_methods_for_country

User = get_user_model()

# Removed circular import - BankType will be imported dynamically

class P2PPaymentMethodType(graphene.ObjectType):
    id = graphene.ID()
    name = graphene.String()
    display_name = graphene.String()
    icon = graphene.String()
    is_active = graphene.Boolean()
    provider_type = graphene.String()
    requires_phone = graphene.Boolean()
    requires_email = graphene.Boolean()
    requires_account_number = graphene.Boolean()
    country_code = graphene.String()
    bank = graphene.Field('users.schema.BankType')
    country = graphene.Field('users.schema.CountryType')
    
    # GraphQL camelCase aliases
    displayName = graphene.String()
    isActive = graphene.Boolean()
    providerType = graphene.String()
    requiresPhone = graphene.Boolean()
    requiresEmail = graphene.Boolean()
    requiresAccountNumber = graphene.Boolean()
    countryCode = graphene.String()
    
    def resolve_displayName(self, info):
        return self.display_name
        
    def resolve_isActive(self, info):
        return self.is_active
        
    def resolve_providerType(self, info):
        return self.provider_type
        
    def resolve_requiresPhone(self, info):
        return self.requires_phone
        
    def resolve_requiresEmail(self, info):
        return self.requires_email
        
    def resolve_requiresAccountNumber(self, info):
        return self.requires_account_number
        
    def resolve_countryCode(self, info):
        return self.country_code

class P2PUserStatsType(DjangoObjectType):
    # Add computed fields for better frontend integration
    stats_type = graphene.String()
    stats_display_name = graphene.String()
    # Override decimal fields to return float
    avg_rating = graphene.Float()
    success_rate = graphene.Float()  # Override to return Float instead of Decimal
    last_seen_online = graphene.String()  # Override to return ISO string instead of DateTime
    
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
    
    def resolve_avg_rating(self, info):
        """Convert Decimal to float for GraphQL compatibility"""
        return float(self.avg_rating) if self.avg_rating is not None else 0.0
    
    def resolve_success_rate(self, info):
        """Convert Decimal to float for GraphQL compatibility"""
        return float(self.success_rate) if self.success_rate is not None else 0.0
    
    def resolve_last_seen_online(self, info):
        """Convert DateTime to ISO string for GraphQL compatibility"""
        if self.last_seen_online:
            # Check if it's a datetime object with isoformat method
            if hasattr(self.last_seen_online, 'isoformat'):
                return self.last_seen_online.isoformat()
            # If it's already a string, return as is
            return str(self.last_seen_online)
        return None

class P2PFavoriteTraderType(DjangoObjectType):
    favorite_display_name = graphene.String()
    favorite_type = graphene.String()  # 'user' or 'business'
    is_online = graphene.Boolean()
    
    class Meta:
        model = P2PFavoriteTrader
        fields = '__all__'
    
    def resolve_favorite_display_name(self, info):
        if self.favorite_user:
            return f"{self.favorite_user.first_name} {self.favorite_user.last_name}".strip() or self.favorite_user.username
        elif self.favorite_business:
            return self.favorite_business.name
        return "Unknown"
    
    def resolve_favorite_type(self, info):
        return 'business' if self.favorite_business else 'user'
    
    def resolve_is_online(self, info):
        # Check last activity within 5 minutes
        from django.utils import timezone
        from datetime import timedelta
        
        if self.favorite_user:
            last_seen = getattr(self.favorite_user, 'last_seen_at', None)
            if last_seen:
                return (timezone.now() - last_seen) < timedelta(minutes=5)
        # For businesses, we could check if any of their accounts are online
        return False


class P2POfferType(DjangoObjectType):
    payment_methods = graphene.List(P2PPaymentMethodType)
    user_stats = graphene.Field(P2PUserStatsType)
    # Add computed fields for better frontend integration
    offer_type = graphene.String()
    offer_display_name = graphene.String()
    is_favorite = graphene.Boolean()
    
    class Meta:
        model = P2POffer
        fields = (
            'id', 
            # New direct relationship fields
            'offer_user', 'offer_business',
            # Keep old fields for backward compatibility (but marked as deprecated)
            'user', 'account', 
            'exchange_type', 'token_type', 'rate', 'min_amount',
            'max_amount', 'available_amount', 'payment_methods', 'country_code', 'currency_code', 'terms',
            'response_time_minutes', 'status', 'auto_complete_enabled',
            'auto_complete_time_minutes', 'created_at', 'updated_at'
        )
    
    def resolve_user_stats(self, info):
        # Use the offer entity (new or old) to get user stats
        user = self.offer_user if self.offer_user else self.user
        business = self.offer_business
        
        if business:
            # For business offers, get or create stats for the business
            stats, created = P2PUserStats.objects.get_or_create(
                stats_business=business,
                defaults={
                    'user': user,  # Set deprecated field for compatibility
                    'total_trades': 0,
                    'completed_trades': 0,
                    'success_rate': 0,
                    'avg_rating': 0
                }
            )
            return stats
        elif user:
            # For personal offers, get or create stats for the user
            stats, created = P2PUserStats.objects.get_or_create(
                stats_user=user,
                defaults={
                    'user': user,  # Set deprecated field for compatibility
                    'total_trades': 0,
                    'completed_trades': 0,
                    'success_rate': 0,
                    'avg_rating': 0
                }
            )
            return stats
        return None
    
    def resolve_offer_type(self, info):
        """Returns 'user' or 'business' for the offer creator"""
        return self.offer_type
    
    def resolve_offer_display_name(self, info):
        """Returns display name for the offer creator"""
        return self.offer_display_name
    
    def resolve_is_favorite(self, info):
        """Check if current user has favorited this trader"""
        user = info.context.user
        if not user.is_authenticated:
            return False
        
        # Get the active account context from the request
        request = info.context
        active_account_type = getattr(request, 'active_account_type', 'personal')
        active_account_index = getattr(request, 'active_account_index', 0)
        
        # Determine favoriter_business if acting as business account
        favoriter_business = None
        if active_account_type == 'business':
            from users.models import Account
            active_account = Account.objects.filter(
                user=user,
                account_type='business',
                account_index=active_account_index
            ).first()
            
            if active_account and active_account.business:
                favoriter_business = active_account.business
        
        # Check if the offer creator is in user's favorites based on account context
        if self.offer_user:
            if favoriter_business:
                return P2PFavoriteTrader.objects.filter(
                    user=user,
                    favoriter_business=favoriter_business,
                    favorite_user=self.offer_user
                ).exists()
            else:
                return P2PFavoriteTrader.objects.filter(
                    user=user,
                    favoriter_business__isnull=True,
                    favorite_user=self.offer_user
                ).exists()
        elif self.offer_business:
            if favoriter_business:
                return P2PFavoriteTrader.objects.filter(
                    user=user,
                    favoriter_business=favoriter_business,
                    favorite_business=self.offer_business
                ).exists()
            else:
                return P2PFavoriteTrader.objects.filter(
                    user=user,
                    favoriter_business__isnull=True,
                    favorite_business=self.offer_business
                ).exists()
        
        return False
    
    def resolve_payment_methods(self, info):
        """Resolve payment methods for this offer, converting DB records to our GraphQL type"""
        try:
            # Only return active payment methods
            db_payment_methods = self.payment_methods.filter(is_active=True)
            payment_methods = []
            
            for db_method in db_payment_methods:
                # Create a simple object that matches P2PPaymentMethodType fields
                payment_method = type('PaymentMethod', (), {
                    'id': str(db_method.id),
                    'name': db_method.name,
                    'display_name': db_method.display_name,
                    'icon': db_method.icon,
                    'is_active': db_method.is_active,
                    'provider_type': db_method.provider_type,
                    'requires_phone': db_method.requires_phone,
                    'requires_email': db_method.requires_email,
                    'requires_account_number': db_method.requires_account_number,
                    'country_code': db_method.country_code,
                    'bank': db_method.bank
                })()
                payment_methods.append(payment_method)
            
            return payment_methods
        except Exception as e:
            # Return empty list if there's any issue with payment methods
            return []

class P2PTradeRatingType(DjangoObjectType):
    """GraphQL type for P2P trade ratings"""
    rater_type = graphene.String()
    ratee_type = graphene.String()
    rater_display_name = graphene.String()
    ratee_display_name = graphene.String()
    
    class Meta:
        model = P2PTradeRating
        fields = (
            'id', 'trade',
            'rater_user', 'rater_business',
            'ratee_user', 'ratee_business',
            'overall_rating', 'communication_rating',
            'speed_rating', 'reliability_rating',
            'comment', 'tags', 'rated_at'
        )
    
    def resolve_rater_type(self, info):
        return self.rater_type
    
    def resolve_ratee_type(self, info):
        return self.ratee_type
    
    def resolve_rater_display_name(self, info):
        return self.rater_display_name
    
    def resolve_ratee_display_name(self, info):
        return self.ratee_display_name

class P2PTradeConfirmationType(DjangoObjectType):
    """GraphQL type for P2P trade confirmations"""
    confirmer_type = graphene.String()
    confirmer_display_name = graphene.String()
    
    class Meta:
        model = P2PTradeConfirmation
        fields = (
            'id', 'trade', 'confirmation_type',
            'confirmer_user', 'confirmer_business',
            'reference', 'notes', 'proof_image_url',
            'created_at', 'updated_at'
        )
    
    def resolve_confirmer_type(self, info):
        return self.confirmer_type
    
    def resolve_confirmer_display_name(self, info):
        return self.confirmer_display_name

class P2PEscrowType(DjangoObjectType):
    """GraphQL type for P2P escrow records"""
    
    # Add computed field for status display
    status_display = graphene.String()
    
    class Meta:
        model = P2PEscrow
        fields = (
            'id', 'trade', 'escrow_amount', 'token_type',
            'escrow_transaction_hash', 'release_transaction_hash',
            'is_escrowed', 'is_released',
            'release_type', 'release_amount', 'resolved_by_dispute',
            'dispute_resolution', 'escrowed_at', 'released_at',
            'created_at', 'updated_at'
        )
    
    def resolve_status_display(self, info):
        """Return human-readable status"""
        return self.status_display

class P2PDisputeType(DjangoObjectType):
    """GraphQL type for P2P disputes"""
    
    class Meta:
        model = P2PDispute
        fields = (
            'id', 'trade', 'initiator_user', 'initiator_business',
            'reason', 'status', 'priority', 'resolution_type',
            'resolution_amount', 'resolution_notes', 'admin_notes',
            'evidence_urls', 'resolved_by', 'opened_at', 'resolved_at',
            'last_updated'
        )

class P2PTradeType(DjangoObjectType):
    payment_method = graphene.Field(P2PPaymentMethodType)
    # Add computed fields for better frontend integration
    buyer_type = graphene.String()
    seller_type = graphene.String()
    buyer_display_name = graphene.String()
    seller_display_name = graphene.String()
    # Add rating field to check if trade has been rated
    rating = graphene.Field(P2PTradeRatingType)
    has_rating = graphene.Boolean()
    # Add confirmations field
    confirmations = graphene.List(P2PTradeConfirmationType)
    # Add user stats for both parties
    buyer_stats = graphene.Field(P2PUserStatsType)
    seller_stats = graphene.Field(P2PUserStatsType)
    
    # Add escrow field
    escrow = graphene.Field('p2p_exchange.schema.P2PEscrowType')
    
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
            'completed_at', 'created_at', 'updated_at',
            # Country and currency info
            'country_code', 'currency_code',
            # Escrow info
            'escrow'
        )
    
    def resolve_payment_method(self, info):
        """Custom resolver for payment_method to ensure it's properly serialized"""
        if self.payment_method:
            return type('PaymentMethod', (), {
                'id': str(self.payment_method.id),
                'name': self.payment_method.name,
                'display_name': self.payment_method.display_name,
                'icon': self.payment_method.icon,
                'is_active': self.payment_method.is_active,
                'provider_type': self.payment_method.provider_type,
                'requires_phone': self.payment_method.requires_phone,
                'requires_email': self.payment_method.requires_email,
                'requires_account_number': self.payment_method.requires_account_number,
                'country_code': self.payment_method.country_code,
                'bank': self.payment_method.bank
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
    
    def resolve_has_rating(self, info):
        """Returns True if the current user has already rated this trade"""
        try:
            user = info.context.user
            if not user.is_authenticated:
                return False
            
            # Get the active account context from request (set by middleware)
            request = info.context
            active_account_type = getattr(request, 'active_account_type', 'personal')
            active_account_index = getattr(request, 'active_account_index', 0)
            
            print(f"\n[DEBUG] resolve_has_rating for trade {self.id}")
            print(f"  - User: {user.id} ({user.username})")
            print(f"  - Active account: {active_account_type} (index: {active_account_index})")
            print(f"  - Trade buyer_user: {self.buyer_user_id} ({self.buyer_user.username if self.buyer_user else 'None'})")
            print(f"  - Trade seller_user: {self.seller_user_id} ({self.seller_user.username if self.seller_user else 'None'})")
            print(f"  - Trade buyer_business: {self.buyer_business}")
            print(f"  - Trade seller_business: {self.seller_business}")
            
            # Check if current user/business has already rated this trade
            if active_account_type == 'business':
                # Check if this specific business account has rated
                # First, check if the user is part of this trade as a business
                if self.buyer_business and self.buyer_business.accounts.filter(user=user, account_index=active_account_index).exists():
                    # User is the buyer business with this specific account index
                    has_rating = P2PTradeRating.objects.filter(
                        trade=self,
                        rater_business=self.buyer_business
                    ).exists()
                    print(f"  - Buyer business rating exists: {has_rating}")
                    return has_rating
                elif self.seller_business and self.seller_business.accounts.filter(user=user, account_index=active_account_index).exists():
                    # User is the seller business with this specific account index
                    has_rating = P2PTradeRating.objects.filter(
                        trade=self,
                        rater_business=self.seller_business
                    ).exists()
                    print(f"  - Seller business rating exists: {has_rating}")
                    return has_rating
                else:
                    print(f"  - User not part of trade as business")
                    return False
            else:
                # Personal account - check if user has rated
                rating_query = P2PTradeRating.objects.filter(
                    trade=self,
                    rater_user=user
                )
                has_rating = rating_query.exists()
                
                # Debug: Check the actual rating if it exists
                if has_rating:
                    actual_rating = rating_query.first()
                    print(f"  - Personal account rating exists: {has_rating}")
                    print(f"  - Rating ID: {actual_rating.id}")
                    print(f"  - Created at: {actual_rating.created_at}")
                else:
                    print(f"  - Personal account rating exists: {has_rating}")
                    # Check if there are any ratings for this trade at all
                    all_ratings = P2PTradeRating.objects.filter(trade=self)
                    print(f"  - Total ratings for this trade: {all_ratings.count()}")
                    for r in all_ratings:
                        print(f"    - Rating {r.id}: rater_user={r.rater_user}, rater_business={r.rater_business}")
                
                return has_rating
                
        except Exception as e:
            print(f"[DEBUG] hasRating error for trade {self.id}: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    def resolve_confirmations(self, info):
        """Get all confirmations for this trade"""
        return self.confirmations.all().order_by('created_at')
    
    def resolve_buyer_stats(self, info):
        """Get stats for the buyer"""
        print(f"\n[resolve_buyer_stats] Trade {self.id}")
        print(f"  - buyer_user: {self.buyer_user}")
        print(f"  - buyer_business: {self.buyer_business}")
        
        # Check if it's a business buyer
        if self.buyer_business:
            # For business buyers, we need to aggregate stats across all business trades
            completed_trades = P2PTrade.objects.filter(
                models.Q(buyer_business=self.buyer_business) | 
                models.Q(seller_business=self.buyer_business),
                status='COMPLETED'
            ).count()
            
            total_trades = P2PTrade.objects.filter(
                models.Q(buyer_business=self.buyer_business) | 
                models.Q(seller_business=self.buyer_business)
            ).count()
            
            # Get average rating for business
            ratings = P2PTradeRating.objects.filter(
                models.Q(ratee_business=self.buyer_business)
            )
            avg_rating = ratings.aggregate(models.Avg('overall_rating'))['overall_rating__avg'] or 0.0
            
            # Get last activity
            last_trade = P2PTrade.objects.filter(
                models.Q(buyer_business=self.buyer_business) | 
                models.Q(seller_business=self.buyer_business)
            ).order_by('-created_at').first()
            
            stats = P2PUserStatsType(
                total_trades=total_trades,
                completed_trades=completed_trades,
                success_rate=float((completed_trades / total_trades * 100)) if total_trades > 0 else 0.0,
                avg_response_time=15,  # Default 15 minutes
                is_verified=self.buyer_business.is_verified if hasattr(self.buyer_business, 'is_verified') else False,
                last_seen_online=last_trade.created_at if last_trade else None,
                avg_rating=float(avg_rating),
            )
            print(f"  - Buyer business stats: total_trades={total_trades}, completed_trades={completed_trades}")
            return stats
        elif self.buyer_user:
            # For personal buyers
            completed_trades = P2PTrade.objects.filter(
                models.Q(buyer_user=self.buyer_user) | 
                models.Q(seller_user=self.buyer_user),
                status='COMPLETED'
            ).count()
            
            total_trades = P2PTrade.objects.filter(
                models.Q(buyer_user=self.buyer_user) | 
                models.Q(seller_user=self.buyer_user)
            ).count()
            
            # Get average rating for user
            ratings = P2PTradeRating.objects.filter(
                models.Q(ratee_user=self.buyer_user)
            )
            avg_rating = ratings.aggregate(models.Avg('overall_rating'))['overall_rating__avg'] or 0.0
            
            # Get last activity
            last_trade = P2PTrade.objects.filter(
                models.Q(buyer_user=self.buyer_user) | 
                models.Q(seller_user=self.buyer_user)
            ).order_by('-created_at').first()
            
            stats = P2PUserStatsType(
                total_trades=total_trades,
                completed_trades=completed_trades,
                success_rate=float((completed_trades / total_trades * 100)) if total_trades > 0 else 0.0,
                avg_response_time=15,  # Default 15 minutes
                is_verified=self.buyer_user.is_identity_verified if hasattr(self.buyer_user, 'is_identity_verified') else False,
                last_seen_online=last_trade.created_at if last_trade else None,
                avg_rating=float(avg_rating),
            )
            print(f"  - Buyer user stats: total_trades={total_trades}, completed_trades={completed_trades}")
            return stats
        return None
    
    def resolve_seller_stats(self, info):
        """Get stats for the seller"""
        print(f"\n[resolve_seller_stats] Trade {self.id}")
        print(f"  - seller_user: {self.seller_user}")
        print(f"  - seller_business: {self.seller_business}")
        
        # Check if it's a business seller
        if self.seller_business:
            # For business sellers, we need to aggregate stats across all business trades
            completed_trades = P2PTrade.objects.filter(
                models.Q(buyer_business=self.seller_business) | 
                models.Q(seller_business=self.seller_business),
                status='COMPLETED'
            ).count()
            
            total_trades = P2PTrade.objects.filter(
                models.Q(buyer_business=self.seller_business) | 
                models.Q(seller_business=self.seller_business)
            ).count()
            
            # Get average rating for business
            ratings = P2PTradeRating.objects.filter(
                models.Q(ratee_business=self.seller_business)
            )
            avg_rating = ratings.aggregate(models.Avg('overall_rating'))['overall_rating__avg'] or 0.0
            
            # Get last activity
            last_trade = P2PTrade.objects.filter(
                models.Q(buyer_business=self.seller_business) | 
                models.Q(seller_business=self.seller_business)
            ).order_by('-created_at').first()
            
            stats = P2PUserStatsType(
                total_trades=total_trades,
                completed_trades=completed_trades,
                success_rate=float((completed_trades / total_trades * 100)) if total_trades > 0 else 0.0,
                avg_response_time=15,  # Default 15 minutes
                is_verified=self.seller_business.is_verified if hasattr(self.seller_business, 'is_verified') else False,
                last_seen_online=last_trade.created_at if last_trade else None,
                avg_rating=float(avg_rating),
            )
            print(f"  - Seller business stats: total_trades={total_trades}, completed_trades={completed_trades}")
            return stats
        elif self.seller_user:
            # For personal sellers
            completed_trades = P2PTrade.objects.filter(
                models.Q(buyer_user=self.seller_user) | 
                models.Q(seller_user=self.seller_user),
                status='COMPLETED'
            ).count()
            
            total_trades = P2PTrade.objects.filter(
                models.Q(buyer_user=self.seller_user) | 
                models.Q(seller_user=self.seller_user)
            ).count()
            
            # Get average rating for user
            ratings = P2PTradeRating.objects.filter(
                models.Q(ratee_user=self.seller_user)
            )
            avg_rating = ratings.aggregate(models.Avg('overall_rating'))['overall_rating__avg'] or 0.0
            
            # Get last activity
            last_trade = P2PTrade.objects.filter(
                models.Q(buyer_user=self.seller_user) | 
                models.Q(seller_user=self.seller_user)
            ).order_by('-created_at').first()
            
            stats = P2PUserStatsType(
                total_trades=total_trades,
                completed_trades=completed_trades,
                success_rate=float((completed_trades / total_trades * 100)) if total_trades > 0 else 0.0,
                avg_response_time=15,  # Default 15 minutes
                is_verified=self.seller_user.is_identity_verified if hasattr(self.seller_user, 'is_identity_verified') else False,
                last_seen_online=last_trade.created_at if last_trade else None,
                avg_rating=float(avg_rating),
            )
            print(f"  - Seller user stats: total_trades={total_trades}, completed_trades={completed_trades}")
            return stats
        return None


class P2PTradePaginatedType(graphene.ObjectType):
    """Paginated response for P2P trades"""
    trades = graphene.List(P2PTradeType)
    total_count = graphene.Int()
    has_more = graphene.Boolean()
    offset = graphene.Int()
    limit = graphene.Int()
    active_count = graphene.Int()  # Count of non-completed trades

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
    account_id = graphene.String(required=False)  # Optional: specify which account to use

class CreateP2PTradeInput(graphene.InputObjectType):
    offerId = graphene.ID(required=True)
    cryptoAmount = graphene.Decimal(required=True)
    paymentMethodId = graphene.ID(required=True)
    accountId = graphene.String(required=False)  # Optional: specify which account to use

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


class RateP2PTradeInput(graphene.InputObjectType):
    trade_id = graphene.ID(required=True)
    overall_rating = graphene.Int(required=True)
    communication_rating = graphene.Int()
    speed_rating = graphene.Int()
    reliability_rating = graphene.Int()
    comment = graphene.String()
    tags = graphene.List(graphene.String)

class ConfirmP2PTradeStepInput(graphene.InputObjectType):
    trade_id = graphene.ID(required=True)
    confirmation_type = graphene.String(required=True)
    reference = graphene.String()
    notes = graphene.String()
    proof_image_url = graphene.String()

# Mutations
class CreateP2POffer(graphene.Mutation):
    class Arguments:
        input = CreateP2POfferInput(required=True)

    offer = graphene.Field(P2POfferType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    
    @staticmethod
    def _get_currency_for_country(country_code):
        """Get currency code for a given country code"""
        # Country ISO code to currency mapping
        COUNTRY_TO_CURRENCY = {
            # Latin America (Primary focus)
            'VE': 'VES',  # Venezuela - Bolívar
            'AR': 'ARS',  # Argentina - Peso
            'CO': 'COP',  # Colombia - Peso
            'PE': 'PEN',  # Peru - Sol
            'CL': 'CLP',  # Chile - Peso
            'BO': 'BOB',  # Bolivia - Boliviano
            'UY': 'UYU',  # Uruguay - Peso
            'PY': 'PYG',  # Paraguay - Guaraní
            'BR': 'BRL',  # Brazil - Real
            'MX': 'MXN',  # Mexico - Peso
            'EC': 'USD',  # Ecuador - US Dollar (dollarized)
            'PA': 'USD',  # Panama - US Dollar (dollarized)
            'GT': 'GTQ',  # Guatemala - Quetzal
            'HN': 'HNL',  # Honduras - Lempira
            'SV': 'USD',  # El Salvador - US Dollar (dollarized)
            'NI': 'NIO',  # Nicaragua - Córdoba
            'CR': 'CRC',  # Costa Rica - Colón
            'DO': 'DOP',  # Dominican Republic - Peso
            'CU': 'CUP',  # Cuba - Peso
            'JM': 'JMD',  # Jamaica - Dollar
            'TT': 'TTD',  # Trinidad and Tobago - Dollar
            # North America
            'US': 'USD',  # United States - Dollar
            'CA': 'CAD',  # Canada - Dollar
        }
        return COUNTRY_TO_CURRENCY.get(country_code, 'USD')  # Default to USD if unknown

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
            
            # Validate payment method IDs against database records
            payment_methods = []
            for method_id in input.payment_method_ids:
                try:
                    # Look up payment method by database ID
                    payment_method = P2PPaymentMethod.objects.get(
                        id=method_id,
                        country_code=input.country_code,
                        is_active=True
                    )
                    payment_methods.append(payment_method)
                    
                except P2PPaymentMethod.DoesNotExist:
                    # Get available methods count for error message
                    available_count = P2PPaymentMethod.objects.filter(
                        country_code=input.country_code,
                        is_active=True
                    ).count()
                    
                    return CreateP2POffer(
                        offer=None,
                        success=False,
                        errors=[f"ID de método de pago inválido: {method_id}, País: {input.country_code}, métodos disponibles: {available_count}"]
                    )
                except (ValueError, TypeError):
                    return CreateP2POffer(
                        offer=None,
                        success=False,
                        errors=[f"Invalid payment method ID format: {method_id}"]
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
                'currency_code': cls._get_currency_for_country(input.country_code),
                'terms': input.terms or '',
                'response_time_minutes': input.response_time_minutes or 15,
                # Keep old fields for backward compatibility
                'user': user,
            }

            if input.account_id:
                from users.models import Account
                
                # Handle special frontend account ID format (e.g., 'personal_0', 'business_0')
                if isinstance(input.account_id, str) and '_' in input.account_id:
                    account_type, account_index = input.account_id.split('_', 1)
                    account_index = int(account_index)
                    
                    if account_type == 'personal':
                        # Personal offer
                        offer_kwargs['offer_user'] = user
                    elif account_type == 'business':
                        # Find the business account by index
                        try:
                            account = Account.objects.get(
                                user=user, 
                                account_type='business', 
                                account_index=account_index
                            )
                            offer_kwargs['account'] = account
                            
                            if account.business:
                                # Business offer
                                offer_kwargs['offer_business'] = account.business
                            else:
                                return CreateP2POffer(
                                    offer=None,
                                    success=False,
                                    errors=["Business account has no associated business"]
                                )
                        except Account.DoesNotExist:
                            return CreateP2POffer(
                                offer=None,
                                success=False,
                                errors=["Business account not found or access denied"]
                            )
                else:
                    # Fallback: try to use account_id as a direct database ID
                    try:
                        account = Account.objects.get(id=input.account_id, user=user)
                        offer_kwargs['account'] = account
                        
                        if account.account_type == 'business' and account.business:
                            # Business offer
                            offer_kwargs['offer_business'] = account.business
                        else:
                            # Personal offer
                            offer_kwargs['offer_user'] = user
                    except (Account.DoesNotExist, ValueError):
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
    

class UpdateP2POffer(graphene.Mutation):
    class Arguments:
        offer_id = graphene.ID(required=True)
        status = graphene.String()  # ACTIVE, PAUSED, CANCELLED
        rate = graphene.Float()
        min_amount = graphene.Float()
        max_amount = graphene.Float()
        available_amount = graphene.Float()
        payment_method_ids = graphene.List(graphene.ID)
        terms = graphene.String()
    
    offer = graphene.Field(P2POfferType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    
    @classmethod
    def mutate(cls, root, info, offer_id, **kwargs):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return UpdateP2POffer(
                offer=None,
                success=False,
                errors=["Authentication required"]
            )
        
        try:
            # Get the offer and check ownership
            offer = P2POffer.objects.filter(
                models.Q(id=offer_id) & (
                    models.Q(offer_user=user) | 
                    models.Q(offer_business__accounts__user=user)
                )
            ).distinct().first()
            
            if not offer:
                return UpdateP2POffer(
                    offer=None,
                    success=False,
                    errors=["Offer not found or access denied"]
                )
            
            # Update allowed fields
            if 'status' in kwargs and kwargs['status']:
                if kwargs['status'] in ['ACTIVE', 'PAUSED', 'CANCELLED']:
                    offer.status = kwargs['status']
                else:
                    return UpdateP2POffer(
                        offer=None,
                        success=False,
                        errors=["Invalid status. Must be ACTIVE, PAUSED, or CANCELLED"]
                    )
            
            if 'rate' in kwargs and kwargs['rate'] is not None:
                offer.rate = kwargs['rate']
            
            if 'min_amount' in kwargs and kwargs['min_amount'] is not None:
                offer.min_amount = kwargs['min_amount']
            
            if 'max_amount' in kwargs and kwargs['max_amount'] is not None:
                offer.max_amount = kwargs['max_amount']
            
            if 'available_amount' in kwargs and kwargs['available_amount'] is not None:
                offer.available_amount = kwargs['available_amount']
            
            if 'terms' in kwargs and kwargs['terms'] is not None:
                offer.terms = kwargs['terms']
            
            # Update payment methods if provided
            if 'payment_method_ids' in kwargs and kwargs['payment_method_ids'] is not None:
                from .models import P2PPaymentMethod
                payment_methods = P2PPaymentMethod.objects.filter(
                    id__in=kwargs['payment_method_ids'],
                    is_active=True
                )
                offer.payment_methods.set(payment_methods)
            
            offer.save()
            
            return UpdateP2POffer(
                offer=offer,
                success=True,
                errors=None
            )
            
        except Exception as e:
            return UpdateP2POffer(
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
    
    @staticmethod
    def _get_currency_for_country(country_code):
        """Get currency code for a given country code"""
        # Country ISO code to currency mapping
        COUNTRY_TO_CURRENCY = {
            # Latin America (Primary focus)
            'VE': 'VES',  # Venezuela - Bolívar
            'AR': 'ARS',  # Argentina - Peso
            'CO': 'COP',  # Colombia - Peso
            'PE': 'PEN',  # Peru - Sol
            'CL': 'CLP',  # Chile - Peso
            'BO': 'BOB',  # Bolivia - Boliviano
            'UY': 'UYU',  # Uruguay - Peso
            'PY': 'PYG',  # Paraguay - Guaraní
            'BR': 'BRL',  # Brazil - Real
            'MX': 'MXN',  # Mexico - Peso
            'EC': 'USD',  # Ecuador - US Dollar (dollarized)
            'PA': 'USD',  # Panama - US Dollar (dollarized)
            'GT': 'GTQ',  # Guatemala - Quetzal
            'HN': 'HNL',  # Honduras - Lempira
            'SV': 'USD',  # El Salvador - US Dollar (dollarized)
            'NI': 'NIO',  # Nicaragua - Córdoba
            'CR': 'CRC',  # Costa Rica - Colón
            'DO': 'DOP',  # Dominican Republic - Peso
            'CU': 'CUP',  # Cuba - Peso
            'JM': 'JMD',  # Jamaica - Dollar
            'TT': 'TTD',  # Trinidad and Tobago - Dollar
            # North America
            'US': 'USD',  # United States - Dollar
            'CA': 'CAD',  # Canada - Dollar
        }
        return COUNTRY_TO_CURRENCY.get(country_code, 'USD')  # Default to USD if unknown

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

            # Validate payment method - frontend sends actual database IDs
            try:
                # Check if the payment method belongs to the offer
                payment_method = offer.payment_methods.filter(
                    id=input.paymentMethodId,
                    is_active=True
                ).first()
                
                if not payment_method:
                    # List available payment methods for debugging
                    available_methods = list(offer.payment_methods.filter(is_active=True).values_list('id', 'display_name'))
                    return CreateP2PTrade(
                        trade=None,
                        success=False,
                        errors=[f"El método de pago seleccionado no está disponible para esta oferta. Métodos disponibles: {available_methods}"]
                    )
                
            except Exception as e:
                return CreateP2PTrade(
                    trade=None,
                    success=False,
                    errors=[f"Error al validar el método de pago: {str(e)}"]
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
                
                # Handle special frontend account ID format (e.g., 'personal_0', 'business_0')
                if isinstance(input.accountId, str) and '_' in input.accountId:
                    account_type, account_index = input.accountId.split('_', 1)
                    account_index = int(account_index)
                    
                    if account_type == 'personal':
                        # Keep default personal settings
                        user_entity = user
                        user_entity_type = 'user'
                        user_account = None
                    elif account_type == 'business':
                        # Find the business account by index
                        try:
                            user_account = Account.objects.get(
                                user=user, 
                                account_type='business', 
                                account_index=account_index
                            )
                            if user_account.business:
                                user_entity = user_account.business
                                user_entity_type = 'business'
                            else:
                                return CreateP2PTrade(
                                    trade=None,
                                    success=False,
                                    errors=["Business account has no associated business"]
                                )
                        except Account.DoesNotExist:
                            return CreateP2PTrade(
                                trade=None,
                                success=False,
                                errors=["Business account not found or access denied"]
                            )
                else:
                    # Fallback: try to use accountId as a direct database ID
                    try:
                        user_account = Account.objects.get(id=input.accountId, user=user)
                        if user_account.account_type == 'business' and user_account.business:
                            user_entity = user_account.business
                            user_entity_type = 'business'
                    except (Account.DoesNotExist, ValueError):
                        return CreateP2PTrade(
                            trade=None,
                            success=False,
                            errors=["Account not found or access denied"]
                        )
            
            # Check offer's account type
            if offer.account and offer.account.account_type == 'business' and offer.account.business:
                offer_entity = offer.account.business
                offer_entity_type = 'business'
            
            # Validate user can't trade with themselves (after entity determination)
            # Personal account can trade with business account even if same underlying user
            if user_entity_type == offer_entity_type:
                if user_entity_type == 'user' and offer_entity == user_entity:
                    return CreateP2PTrade(
                        trade=None,
                        success=False,
                        errors=["No puedes comerciar con tu propia oferta"]
                    )
                elif user_entity_type == 'business' and offer_entity == user_entity:
                    return CreateP2PTrade(
                        trade=None,
                        success=False,
                        errors=["No puedes comerciar con tu propia oferta"]
                    )

            # Determine buyer and seller entities based on offer type
            trade_kwargs = {
                'offer': offer,
                'crypto_amount': input.cryptoAmount,
                'fiat_amount': fiat_amount,
                'rate_used': offer.rate,
                'payment_method': payment_method,
                'expires_at': timezone.now() + timedelta(minutes=30),
                # Country and currency from the offer
                'country_code': offer.country_code,
                'currency_code': offer.currency_code if offer.currency_code else self._get_currency_for_country(offer.country_code),
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
            
            # Create escrow record for this trade
            from .models import P2PEscrow
            escrow = P2PEscrow.objects.create(
                trade=trade,
                escrow_amount=input.cryptoAmount,
                token_type=offer.token_type,
                is_escrowed=False,  # Will be set to True when blockchain confirms escrow
                is_released=False
            )
            
            # TODO: In production, initiate blockchain escrow transaction here
            # and update is_escrowed=True when blockchain confirms
            # For now, we'll simulate this by setting it to True immediately
            escrow.is_escrowed = True
            escrow.escrowed_at = timezone.now()
            escrow.escrow_transaction_hash = f"simulated_tx_hash_{trade.id}"
            escrow.save()

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
            # Get trade and verify user is part of it using new fields
            trade = P2PTrade.objects.filter(
                id=input.trade_id
            ).filter(
                models.Q(buyer_user=user) | 
                models.Q(seller_user=user) |
                models.Q(buyer_business__accounts__user=user) |
                models.Q(seller_business__accounts__user=user)
            ).distinct().first()
            
            if not trade:
                return UpdateP2PTradeStatus(
                    trade=None,
                    success=False,
                    errors=["Trade not found or access denied"]
                )

            # Validate status transition
            valid_statuses = [choice[0] for choice in P2PTrade.STATUS_CHOICES]
            if input.status not in valid_statuses:
                return UpdateP2PTradeStatus(
                    trade=None,
                    success=False,
                    errors=["Invalid status"]
                )

            # Get active account context to determine confirmer
            request = info.context
            active_account_type = getattr(request, 'active_account_type', 'personal')
            active_account_index = getattr(request, 'active_account_index', 0)
            
            # Determine if user is buyer or seller
            is_buyer = False
            is_seller = False
            confirmer_user = None
            confirmer_business = None
            
            if active_account_type == 'business':
                # Check if user is buyer business
                if trade.buyer_business and trade.buyer_business.accounts.filter(user=user, account_index=active_account_index).exists():
                    is_buyer = True
                    confirmer_business = trade.buyer_business
                # Check if user is seller business
                elif trade.seller_business and trade.seller_business.accounts.filter(user=user, account_index=active_account_index).exists():
                    is_seller = True
                    confirmer_business = trade.seller_business
            else:
                # Personal account
                is_buyer = trade.buyer_user == user
                is_seller = trade.seller_user == user
                confirmer_user = user

            # Update trade
            trade.status = input.status
            if input.payment_reference:
                trade.payment_reference = input.payment_reference
            if input.payment_notes:
                trade.payment_notes = input.payment_notes

            if input.status == 'COMPLETED':
                trade.completed_at = timezone.now()

            trade.save()
            
            # Create confirmation records for specific status changes
            confirmation_type = None
            if input.status == 'PAYMENT_SENT' and is_buyer:
                confirmation_type = 'PAYMENT_SENT'
            elif input.status == 'PAYMENT_CONFIRMED' and is_seller:
                confirmation_type = 'PAYMENT_RECEIVED'
            elif input.status == 'CRYPTO_RELEASED' and is_seller:
                confirmation_type = 'CRYPTO_RELEASED'
            elif input.status == 'COMPLETED' and is_buyer:
                confirmation_type = 'CRYPTO_RECEIVED'
            
            if confirmation_type:
                # Check if confirmation already exists
                existing_confirmation = P2PTradeConfirmation.objects.filter(
                    trade=trade,
                    confirmation_type=confirmation_type
                )
                
                if confirmer_business:
                    existing_confirmation = existing_confirmation.filter(confirmer_business=confirmer_business)
                else:
                    existing_confirmation = existing_confirmation.filter(confirmer_user=confirmer_user)
                
                # Create confirmation if it doesn't exist
                if not existing_confirmation.exists():
                    confirmation_data = {
                        'trade': trade,
                        'confirmation_type': confirmation_type,
                        'reference': input.payment_reference or '',
                        'notes': input.payment_notes or ''
                    }
                    
                    if confirmer_business:
                        confirmation_data['confirmer_business'] = confirmer_business
                    else:
                        confirmation_data['confirmer_user'] = confirmer_user
                    
                    P2PTradeConfirmation.objects.create(**confirmation_data)

            # Broadcast the status update via WebSocket
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            
            channel_layer = get_channel_layer()
            room_group_name = f'trade_chat_{trade.id}'
            
            # Send trade status update to all connected clients
            broadcast_data = {
                'type': 'trade_status_update',
                'status': input.status,
                'updated_by': str(user.id),
                'payment_reference': input.payment_reference or '',
                'payment_notes': input.payment_notes or '',
            }
            
            async_to_sync(channel_layer.group_send)(
                room_group_name,
                broadcast_data
            )

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
            # Get trade and verify user is part of it using new fields
            trade = P2PTrade.objects.filter(
                id=input.trade_id
            ).filter(
                models.Q(buyer_user=user) | 
                models.Q(seller_user=user) |
                models.Q(buyer_business__accounts__user=user) |
                models.Q(seller_business__accounts__user=user)
            ).distinct().first()
            
            if not trade:
                return SendP2PMessage(
                    message=None,
                    success=False,
                    errors=["Trade not found or access denied"]
                )

            # Get the active account context from the request
            request = info.context
            active_account_type = getattr(request, 'active_account_type', 'personal')
            active_account_index = getattr(request, 'active_account_index', 0)
            
            print(f"SendP2PMessage - Active account context: type={active_account_type}, index={active_account_index}")
            print(f"SendP2PMessage - Trade participants: buyer_user={trade.buyer_user_id}, seller_user={trade.seller_user_id}, buyer_business={trade.buyer_business_id}, seller_business={trade.seller_business_id}")

            # Determine sender entity based on the active account context
            message_kwargs = {
                'trade': trade,
                'content': input.content,
                'message_type': input.message_type or 'TEXT',
                'attachment_url': input.attachment_url or '',
                'attachment_type': input.attachment_type or '',
                # Keep old field for backward compatibility
                'sender': user,
            }
            
            # Determine which account is sending the message based on active account context
            if active_account_type == 'business':
                # User is sending as a business - find which business they're using
                if trade.buyer_business and trade.buyer_business.accounts.filter(user=user, account_index=active_account_index).exists():
                    message_kwargs['sender_business'] = trade.buyer_business
                    print(f"SendP2PMessage - Sending as buyer business: {trade.buyer_business.name}")
                elif trade.seller_business and trade.seller_business.accounts.filter(user=user, account_index=active_account_index).exists():
                    message_kwargs['sender_business'] = trade.seller_business
                    print(f"SendP2PMessage - Sending as seller business: {trade.seller_business.name}")
                else:
                    # Fallback to personal if business not found
                    message_kwargs['sender_user'] = user
                    print(f"SendP2PMessage - Business account not found, falling back to personal")
            else:
                # User is sending as personal account
                message_kwargs['sender_user'] = user
                print(f"SendP2PMessage - Sending as personal user: {user.username}")

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


class RateP2PTrade(graphene.Mutation):
    class Arguments:
        input = RateP2PTradeInput(required=True)
    
    rating = graphene.Field(P2PTradeRatingType)
    trade = graphene.Field(P2PTradeType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    
    @classmethod
    def mutate(cls, root, info, input):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return RateP2PTrade(
                rating=None,
                trade=None,
                success=False,
                errors=["Authentication required"]
            )
        
        try:
            # Get trade and verify user is part of it
            trade = P2PTrade.objects.filter(
                id=input.trade_id
            ).filter(
                models.Q(buyer_user=user) | 
                models.Q(seller_user=user) |
                models.Q(buyer_business__accounts__user=user) |
                models.Q(seller_business__accounts__user=user)
            ).distinct().first()
            
            if not trade:
                return RateP2PTrade(
                    rating=None,
                    trade=None,
                    success=False,
                    errors=["Trade not found or access denied"]
                )
            
            # Check if trade is completed
            if trade.status not in ['PAYMENT_CONFIRMED', 'CRYPTO_RELEASED', 'COMPLETED']:
                return RateP2PTrade(
                    rating=None,
                    trade=None,
                    success=False,
                    errors=["Trade must be completed before rating"]
                )
            
            # Get the active account context
            request = info.context
            active_account_type = getattr(request, 'active_account_type', 'personal')
            active_account_index = getattr(request, 'active_account_index', 0)
            
            # Check if already rated by current user IN THEIR CURRENT CONTEXT
            if active_account_type == 'business':
                # Check if this specific business account has rated
                # First find which business the user is acting as
                from users.models import Account
                active_account = Account.objects.filter(
                    user=user,
                    account_type='business',
                    account_index=active_account_index
                ).first()
                
                if active_account and active_account.business:
                    existing_rating = trade.ratings.filter(
                        rater_business=active_account.business
                    ).first()
                else:
                    existing_rating = None
            else:
                # Personal account - check only personal ratings
                existing_rating = trade.ratings.filter(
                    rater_user=user
                ).first()
            
            if existing_rating:
                print(f"\n[RateP2PTrade] User already rated this trade")
                print(f"  - Existing rating ID: {existing_rating.id}")
                print(f"  - Rater User: {existing_rating.rater_user}")
                print(f"  - Rater Business: {existing_rating.rater_business}")
                return RateP2PTrade(
                    rating=None,
                    trade=None,
                    success=False,
                    errors=["You have already rated this trade"]
                )
            
            # Validate ratings
            if not (1 <= input.overall_rating <= 5):
                return RateP2PTrade(
                    rating=None,
                    trade=None,
                    success=False,
                    errors=["Overall rating must be between 1 and 5"]
                )
            
            # Determine who is rating and who is being rated
            rating_kwargs = {
                'trade': trade,
                'overall_rating': input.overall_rating,
                'communication_rating': input.communication_rating,
                'speed_rating': input.speed_rating,
                'reliability_rating': input.reliability_rating,
                'comment': input.comment or '',
                'tags': input.tags or []
            }
            
            # Determine rater and ratee based on who the user is in the trade
            is_buyer = False
            is_seller = False
            
            if active_account_type == 'business':
                # Check if user is acting as a business
                if trade.buyer_business and trade.buyer_business.accounts.filter(user=user, account_index=active_account_index).exists():
                    rating_kwargs['rater_business'] = trade.buyer_business
                    is_buyer = True
                elif trade.seller_business and trade.seller_business.accounts.filter(user=user, account_index=active_account_index).exists():
                    rating_kwargs['rater_business'] = trade.seller_business
                    is_seller = True
            else:
                # User is acting as personal account
                if trade.buyer_user == user:
                    rating_kwargs['rater_user'] = user
                    is_buyer = True
                elif trade.seller_user == user:
                    rating_kwargs['rater_user'] = user
                    is_seller = True
            
            # Set ratee based on who is rating
            if is_buyer:
                # Buyer is rating the seller
                if trade.seller_business:
                    rating_kwargs['ratee_business'] = trade.seller_business
                else:
                    rating_kwargs['ratee_user'] = trade.seller_user
            elif is_seller:
                # Seller is rating the buyer
                if trade.buyer_business:
                    rating_kwargs['ratee_business'] = trade.buyer_business
                else:
                    rating_kwargs['ratee_user'] = trade.buyer_user
            else:
                return RateP2PTrade(
                    rating=None,
                    trade=None,
                    success=False,
                    errors=["You are not part of this trade"]
                )
            
            # Create the rating
            rating = P2PTradeRating.objects.create(**rating_kwargs)
            
            print(f"\n[RateP2PTrade] Rating created successfully")
            print(f"  - Trade ID: {trade.id}")
            print(f"  - Rating ID: {rating.id}")
            print(f"  - Rater User: {rating.rater_user}")
            print(f"  - Rater Business: {rating.rater_business}")
            print(f"  - Ratee User: {rating.ratee_user}")
            print(f"  - Ratee Business: {rating.ratee_business}")
            print(f"  - Overall Rating: {rating.overall_rating}")
            
            # Update trade status to COMPLETED if not already
            if trade.status in ['PAYMENT_CONFIRMED', 'CRYPTO_RELEASED']:
                old_status = trade.status
                trade.status = 'COMPLETED'
                trade.completed_at = timezone.now()
                trade.save()
                print(f"  - Trade status updated from {old_status} to COMPLETED")
            else:
                print(f"  - Trade status remains: {trade.status}")
            
            # Update user stats for the ratee
            ratee = rating.ratee_user or rating.ratee_business
            if ratee:
                # Get or create stats for the ratee
                if rating.ratee_business:
                    stats, created = P2PUserStats.objects.get_or_create(
                        stats_business=rating.ratee_business,
                        defaults={'total_trades': 0, 'completed_trades': 0}
                    )
                else:
                    stats, created = P2PUserStats.objects.get_or_create(
                        stats_user=rating.ratee_user,
                        defaults={'total_trades': 0, 'completed_trades': 0}
                    )
                
                # Update average rating
                all_ratings = P2PTradeRating.objects.filter(
                    models.Q(ratee_user=rating.ratee_user) | 
                    models.Q(ratee_business=rating.ratee_business)
                )
                avg_rating = all_ratings.aggregate(models.Avg('overall_rating'))['overall_rating__avg']
                if avg_rating:
                    stats.avg_rating = avg_rating  # Store the actual average rating (1-5 scale)
                    stats.save()
            
            return RateP2PTrade(
                rating=rating,
                trade=trade,
                success=True,
                errors=None
            )
            
        except Exception as e:
            return RateP2PTrade(
                rating=None,
                trade=None,
                success=False,
                errors=[str(e)]
            )

class DisputeP2PTrade(graphene.Mutation):
    class Arguments:
        trade_id = graphene.ID(required=True)
        reason = graphene.String(required=True)
        
    trade = graphene.Field(P2PTradeType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    
    @classmethod
    def mutate(cls, root, info, trade_id, reason):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return DisputeP2PTrade(
                trade=None,
                success=False,
                errors=["Authentication required"]
            )
        
        try:
            # Get trade and verify user is part of it
            trade = P2PTrade.objects.filter(
                id=trade_id
            ).filter(
                models.Q(buyer_user=user) | 
                models.Q(seller_user=user) |
                models.Q(buyer_business__accounts__user=user) |
                models.Q(seller_business__accounts__user=user)
            ).distinct().first()
            
            if not trade:
                return DisputeP2PTrade(
                    trade=None,
                    success=False,
                    errors=["Trade not found or access denied"]
                )
            
            # Check if trade can be disputed
            if trade.status in ['COMPLETED', 'CANCELLED', 'EXPIRED']:
                return DisputeP2PTrade(
                    trade=None,
                    success=False,
                    errors=[f"Cannot dispute a trade with status: {trade.status}"]
                )
            
            # Check if already disputed
            if trade.status == 'DISPUTED':
                return DisputeP2PTrade(
                    trade=trade,
                    success=False,
                    errors=["Trade is already disputed"]
                )
            
            # Validate reason
            if not reason or len(reason.strip()) < 10:
                return DisputeP2PTrade(
                    trade=None,
                    success=False,
                    errors=["Please provide a detailed reason for the dispute (minimum 10 characters)"]
                )
            
            # Update trade status to disputed
            from django.utils import timezone
            trade.status = 'DISPUTED'
            trade.save()
            
            # Create detailed dispute record
            from .models import P2PDispute
            
            # Determine if initiator is user or business based on active account
            request = info.context
            active_account_type = getattr(request, 'active_account_type', 'personal')
            active_account_index = getattr(request, 'active_account_index', 0)
            
            dispute_kwargs = {
                'trade': trade,
                'reason': reason.strip(),
                'priority': 2  # Default to medium priority
            }
            
            # Determine which account is initiating the dispute
            if active_account_type == 'business':
                # Check if user is acting as buyer business or seller business
                if trade.buyer_business and trade.buyer_business.accounts.filter(user=user, account_index=active_account_index).exists():
                    dispute_kwargs['initiator_business'] = trade.buyer_business
                elif trade.seller_business and trade.seller_business.accounts.filter(user=user, account_index=active_account_index).exists():
                    dispute_kwargs['initiator_business'] = trade.seller_business
                else:
                    # Fallback to user if business not found
                    dispute_kwargs['initiator_user'] = user
            else:
                # User is disputing as personal account
                dispute_kwargs['initiator_user'] = user
            
            P2PDispute.objects.create(**dispute_kwargs)
            
            # Send system message about dispute
            P2PMessage.objects.create(
                trade=trade,
                message_type='SYSTEM',
                content=f"Trade disputed: {reason}"
            )
            
            # TODO: Send notification to admin and other party
            
            return DisputeP2PTrade(
                trade=trade,
                success=True,
                errors=[]
            )
            
        except Exception as e:
            return DisputeP2PTrade(
                trade=None,
                success=False,
                errors=[str(e)]
            )

class ConfirmP2PTradeStep(graphene.Mutation):
    class Arguments:
        input = ConfirmP2PTradeStepInput(required=True)
    
    confirmation = graphene.Field(P2PTradeConfirmationType)
    trade = graphene.Field(P2PTradeType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    
    @classmethod
    def mutate(cls, root, info, input):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return ConfirmP2PTradeStep(
                confirmation=None,
                trade=None,
                success=False,
                errors=["Authentication required"]
            )
        
        try:
            # Get trade and verify user is part of it
            trade = P2PTrade.objects.filter(
                id=input.trade_id
            ).filter(
                models.Q(buyer_user=user) | 
                models.Q(seller_user=user) |
                models.Q(buyer_business__accounts__user=user) |
                models.Q(seller_business__accounts__user=user)
            ).distinct().first()
            
            if not trade:
                return ConfirmP2PTradeStep(
                    confirmation=None,
                    trade=None,
                    success=False,
                    errors=["Trade not found or access denied"]
                )
            
            # Get active account context
            request = info.context
            active_account_type = getattr(request, 'active_account_type', 'personal')
            active_account_index = getattr(request, 'active_account_index', 0)
            
            # Determine if user is buyer or seller
            is_buyer = False
            is_seller = False
            
            if active_account_type == 'business':
                # Check if user is buyer business
                if trade.buyer_business and trade.buyer_business.accounts.filter(user=user, account_index=active_account_index).exists():
                    is_buyer = True
                # Check if user is seller business
                elif trade.seller_business and trade.seller_business.accounts.filter(user=user, account_index=active_account_index).exists():
                    is_seller = True
            else:
                # Personal account
                is_buyer = trade.buyer_user == user
                is_seller = trade.seller_user == user
            
            # Validate confirmation type based on role
            confirmation_type = input.confirmation_type
            
            if confirmation_type == 'PAYMENT_SENT' and not is_buyer:
                return ConfirmP2PTradeStep(
                    confirmation=None,
                    trade=None,
                    success=False,
                    errors=["Only buyer can confirm payment sent"]
                )
            elif confirmation_type == 'PAYMENT_RECEIVED' and not is_seller:
                return ConfirmP2PTradeStep(
                    confirmation=None,
                    trade=None,
                    success=False,
                    errors=["Only seller can confirm payment received"]
                )
            elif confirmation_type == 'CRYPTO_RELEASED' and not is_seller:
                return ConfirmP2PTradeStep(
                    confirmation=None,
                    trade=None,
                    success=False,
                    errors=["Only seller can release crypto"]
                )
            elif confirmation_type == 'CRYPTO_RECEIVED' and not is_buyer:
                return ConfirmP2PTradeStep(
                    confirmation=None,
                    trade=None,
                    success=False,
                    errors=["Only buyer can confirm crypto received"]
                )
            
            # Prepare confirmation data
            confirmation_data = {
                'trade': trade,
                'confirmation_type': confirmation_type,
                'reference': input.reference or '',
                'notes': input.notes or '',
                'proof_image_url': input.proof_image_url or ''
            }
            
            # Set confirmer based on account type
            if active_account_type == 'business':
                if is_buyer:
                    confirmation_data['confirmer_business'] = trade.buyer_business
                elif is_seller:
                    confirmation_data['confirmer_business'] = trade.seller_business
            else:
                confirmation_data['confirmer_user'] = user
            
            # Check if already confirmed
            existing_confirmation = P2PTradeConfirmation.objects.filter(
                trade=trade,
                confirmation_type=confirmation_type
            )
            
            if active_account_type == 'business':
                if is_buyer:
                    existing_confirmation = existing_confirmation.filter(confirmer_business=trade.buyer_business)
                elif is_seller:
                    existing_confirmation = existing_confirmation.filter(confirmer_business=trade.seller_business)
            else:
                existing_confirmation = existing_confirmation.filter(confirmer_user=user)
            
            if existing_confirmation.exists():
                return ConfirmP2PTradeStep(
                    confirmation=None,
                    trade=None,
                    success=False,
                    errors=["This step has already been confirmed"]
                )
            
            # Create confirmation
            confirmation = P2PTradeConfirmation.objects.create(**confirmation_data)
            
            # Update trade status based on confirmation type
            status_updated = False
            if confirmation_type == 'PAYMENT_SENT':
                if trade.status == 'PAYMENT_PENDING':
                    trade.status = 'PAYMENT_SENT'
                    status_updated = True
            elif confirmation_type == 'PAYMENT_RECEIVED':
                if trade.status == 'PAYMENT_SENT':
                    trade.status = 'PAYMENT_CONFIRMED'
                    status_updated = True
                    
                    # Note: is_escrowed should be set to True when blockchain confirms escrow
                    # This would typically happen async after trade creation
                    # For now, we're simulating it here, but in production this would be
                    # set by a webhook or polling service checking blockchain status
                        
            elif confirmation_type == 'CRYPTO_RELEASED':
                # This is now handled by PAYMENT_RECEIVED
                # Keep for backward compatibility but it won't be used in new flow
                if trade.status == 'PAYMENT_CONFIRMED':
                    trade.status = 'CRYPTO_RELEASED'
                    status_updated = True
                    
                    # Update escrow status when crypto is released
                    if hasattr(trade, 'escrow'):
                        escrow = trade.escrow
                        escrow.is_released = True
                        escrow.released_at = timezone.now()
                        escrow.save()
                        
            elif confirmation_type == 'CRYPTO_RECEIVED':
                if trade.status == 'CRYPTO_RELEASED':
                    trade.status = 'COMPLETED'
                    trade.completed_at = timezone.now()
                    status_updated = True
            
            if status_updated:
                trade.save()
                
                # Send WebSocket notification
                channel_layer = get_channel_layer()
                message = {
                    'tradeId': str(trade.id),
                    'status': trade.status,
                    'updatedBy': user.id,
                    'trade': {
                        'id': str(trade.id),
                        'status': trade.status,
                        'cryptoAmount': str(trade.crypto_amount),
                        'fiatAmount': str(trade.fiat_amount),
                        'rateUsed': str(trade.rate_used)
                    }
                }
                
                from asgiref.sync import async_to_sync
                async_to_sync(channel_layer.group_send)(
                    f'trade_{trade.id}',
                    {
                        'type': 'trade_status_update',
                        'message': message
                    }
                )
            
            return ConfirmP2PTradeStep(
                confirmation=confirmation,
                trade=trade,
                success=True,
                errors=None
            )
            
        except Exception as e:
            return ConfirmP2PTradeStep(
                confirmation=None,
                trade=None,
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
        country_code=graphene.String(),
        favorites_only=graphene.Boolean()
    )
    p2p_offer = graphene.Field(P2POfferType, id=graphene.ID(required=True))
    my_p2p_offers = graphene.List(P2POfferType, account_id=graphene.String())
    my_p2p_trades = graphene.Field(
        P2PTradePaginatedType, 
        account_id=graphene.String(),
        offset=graphene.Int(default_value=0),
        limit=graphene.Int(default_value=10)
    )
    p2p_trade = graphene.Field(P2PTradeType, id=graphene.ID(required=True))
    p2p_trade_messages = graphene.List(P2PMessageType, trade_id=graphene.ID(required=True))
    p2p_payment_methods = graphene.List(P2PPaymentMethodType, country_code=graphene.String())

    def resolve_p2p_offers(self, info, exchange_type=None, token_type=None, payment_method=None, country_code=None, favorites_only=False):
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
        
        # Filter by favorites if requested
        if favorites_only:
            user = getattr(info.context, 'user', None)
            if user and getattr(user, 'is_authenticated', False):
                from django.db.models import Q
                from .models import P2PFavoriteTrader
                
                # Get the active account context from the request
                request = info.context
                active_account_type = getattr(request, 'active_account_type', 'personal')
                active_account_index = getattr(request, 'active_account_index', 0)
                
                # Determine favoriter_business if acting as business account
                favoriter_business = None
                if active_account_type == 'business':
                    from users.models import Account
                    active_account = Account.objects.filter(
                        user=user,
                        account_type='business',
                        account_index=active_account_index
                    ).first()
                    
                    if active_account and active_account.business:
                        favoriter_business = active_account.business
                
                # Get all favorite traders for this user in the current account context
                if favoriter_business:
                    favorite_users = P2PFavoriteTrader.objects.filter(
                        user=user,
                        favoriter_business=favoriter_business
                    ).values_list('favorite_user_id', 'favorite_business_id')
                else:
                    favorite_users = P2PFavoriteTrader.objects.filter(
                        user=user,
                        favoriter_business__isnull=True
                    ).values_list('favorite_user_id', 'favorite_business_id')
                
                # Build query for favorite offers
                favorite_q = Q()
                for fav_user_id, fav_business_id in favorite_users:
                    if fav_user_id:
                        favorite_q |= Q(offer_user_id=fav_user_id)
                    if fav_business_id:
                        favorite_q |= Q(offer_business_id=fav_business_id)
                
                # Also include legacy offers from favorite users
                # BUT exclude offers that have a business as primary creator
                favorite_user_ids = [u[0] for u in favorite_users if u[0]]
                if favorite_user_ids:
                    favorite_q |= Q(user_id__in=favorite_user_ids, offer_business__isnull=True)
                
                if favorite_q:
                    queryset = queryset.filter(favorite_q)
                else:
                    # No favorites, return empty
                    return []
        
        return queryset.order_by('-created_at')

    def resolve_p2p_offer(self, info, id):
        try:
            return P2POffer.objects.get(id=id)
        except P2POffer.DoesNotExist:
            return None

    def resolve_my_p2p_offers(self, info, account_id=None):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        
        from django.db.models import Q
        from users.models import Account, Business
        
        if account_id:
            # Handle special frontend account ID format (e.g., 'personal_0', 'business_0')
            if isinstance(account_id, str) and '_' in account_id:
                account_type, account_index = account_id.split('_', 1)
                account_index = int(account_index)
                
                if account_type == 'personal':
                    # Return only personal offers for this user
                    return P2POffer.objects.filter(
                        Q(offer_user=user) | Q(user=user)  # Include legacy offers
                    ).exclude(
                        offer_business__isnull=False  # Exclude business offers
                    ).order_by('-created_at')
                elif account_type == 'business':
                    # Find the business account by index
                    try:
                        account = Account.objects.get(
                            user=user, 
                            account_type='business', 
                            account_index=account_index
                        )
                        if account.business:
                            # Return only business offers for this specific business
                            return P2POffer.objects.filter(
                                offer_business=account.business
                            ).order_by('-created_at')
                    except Account.DoesNotExist:
                        return []
            else:
                # Fallback: try to use account_id as a direct database ID
                try:
                    account = Account.objects.get(id=account_id, user=user)
                    
                    if account.account_type == 'business' and account.business:
                        # Return only business offers for this specific business
                        return P2POffer.objects.filter(
                            offer_business=account.business
                        ).order_by('-created_at')
                    else:
                        # Return only personal offers for this user
                        return P2POffer.objects.filter(
                            Q(offer_user=user) | Q(user=user)  # Include legacy offers
                        ).exclude(
                            offer_business__isnull=False  # Exclude business offers
                        ).order_by('-created_at')
                        
                except (Account.DoesNotExist, ValueError):
                    return []
            
            return []
        else:
            # Fallback: return all user's offers if no account specified
            user_businesses = Business.objects.filter(user=user)
            query = Q(offer_user=user) | Q(user=user)
            if user_businesses.exists():
                query |= Q(offer_business__in=user_businesses)
            return P2POffer.objects.filter(query).order_by('-created_at')

    def resolve_my_p2p_trades(self, info, account_id=None, offset=0, limit=10):
        try:
            user = getattr(info.context, 'user', None)
            if not (user and getattr(user, 'is_authenticated', False)):
                return P2PTradePaginatedType(
                    trades=[],
                    total_count=0,
                    has_more=False,
                    offset=offset,
                    limit=limit,
                    active_count=0
                )
            
            print(f"[P2P] resolve_my_p2p_trades - account_id: {account_id}, user: {user.username if user else 'None'}")
            
            if account_id:
                # Handle special frontend account ID format (e.g., 'personal_0', 'business_0')
                print(f"[P2P] Processing account_id: '{account_id}' for user: {user.username}")
                
                if isinstance(account_id, str) and '_' in account_id:
                    account_type, account_index = account_id.split('_', 1)
                    account_index = int(account_index)
                    print(f"[P2P] Parsed frontend account ID: type='{account_type}', index={account_index}")
                    
                    if account_type == 'personal':
                        # Show only personal trades for this user, excluding cancelled
                        base_trades = P2PTrade.objects.filter(
                            models.Q(buyer_user=user) | models.Q(seller_user=user)
                        ).exclude(status='CANCELLED').prefetch_related('ratings')
                        
                        # Apply sorting
                        trades = Query._get_sorted_trades_queryset(base_trades)
                        
                        total_count = trades.count()
                        active_count = trades.exclude(status='COMPLETED').count()
                        
                        print(f"[P2P] Filtering personal trades for user_id: {user.id}, found: {total_count} trades ({active_count} active), returning offset={offset}, limit={limit}")
                        paginated_trades = trades[offset:offset+limit]
                        
                        return P2PTradePaginatedType(
                            trades=paginated_trades,
                            total_count=total_count,
                            has_more=(offset + limit) < total_count,
                            offset=offset,
                            limit=limit,
                            active_count=active_count
                        )
                    elif account_type == 'business':
                        # Find the business account by index
                        from users.models import Account
                        try:
                            account = Account.objects.get(
                                user=user, 
                                account_type='business', 
                                account_index=account_index
                            )
                            print(f"[P2P] Found business account: {account.id}, business: {account.business.id if account.business else 'None'}")
                            
                            if account.business:
                                # Show only business trades for this specific business, excluding cancelled
                                base_trades = P2PTrade.objects.filter(
                                    models.Q(buyer_business=account.business) | models.Q(seller_business=account.business)
                                ).exclude(status='CANCELLED').prefetch_related('ratings')
                                
                                # Apply sorting
                                trades = Query._get_sorted_trades_queryset(base_trades)
                                
                                total_count = trades.count()
                                active_count = trades.exclude(status='COMPLETED').count()
                                
                                print(f"[P2P] Filtering business trades for business_id: {account.business.id}, found: {total_count} trades ({active_count} active), returning offset={offset}, limit={limit}")
                                paginated_trades = trades[offset:offset+limit]
                                
                                return P2PTradePaginatedType(
                                    trades=paginated_trades,
                                    total_count=total_count,
                                    has_more=(offset + limit) < total_count,
                                    offset=offset,
                                    limit=limit,
                                    active_count=active_count
                                )
                        except Account.DoesNotExist:
                            print(f"[P2P] Business account not found: user_id={user.id}, account_index={account_index}")
                            return P2PTradePaginatedType(
                                trades=[],
                                total_count=0,
                                has_more=False,
                                offset=offset,
                                limit=limit,
                                active_count=0
                            )
                else:
                    # Fallback: try to use account_id as a direct database ID
                    from users.models import Account
                    try:
                        account = Account.objects.get(id=account_id, user=user)
                        print(f"[P2P] Found database account: {account.id}, type: {account.account_type}, business: {account.business.id if account.business else 'None'}")
                        
                        if account.account_type == 'business' and account.business:
                            # Show only business trades for this specific business, excluding cancelled
                            base_trades = P2PTrade.objects.filter(
                                models.Q(buyer_business=account.business) | models.Q(seller_business=account.business)
                            ).exclude(status='CANCELLED').prefetch_related('ratings')
                            
                            # Apply sorting
                            trades = Query._get_sorted_trades_queryset(base_trades)
                            
                            total_count = trades.count()
                            active_count = trades.exclude(status='COMPLETED').count()
                            
                            print(f"[P2P] Filtering business trades for business_id: {account.business.id}, found: {total_count} trades ({active_count} active), returning offset={offset}, limit={limit}")
                            paginated_trades = trades[offset:offset+limit]
                            
                            return P2PTradePaginatedType(
                                trades=paginated_trades,
                                total_count=total_count,
                                has_more=(offset + limit) < total_count,
                                offset=offset,
                                limit=limit,
                                active_count=active_count
                            )
                        else:
                            # Show only personal trades for this user, excluding cancelled
                            base_trades = P2PTrade.objects.filter(
                                models.Q(buyer_user=user) | models.Q(seller_user=user)
                            ).exclude(status='CANCELLED').prefetch_related('ratings')
                            
                            # Apply sorting
                            trades = Query._get_sorted_trades_queryset(base_trades)
                            
                            total_count = trades.count()
                            active_count = trades.exclude(status='COMPLETED').count()
                            
                            print(f"[P2P] Filtering personal trades for user_id: {user.id}, found: {total_count} trades ({active_count} active), returning offset={offset}, limit={limit}")
                            paginated_trades = trades[offset:offset+limit]
                            
                            return P2PTradePaginatedType(
                                trades=paginated_trades,
                                total_count=total_count,
                                has_more=(offset + limit) < total_count,
                                offset=offset,
                                limit=limit,
                                active_count=active_count
                            )
                    except (Account.DoesNotExist, ValueError):
                        print(f"[P2P] Database account not found: account_id={account_id}, user_id={user.id}")
                        return P2PTradePaginatedType(
                            trades=[],
                            total_count=0,
                            has_more=False,
                            offset=offset,
                            limit=limit,
                            active_count=0
                        )
                
                return P2PTradePaginatedType(
                    trades=[],
                    total_count=0,
                    has_more=False,
                    offset=offset,
                    limit=limit,
                    active_count=0
                )
            else:
                # No account filter - show all trades for this user (all accounts)
                print(f"[P2P] No account_id provided - returning ALL trades for user")
                from users.models import Business
                user_businesses = Business.objects.filter(accounts__user=user)
                
                # Find trades where user is involved as a person OR through their businesses, excluding cancelled
                # NEW: Use direct relationships for cleaner semantics
                base_trades = P2PTrade.objects.filter(
                    models.Q(buyer_user=user) | models.Q(seller_user=user) |
                    models.Q(buyer_business__in=user_businesses) | models.Q(seller_business__in=user_businesses)
                ).exclude(status='CANCELLED').prefetch_related('ratings')
                
                # Apply sorting
                trades = Query._get_sorted_trades_queryset(base_trades)
                
                total_count = trades.count()
                active_count = trades.exclude(status='COMPLETED').count()
                
                print(f"[P2P] Found {total_count} total trades across all accounts ({active_count} active), returning offset={offset}, limit={limit}")
                paginated_trades = trades[offset:offset+limit]
                
                return P2PTradePaginatedType(
                    trades=paginated_trades,
                    total_count=total_count,
                    has_more=(offset + limit) < total_count,
                    offset=offset,
                    limit=limit,
                    active_count=active_count
                )
        except Exception as e:
            print(f"[P2P] Error in resolve_my_p2p_trades: {str(e)}")
            import traceback
            traceback.print_exc()
            # Return empty result on error
            return P2PTradePaginatedType(
                trades=[],
                total_count=0,
                has_more=False,
                offset=offset,
                limit=limit,
                active_count=0
            )
    
    @staticmethod
    def _get_sorted_trades_queryset(base_queryset):
        """
        Sort trades by status priority and creation date.
        Active trades come first, sorted by status, then completed trades.
        """
        from django.db.models import Case, When, IntegerField
        
        # Define status priority (lower number = higher priority)
        # DISPUTED trades should appear at the top with high priority
        status_ordering = Case(
            When(status='DISPUTED', then=1),
            When(status='PENDING', then=2),
            When(status='PAYMENT_PENDING', then=3),
            When(status='PAYMENT_SENT', then=4),
            When(status='PAYMENT_CONFIRMED', then=5),
            When(status='COMPLETED', then=6),
            default=999,
            output_field=IntegerField()
        )
        
        return base_queryset.annotate(
            status_priority=status_ordering
        ).order_by('status_priority', '-created_at')

    def resolve_p2p_trade(self, info, id):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return None
        
        try:
            # Use new fields to check access
            return P2PTrade.objects.filter(
                id=id
            ).filter(
                models.Q(buyer_user=user) | 
                models.Q(seller_user=user) |
                models.Q(buyer_business__accounts__user=user) |
                models.Q(seller_business__accounts__user=user)
            ).distinct().first()
        except P2PTrade.DoesNotExist:
            return None

    def resolve_p2p_trade_messages(self, info, trade_id):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return []
        
        try:
            # Use new fields to check access
            trade = P2PTrade.objects.filter(
                id=trade_id
            ).filter(
                models.Q(buyer_user=user) | 
                models.Q(seller_user=user) |
                models.Q(buyer_business__accounts__user=user) |
                models.Q(seller_business__accounts__user=user)
            ).distinct().first()
            
            if trade:
                return P2PMessage.objects.filter(trade=trade).order_by('created_at')  # Ascending order (oldest first)
            return []
        except P2PTrade.DoesNotExist:
            return []

    def resolve_p2p_payment_methods(self, info, country_code=None):
        import datetime
        import random
        request_id = random.randint(1000, 9999)
        print(f"🔍 DEBUG [{datetime.datetime.now()}] REQ-{request_id}: resolve_p2p_payment_methods called with country_code: '{country_code}'")
        
        # Get payment methods from database (only country-specific methods)
        # No global methods should exist per user requirements
        if country_code:
            db_methods = P2PPaymentMethod.objects.filter(
                country_code=country_code,
                is_active=True
            ).order_by('display_order', 'display_name')
        else:
            # If no country_code provided, return empty list
            # All payment methods must be country-specific
            db_methods = P2PPaymentMethod.objects.none()
        
        print(f"📋 DEBUG REQ-{request_id}: Found {db_methods.count()} database payment methods for country: '{country_code or 'global'}'")
        
        # Convert to GraphQL objects
        payment_methods = []
        for db_method in db_methods:
            # Create a simple object that matches P2PPaymentMethodType fields
            payment_method = type('PaymentMethod', (), {
                'id': str(db_method.id),
                'name': db_method.name,
                'display_name': db_method.display_name,
                'icon': db_method.icon,
                'is_active': db_method.is_active,
                'provider_type': db_method.provider_type,
                'requires_phone': db_method.requires_phone,
                'requires_email': db_method.requires_email,
                'requires_account_number': db_method.requires_account_number,
                'country_code': db_method.country_code,
                'bank': db_method.bank,  # This will be resolved by users.schema.BankType
                'country': db_method.country  # This will be resolved by users.schema.CountryType
            })()
            payment_methods.append(payment_method)
            print(f"   - {db_method.display_name} ({db_method.name}) - Type: {db_method.provider_type}")
        
        print(f"✅ DEBUG REQ-{request_id}: Returning {len(payment_methods)} payment methods to GraphQL")
        return payment_methods

# Mutations
class ToggleFavoriteTrader(graphene.Mutation):
    class Arguments:
        trader_user_id = graphene.ID(required=False)
        trader_business_id = graphene.ID(required=False)
        note = graphene.String(required=False)
    
    success = graphene.Boolean()
    is_favorite = graphene.Boolean()
    message = graphene.String()
    
    @classmethod
    def mutate(cls, root, info, trader_user_id=None, trader_business_id=None, note=""):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return ToggleFavoriteTrader(
                success=False,
                is_favorite=False,
                message="Authentication required"
            )
        
        # Validate input
        if not trader_user_id and not trader_business_id:
            return ToggleFavoriteTrader(
                success=False,
                is_favorite=False,
                message="Either trader_user_id or trader_business_id must be provided"
            )
        
        if trader_user_id and trader_business_id:
            return ToggleFavoriteTrader(
                success=False,
                is_favorite=False,
                message="Cannot provide both trader_user_id and trader_business_id"
            )
        
        # Get the active account context from the request
        request = info.context
        active_account_type = getattr(request, 'active_account_type', 'personal')
        active_account_index = getattr(request, 'active_account_index', 0)
        
        try:
            # Determine favoriter_business if acting as business account
            favoriter_business = None
            if active_account_type == 'business':
                from users.models import Account
                active_account = Account.objects.filter(
                    user=user,
                    account_type='business',
                    account_index=active_account_index
                ).first()
                
                if active_account and active_account.business:
                    favoriter_business = active_account.business
                else:
                    return ToggleFavoriteTrader(
                        success=False,
                        is_favorite=False,
                        message="Business account not found"
                    )
            
            # Check if already favorited
            if trader_user_id:
                # Personal accounts can't favorite themselves, but business accounts can favorite the owner's personal account
                if str(trader_user_id) == str(user.id) and active_account_type == 'personal':
                    return ToggleFavoriteTrader(
                        success=False,
                        is_favorite=False,
                        message="Cannot favorite yourself"
                    )
                
                favorite_user = User.objects.get(id=trader_user_id)
                
                # Check for existing favorite based on account context
                if favoriter_business:
                    existing = P2PFavoriteTrader.objects.filter(
                        user=user,
                        favoriter_business=favoriter_business,
                        favorite_user=favorite_user
                    ).first()
                else:
                    existing = P2PFavoriteTrader.objects.filter(
                        user=user,
                        favoriter_business__isnull=True,
                        favorite_user=favorite_user
                    ).first()
                
                if existing:
                    # Remove from favorites
                    existing.delete()
                    return ToggleFavoriteTrader(
                        success=True,
                        is_favorite=False,
                        message="Removed from favorites"
                    )
                else:
                    # Add to favorites
                    P2PFavoriteTrader.objects.create(
                        user=user,
                        favoriter_business=favoriter_business,
                        favorite_user=favorite_user,
                        note=note
                    )
                    return ToggleFavoriteTrader(
                        success=True,
                        is_favorite=True,
                        message="Added to favorites"
                    )
            
            else:  # trader_business_id
                from users.models import Business
                favorite_business = Business.objects.get(id=trader_business_id)
                
                # Check if trying to favorite own business from same business account
                if favoriter_business and favoriter_business.id == favorite_business.id:
                    return ToggleFavoriteTrader(
                        success=False,
                        is_favorite=False,
                        message="Cannot favorite your own business account"
                    )
                
                # Check for existing favorite based on account context
                if favoriter_business:
                    existing = P2PFavoriteTrader.objects.filter(
                        user=user,
                        favoriter_business=favoriter_business,
                        favorite_business=favorite_business
                    ).first()
                else:
                    existing = P2PFavoriteTrader.objects.filter(
                        user=user,
                        favoriter_business__isnull=True,
                        favorite_business=favorite_business
                    ).first()
                
                if existing:
                    # Remove from favorites
                    existing.delete()
                    return ToggleFavoriteTrader(
                        success=True,
                        is_favorite=False,
                        message="Removed from favorites"
                    )
                else:
                    # Add to favorites
                    P2PFavoriteTrader.objects.create(
                        user=user,
                        favoriter_business=favoriter_business,
                        favorite_business=favorite_business,
                        note=note
                    )
                    return ToggleFavoriteTrader(
                        success=True,
                        is_favorite=True,
                        message="Added to favorites"
                    )
                
        except User.DoesNotExist:
            return ToggleFavoriteTrader(
                success=False,
                is_favorite=False,
                message="Trader not found"
            )
        except Exception as e:
            return ToggleFavoriteTrader(
                success=False,
                is_favorite=False,
                message=str(e)
            )


class Mutation(graphene.ObjectType):
    create_p2p_offer = CreateP2POffer.Field()
    update_p2p_offer = UpdateP2POffer.Field()
    create_p2p_trade = CreateP2PTrade.Field()
    update_p2p_trade_status = UpdateP2PTradeStatus.Field()
    send_p2p_message = SendP2PMessage.Field()
    rate_p2p_trade = RateP2PTrade.Field()
    dispute_p2p_trade = DisputeP2PTrade.Field()
    confirm_p2p_trade_step = ConfirmP2PTradeStep.Field()
    toggle_favorite_trader = ToggleFavoriteTrader.Field()

# Admin Dispute Resolution Mutations
class ResolveDispute(graphene.Mutation):
    """Mutation for admins to resolve disputes"""
    
    class Arguments:
        dispute_id = graphene.ID(required=True)
        resolution_type = graphene.String(required=True)
        resolution_notes = graphene.String()
        resolution_amount = graphene.Decimal()
    
    dispute = graphene.Field(P2PDisputeType)
    trade = graphene.Field(P2PTradeType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    
    def mutate(self, info, dispute_id, resolution_type, resolution_notes=None, resolution_amount=None):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return ResolveDispute(
                dispute=None,
                trade=None,
                success=False,
                errors=["Authentication required"]
            )
        
        # Check if user is admin/staff
        if not (user.is_staff or user.is_superuser):
            return ResolveDispute(
                dispute=None,
                trade=None,
                success=False,
                errors=["Admin privileges required"]
            )
        
        try:
            from .models import P2PDispute, P2PTrade
            from django.utils import timezone
            
            # Get the dispute
            dispute = P2PDispute.objects.get(id=dispute_id)
            
            if dispute.status == 'RESOLVED':
                return ResolveDispute(
                    dispute=dispute,
                    trade=dispute.trade,
                    success=False,
                    errors=["Dispute is already resolved"]
                )
            
            # Update dispute
            dispute.status = 'RESOLVED'
            dispute.resolution_type = resolution_type
            dispute.resolution_notes = resolution_notes or f"Resolved by {user.username}"
            dispute.resolution_amount = resolution_amount
            dispute.resolved_by = user
            dispute.resolved_at = timezone.now()
            dispute.save()
            
            # Update trade based on resolution type and handle escrow
            trade = dispute.trade
            
            # Handle escrow fund movements
            try:
                escrow = trade.escrow
                if escrow and escrow.is_escrowed and not escrow.is_released:
                    # Funds are in escrow and need to be moved
                    
                    if resolution_type == 'REFUND_BUYER':
                        # Refund funds to buyer
                        trade.status = 'CANCELLED'
                        # TODO: Implement blockchain refund transaction
                        escrow.release_transaction_hash = f"dispute_refund_{dispute.id}_{timezone.now().timestamp()}"
                        
                        # Use the new release_funds method
                        escrow.release_funds(
                            release_type='REFUND',
                            amount=escrow.escrow_amount,
                            dispute=dispute
                        )
                        
                        # Create transaction record
                        from .models import P2PDisputeTransaction
                        P2PDisputeTransaction.objects.create(
                            dispute=dispute,
                            trade=trade,
                            transaction_type='REFUND',
                            amount=escrow.escrow_amount,
                            token_type=escrow.token_type,
                            recipient_user=trade.buyer_user,
                            recipient_business=trade.buyer_business,
                            status='COMPLETED',
                            processed_by=user,
                            processed_at=timezone.now(),
                            transaction_hash=escrow.release_transaction_hash,
                            notes=f"Dispute resolution: Full refund to buyer"
                        )
                        
                    elif resolution_type == 'RELEASE_TO_SELLER':
                        # Release funds to seller (dispute resolved in seller's favor)
                        trade.status = 'COMPLETED' 
                        trade.completed_at = timezone.now()
                        # TODO: Implement blockchain release transaction
                        escrow.release_transaction_hash = f"dispute_release_{dispute.id}_{timezone.now().timestamp()}"
                        
                        # Use the new release_funds method
                        escrow.release_funds(
                            release_type='DISPUTE_RELEASE',
                            amount=escrow.escrow_amount,
                            dispute=dispute
                        )
                        
                        # Create transaction record
                        P2PDisputeTransaction.objects.create(
                            dispute=dispute,
                            trade=trade,
                            transaction_type='RELEASE',
                            amount=escrow.escrow_amount,
                            token_type=escrow.token_type,
                            recipient_user=trade.seller_user,
                            recipient_business=trade.seller_business,
                            status='COMPLETED',
                            processed_by=user,
                            processed_at=timezone.now(),
                            transaction_hash=escrow.release_transaction_hash,
                            notes=f"Dispute resolution: Release to seller"
                        )
                        
                    elif resolution_type == 'PARTIAL_REFUND':
                        # Split funds between buyer and seller
                        trade.status = 'COMPLETED'
                        trade.completed_at = timezone.now()
                        # TODO: Implement blockchain partial refund transaction
                        escrow.release_transaction_hash = f"dispute_partial_{dispute.id}_{timezone.now().timestamp()}"
                        
                        # Calculate amounts
                        refund_amount = resolution_amount or (escrow.escrow_amount / 2)  # Default to 50/50 split
                        
                        # Use the new release_funds method
                        escrow.release_funds(
                            release_type='PARTIAL_REFUND',
                            amount=refund_amount,  # Track the refund amount as the primary release amount
                            dispute=dispute
                        )
                        
                        # Create transaction records for partial refund
                        seller_amount = escrow.escrow_amount - refund_amount
                        
                        # Refund to buyer
                        if refund_amount > 0:
                            P2PDisputeTransaction.objects.create(
                                dispute=dispute,
                                trade=trade,
                                transaction_type='PARTIAL_REFUND',
                                amount=refund_amount,
                                token_type=escrow.token_type,
                                recipient_user=trade.buyer_user,
                                recipient_business=trade.buyer_business,
                                status='COMPLETED',
                                processed_by=user,
                                processed_at=timezone.now(),
                                transaction_hash=escrow.release_transaction_hash + "_buyer",
                                notes=f"Dispute resolution: Partial refund to buyer ({refund_amount} {escrow.token_type})"
                            )
                        
                        # Payment to seller
                        if seller_amount > 0:
                            P2PDisputeTransaction.objects.create(
                                dispute=dispute,
                                trade=trade,
                                transaction_type='SPLIT',
                                amount=seller_amount,
                                token_type=escrow.token_type,
                                recipient_user=trade.seller_user,
                                recipient_business=trade.seller_business,
                                status='COMPLETED',
                                processed_by=user,
                                processed_at=timezone.now(),
                                transaction_hash=escrow.release_transaction_hash + "_seller",
                                notes=f"Dispute resolution: Partial payment to seller ({seller_amount} {escrow.token_type})"
                            )
                        
                    elif resolution_type == 'CANCELLED':
                        # Cancel trade and refund to buyer
                        trade.status = 'CANCELLED'
                        # TODO: Implement blockchain refund transaction
                        escrow.release_transaction_hash = f"dispute_cancel_{dispute.id}_{timezone.now().timestamp()}"
                        
                        # Use the new release_funds method
                        escrow.release_funds(
                            release_type='REFUND',
                            amount=escrow.escrow_amount,
                            dispute=dispute
                        )
                        
                        # Create transaction record
                        P2PDisputeTransaction.objects.create(
                            dispute=dispute,
                            trade=trade,
                            transaction_type='REFUND',
                            amount=escrow.escrow_amount,
                            token_type=escrow.token_type,
                            recipient_user=trade.buyer_user,
                            recipient_business=trade.buyer_business,
                            status='COMPLETED',
                            processed_by=user,
                            processed_at=timezone.now(),
                            transaction_hash=escrow.release_transaction_hash,
                            notes=f"Dispute resolution: Trade cancelled, full refund to buyer"
                        )
                        
                    # For 'NO_ACTION', keep current trade status and don't touch escrow
                    
                else:
                    # No escrow or already released, just update trade status
                    if resolution_type == 'REFUND_BUYER':
                        trade.status = 'CANCELLED'
                    elif resolution_type == 'RELEASE_TO_SELLER':
                        trade.status = 'COMPLETED'
                        trade.completed_at = timezone.now()
                    elif resolution_type == 'PARTIAL_REFUND':
                        trade.status = 'COMPLETED'
                        trade.completed_at = timezone.now()
                    elif resolution_type == 'CANCELLED':
                        trade.status = 'CANCELLED'
                        
            except Exception as escrow_error:
                print(f"[DISPUTE] Escrow handling error for dispute {dispute_id}: {str(escrow_error)}")
                # Continue with trade status update even if escrow fails
                if resolution_type == 'REFUND_BUYER':
                    trade.status = 'CANCELLED'
                elif resolution_type == 'RELEASE_TO_SELLER':
                    trade.status = 'COMPLETED'
                    trade.completed_at = timezone.now()
                elif resolution_type == 'PARTIAL_REFUND':
                    trade.status = 'COMPLETED'
                    trade.completed_at = timezone.now()
                elif resolution_type == 'CANCELLED':
                    trade.status = 'CANCELLED'
            
            trade.save()
            
            # Send system message to chat
            from .models import P2PMessage
            resolution_messages = {
                'REFUND_BUYER': '✅ Disputa resuelta: Se ha procesado el reembolso completo al comprador.',
                'RELEASE_TO_SELLER': '✅ Disputa resuelta: Los fondos han sido liberados al vendedor.',
                'PARTIAL_REFUND': f'✅ Disputa resuelta: Se ha procesado un reembolso parcial de {resolution_amount or "N/A"}.',
                'CANCELLED': '✅ Disputa resuelta: El intercambio ha sido cancelado.',
                'NO_ACTION': '✅ Disputa resuelta: No se requiere acción adicional.'
            }
            
            system_message = resolution_messages.get(resolution_type, '✅ Disputa resuelta.')
            if resolution_notes:
                system_message += f"\n\nNotas del administrador: {resolution_notes}"
            
            P2PMessage.objects.create(
                trade=trade,
                message=system_message,
                sender_type='system',
                message_type='system'
            )
            
            print(f"[DISPUTE] Resolved dispute {dispute_id} with {resolution_type} by {user.username}")
            
            return ResolveDispute(
                dispute=dispute,
                trade=trade,
                success=True,
                errors=[]
            )
            
        except P2PDispute.DoesNotExist:
            return ResolveDispute(
                dispute=None,
                trade=None,
                success=False,
                errors=["Dispute not found"]
            )
        except Exception as e:
            print(f"[DEBUG] Error in ResolveDispute: {str(e)}")
            import traceback
            traceback.print_exc()
            return ResolveDispute(
                dispute=None,
                trade=None,
                success=False,
                errors=[f"Error resolving dispute: {str(e)}"]
            )

class EscalateDispute(graphene.Mutation):
    """Mutation for escalating disputes to higher priority"""
    
    class Arguments:
        dispute_id = graphene.ID(required=True)
        escalation_notes = graphene.String()
    
    dispute = graphene.Field(P2PDisputeType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    
    def mutate(self, info, dispute_id, escalation_notes=None):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return EscalateDispute(
                dispute=None,
                success=False,
                errors=["Authentication required"]
            )
        
        # Check if user is admin/staff
        if not (user.is_staff or user.is_superuser):
            return EscalateDispute(
                dispute=None,
                success=False,
                errors=["Admin privileges required"]
            )
        
        try:
            from .models import P2PDispute
            
            dispute = P2PDispute.objects.get(id=dispute_id)
            
            if dispute.status == 'RESOLVED':
                return EscalateDispute(
                    dispute=dispute,
                    success=False,
                    errors=["Cannot escalate resolved dispute"]
                )
            
            # Update dispute
            dispute.status = 'ESCALATED'
            dispute.priority = min(3, dispute.priority + 1)  # Max priority is 3 (high)
            if escalation_notes:
                current_notes = dispute.admin_notes or ""
                dispute.admin_notes = f"{current_notes}\n\n[ESCALATED by {user.username}]: {escalation_notes}".strip()
            dispute.save()
            
            print(f"[DISPUTE] Escalated dispute {dispute_id} by {user.username}")
            
            return EscalateDispute(
                dispute=dispute,
                success=True,
                errors=[]
            )
            
        except P2PDispute.DoesNotExist:
            return EscalateDispute(
                dispute=None,
                success=False,
                errors=["Dispute not found"]
            )
        except Exception as e:
            print(f"[DEBUG] Error in EscalateDispute: {str(e)}")
            import traceback
            traceback.print_exc()
            return EscalateDispute(
                dispute=None,
                success=False,
                errors=[f"Error escalating dispute: {str(e)}"]
            )

class AddDisputeEvidence(graphene.Mutation):
    """Mutation for admins to add evidence or notes to disputes"""
    
    class Arguments:
        dispute_id = graphene.ID(required=True)
        evidence_type = graphene.String(required=True)  # 'note', 'evidence', 'communication'
        content = graphene.String(required=True)
        evidence_urls = graphene.List(graphene.String)
    
    dispute = graphene.Field(P2PDisputeType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)
    
    def mutate(self, info, dispute_id, evidence_type, content, evidence_urls=None):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return AddDisputeEvidence(
                dispute=None,
                success=False,
                errors=["Authentication required"]
            )
        
        # Check if user is admin/staff
        if not (user.is_staff or user.is_superuser):
            return AddDisputeEvidence(
                dispute=None,
                success=False,
                errors=["Admin privileges required"]
            )
        
        try:
            from .models import P2PDispute
            from django.utils import timezone
            
            dispute = P2PDispute.objects.get(id=dispute_id)
            
            if dispute.status == 'RESOLVED':
                return AddDisputeEvidence(
                    dispute=dispute,
                    success=False,
                    errors=["Cannot add evidence to resolved dispute"]
                )
            
            # Add to admin notes
            timestamp = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            evidence_entry = f"\n\n[{evidence_type.upper()} - {timestamp} by {user.username}]: {content}"
            
            if evidence_urls:
                evidence_entry += f"\nEvidence URLs: {', '.join(evidence_urls)}"
                # Also add to evidence_urls field
                current_urls = dispute.evidence_urls or []
                dispute.evidence_urls = current_urls + evidence_urls
            
            current_notes = dispute.admin_notes or ""
            dispute.admin_notes = (current_notes + evidence_entry).strip()
            dispute.save()
            
            # If it's a communication note, also add to trade chat
            if evidence_type == 'communication':
                from .models import P2PMessage
                P2PMessage.objects.create(
                    trade=dispute.trade,
                    message=f"💬 Mensaje del equipo de soporte:\n\n{content}",
                    sender_type='system',
                    message_type='system'
                )
            
            print(f"[DISPUTE] Added {evidence_type} to dispute {dispute_id} by {user.username}")
            
            return AddDisputeEvidence(
                dispute=dispute,
                success=True,
                errors=[]
            )
            
        except P2PDispute.DoesNotExist:
            return AddDisputeEvidence(
                dispute=None,
                success=False,
                errors=["Dispute not found"]
            )
        except Exception as e:
            print(f"[DEBUG] Error in AddDisputeEvidence: {str(e)}")
            import traceback
            traceback.print_exc()
            return AddDisputeEvidence(
                dispute=None,
                success=False,
                errors=[f"Error adding evidence: {str(e)}"]
            )

# Add the admin dispute mutations to the main Mutation class
Mutation.resolve_dispute = ResolveDispute.Field()
Mutation.escalate_dispute = EscalateDispute.Field()
Mutation.add_dispute_evidence = AddDisputeEvidence.Field()

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

# Ensure all types are properly exported
__all__ = [
    'P2POfferType',
    'P2PTradeType',
    'P2PTradePaginatedType',
    'P2PMessageType',
    'P2PPaymentMethodType',
    'P2PUserStatsType',
    'P2PRatingType',
    'P2PTradeConfirmationType',
    'Query',
    'Mutation',
    'Subscription',
]
