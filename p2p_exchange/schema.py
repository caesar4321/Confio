import graphene
from django.conf import settings
from django.utils import timezone
import random
import string
from .models import P2PDisputeEvidence
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
from security.s3_utils import generate_presigned_put, public_s3_url, build_s3_key
from django.conf import settings
from security.utils import graphql_require_kyc, graphql_require_aml, perform_aml_check

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
            'max_amount', 'payment_methods', 'country_code', 'currency_code', 'terms',
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
        
        # Get JWT context for account determination
        from users.jwt_context import get_jwt_business_context_with_validation
        try:
            jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
            active_account_type = jwt_context['account_type']
            active_account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')
        except:
            # Fallback for unauthenticated users or errors
            active_account_type = 'personal'
            active_account_index = 0
            business_id = None
        
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
    
    evidences = graphene.List(lambda: DisputeEvidenceType)

    class Meta:
        model = P2PDispute
        fields = (
            'id', 'trade', 'initiator_user', 'initiator_business',
            'reason', 'status', 'priority', 'resolution_type',
            'resolution_amount', 'resolution_notes', 'admin_notes',
            'evidence_urls', 'resolved_by', 'opened_at', 'resolved_at',
            'last_updated'
        )

    def resolve_evidences(self, info):
        try:
            return list(self.evidences.all().order_by('-uploaded_at'))
        except Exception:
            return []


class DisputeEvidenceType(DjangoObjectType):
    class Meta:
        model = P2PDisputeEvidence
        fields = (
            'id', 'url', 'content_type', 'size_bytes', 'sha256', 'etag', 'confio_code', 'source', 'status', 'uploaded_at'
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
    # Dispute info
    dispute = graphene.Field('p2p_exchange.schema.P2PDisputeType')
    evidence_count = graphene.Int()
    has_evidence = graphene.Boolean()
    
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

    def resolve_dispute(self, info):
        try:
            return getattr(self, 'dispute_details', None)
        except Exception:
            return None

    def resolve_evidence_count(self, info):
        try:
            user = getattr(info.context, 'user', None)
            disp = getattr(self, 'dispute_details', None)
            if not (user and getattr(user, 'is_authenticated', False) and disp):
                return 0
            from users.jwt_context import get_jwt_business_context_with_validation
            ctx = get_jwt_business_context_with_validation(info, required_permission=None) or {}
            qs = P2PDisputeEvidence.objects.filter(dispute_id=disp.id)
            business_id = ctx.get('business_id')
            if ctx.get('account_type') == 'business' and business_id:
                try:
                    qs = qs.filter(uploader_business_id=int(business_id))
                except Exception:
                    qs = qs.filter(uploader_business_id=business_id)
            else:
                qs = qs.filter(uploader_user_id=getattr(user, 'id', None))
            return qs.count()
        except Exception:
            return 0

    def resolve_has_evidence(self, info):
        try:
            user = getattr(info.context, 'user', None)
            disp = getattr(self, 'dispute_details', None)
            if not (user and getattr(user, 'is_authenticated', False) and disp):
                return False
            uploader_filter = {'uploader_user_id': getattr(user, 'id', None)}
            try:
                from users.jwt_context import get_jwt_business_context_with_validation
                ctx = get_jwt_business_context_with_validation(info, required_permission=None) or {}
                if ctx.get('account_type') == 'business' and ctx.get('business_id'):
                    uploader_filter = {'uploader_business_id': ctx.get('business_id')}
            except Exception:
                pass
            return P2PDisputeEvidence.objects.filter(dispute_id=disp.id, **uploader_filter).exists()
        except Exception:
            return False
    
    def resolve_has_rating(self, info):
        """Returns True if the current user has already rated this trade"""
        try:
            user = info.context.user
            if not user.is_authenticated:
                return False
            
            # Get JWT context for account determination
            from users.jwt_context import get_jwt_business_context_with_validation
            try:
                jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
                active_account_type = jwt_context['account_type']
                active_account_index = jwt_context['account_index']
                business_id = jwt_context.get('business_id')
            except:
                # Fallback for unauthenticated users or errors
                active_account_type = 'personal'
                active_account_index = 0
                business_id = None
            
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
    payment_method_ids = graphene.List(graphene.ID, required=True)
    country_code = graphene.String(required=True)  # Required country code for the offer
    terms = graphene.String()
    response_time_minutes = graphene.Int()

class CreateP2PTradeInput(graphene.InputObjectType):
    offerId = graphene.ID(required=True)
    cryptoAmount = graphene.Decimal(required=True)
    paymentMethodId = graphene.ID(required=True)

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

            # No preflight balance validation; availability checked at escrow time

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
                'country_code': input.country_code,
                'currency_code': cls._get_currency_for_country(input.country_code),
                'terms': input.terms or '',
                'response_time_minutes': input.response_time_minutes or 15,
                # Keep old fields for backward compatibility
                'user': user,
            }

            # Use JWT context to determine account type instead of input.account_id
            from users.jwt_context import get_jwt_business_context_with_validation
            from users.models import Business
            
            # Get JWT context with validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
            if not jwt_context:
                return CreateP2POffer(
                    offer=None,
                    success=False,
                    errors=["Invalid account context"]
                )
                
            account_type = jwt_context['account_type']
            business_id = jwt_context.get('business_id')
            
            print(f"CreateP2POffer - JWT context: account_type={account_type}, business_id={business_id}")
            
            if account_type == 'business' and business_id:
                # Business offer using JWT business_id
                try:
                    business = Business.objects.get(id=business_id)
                    offer_kwargs['offer_business'] = business
                    print(f"CreateP2POffer - Creating business offer for business {business.name}")
                except Business.DoesNotExist:
                    return CreateP2POffer(
                        offer=None,
                        success=False,
                        errors=["Business not found"]
                    )
            else:
                # Personal offer
                offer_kwargs['offer_user'] = user
                print(f"CreateP2POffer - Creating personal offer for user {user.username}")

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
        # available_amount removed
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
            
            # available_amount removed
            
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
    @graphql_require_aml()
    @graphql_require_kyc('p2p_trade')
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

            # Do not check offer.available_amount; rely on on-chain escrow validation

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
            
            # Use JWT context to determine account type instead of input.accountId
            from users.jwt_context import get_jwt_business_context_with_validation
            from users.models import Business
            
            # Get JWT context with validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
            if not jwt_context:
                return CreateP2PTrade(
                    trade=None,
                    success=False,
                    errors=["Invalid account context"]
                )
                
            account_type = jwt_context['account_type']
            business_id = jwt_context.get('business_id')
            
            print(f"CreateP2PTrade - JWT context: account_type={account_type}, business_id={business_id}")
            
            if account_type == 'business' and business_id:
                # Business trade using JWT business_id
                try:
                    business = Business.objects.get(id=business_id)
                    user_entity = business
                    user_entity_type = 'business'
                    print(f"CreateP2PTrade - Creating business trade for business {business.name}")
                except Business.DoesNotExist:
                    return CreateP2PTrade(
                        trade=None,
                        success=False,
                        errors=["Business not found"]
                    )
            else:
                # Personal trade
                user_entity = user
                user_entity_type = 'user'
                print(f"CreateP2PTrade - Creating personal trade for user {user.username}")
            
            # Check offer's account type - use new direct relationships
            if offer.offer_business:
                offer_entity = offer.offer_business
                offer_entity_type = 'business'
                print(f"CreateP2PTrade - Offer is from business: {offer.offer_business.name}")
            elif offer.offer_user:
                offer_entity = offer.offer_user
                offer_entity_type = 'user'
                print(f"CreateP2PTrade - Offer is from user: {offer.offer_user.username}")
            
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
                'buyer_account': None,  # Legacy field - not needed with JWT context
                'seller_account': None,  # Legacy field - not needed with JWT context
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

            # Log trade creation details
            print(f"CreateP2PTrade - Trade creation details:")
            print(f"  - Buyer: {trade_kwargs.get('buyer_business', trade_kwargs.get('buyer_user'))}")
            print(f"  - Seller: {trade_kwargs.get('seller_business', trade_kwargs.get('seller_user'))}")
            print(f"  - Buyer type: {'business' if 'buyer_business' in trade_kwargs else 'user'}")
            print(f"  - Seller type: {'business' if 'seller_business' in trade_kwargs else 'user'}")
            
            # Create trade with new direct relationships
            trade = P2PTrade.objects.create(**trade_kwargs)
            
            # Perform AML check for the trade
            aml_result = perform_aml_check(
                user=user,
                transaction_type='p2p_trade',
                amount=fiat_amount
            )
            
            # Check if trade should be flagged for review
            if aml_result['requires_review']:
                trade.status = 'AML_REVIEW'
                trade.save()
                
                # Create suspicious activity if high risk
                if aml_result['risk_score'] >= 70:
                    from security.utils import create_suspicious_activity
                    create_suspicious_activity(
                        user=user,
                        activity_type='high_risk_p2p_trade',
                        detection_data={
                            'trade_id': trade.id,
                            'offer_id': offer.id,
                            'fiat_amount': str(fiat_amount),
                            'crypto_amount': str(input.cryptoAmount),
                            'risk_score': aml_result['risk_score'],
                            'risk_factors': aml_result['risk_factors']
                        },
                        severity=min(aml_result['risk_score'] // 10, 10)
                    )
                
                return CreateP2PTrade(
                    trade=trade,
                    success=True,
                    errors=["Trade is under review due to compliance requirements"]
                )
            
            # Create notifications for trade creation
            from notifications.utils import create_p2p_notification
            
            # Determine buyer and seller display names
            buyer_name = trade.buyer_business.name if trade.buyer_business else f"{trade.buyer_user.first_name} {trade.buyer_user.last_name}".strip() or trade.buyer_user.username
            seller_name = trade.seller_business.name if trade.seller_business else f"{trade.seller_user.first_name} {trade.seller_user.last_name}".strip() or trade.seller_user.username
            
            # Notification for buyer
            buyer_user = trade.buyer_user if trade.buyer_user else (trade.buyer_business.accounts.first().user if trade.buyer_business else None)
            if buyer_user:
                create_p2p_notification(
                    notification_type='P2P_TRADE_STARTED',
                    user=buyer_user,
                    business=trade.buyer_business,
                    trade_id=str(trade.id),
                    offer_id=str(offer.id),
                    amount=str(trade.crypto_amount),
                    token_type=trade.offer.token_type,
                    counterparty_name=seller_name,
                    additional_data={
                        'fiat_amount': str(trade.fiat_amount),
                        'fiat_currency': trade.offer.currency_code,
                        'payment_method': payment_method.display_name,
                        'trade_type': 'buy'
                    }
                )
            
            # Notification for seller
            seller_user = trade.seller_user if trade.seller_user else (trade.seller_business.accounts.first().user if trade.seller_business else None)
            if seller_user:
                create_p2p_notification(
                    notification_type='P2P_TRADE_STARTED',
                    user=seller_user,
                    business=trade.seller_business,
                    trade_id=str(trade.id),
                    offer_id=str(offer.id),
                    amount=str(trade.crypto_amount),
                    token_type=trade.offer.token_type,
                    counterparty_name=buyer_name,
                    additional_data={
                        'fiat_amount': str(trade.fiat_amount),
                        'fiat_currency': trade.offer.currency_code,
                        'payment_method': payment_method.display_name,
                        'trade_type': 'sell'
                    }
                )
            
            # Create escrow record for this trade
            from .models import P2PEscrow
            escrow = P2PEscrow.objects.create(
                trade=trade,
                escrow_amount=input.cryptoAmount,
                token_type=offer.token_type,
                is_escrowed=False,  # Will be set to True when blockchain confirms escrow
                is_released=False
            )
            
            # Escrow will be funded via on-chain transaction submitted by the client
            # through WebSocket (p2p_session). We do not mark as escrowed here.
            escrow.save()

            # No available amount tracking; removed
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
    @graphql_require_aml()
    @graphql_require_kyc('p2p_trade')
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

            # Get JWT context with validation and permission check
            from users.jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission='manage_p2p')
            if not jwt_context:
                return UpdateP2PTradeStatus(
                    trade=None,
                    success=False,
                    errors=["No access or permission to manage P2P trades"]
                )
            active_account_type = jwt_context['account_type']
            active_account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')
            
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

            # Server no longer auto-accepts on seller share. Buyer must accept with a user-signed AppCall.
            
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

            # Create notifications for status updates
            from notifications.utils import create_p2p_notification
            
            # Determine buyer and seller display names
            buyer_name = trade.buyer_business.name if trade.buyer_business else f"{trade.buyer_user.first_name} {trade.buyer_user.last_name}".strip() or trade.buyer_user.username
            seller_name = trade.seller_business.name if trade.seller_business else f"{trade.seller_user.first_name} {trade.seller_user.last_name}".strip() or trade.seller_user.username
            
            # Get the other party's user
            if is_buyer:
                other_party_user = trade.seller_user if trade.seller_user else (trade.seller_business.accounts.first().user if trade.seller_business else None)
                other_party_name = seller_name
            else:
                other_party_user = trade.buyer_user if trade.buyer_user else (trade.buyer_business.accounts.first().user if trade.buyer_business else None)
                other_party_name = buyer_name
            
            # Create notifications based on status change
            if input.status == 'PAYMENT_SENT' and is_buyer:
                # Buyer marked payment as sent - notify seller
                if other_party_user:
                    create_p2p_notification(
                        notification_type='P2P_PAYMENT_CONFIRMED',
                        user=other_party_user,
                        business=trade.seller_business,  # Pass seller's business context
                        trade_id=str(trade.id),
                        offer_id=str(trade.offer.id),
                        amount=str(trade.crypto_amount),
                        token_type=trade.offer.token_type,
                        counterparty_name=buyer_name,
                        additional_data={
                            'fiat_amount': str(trade.fiat_amount),
                            'fiat_currency': trade.offer.currency_code,
                            'payment_reference': input.payment_reference or '',
                            'payment_notes': input.payment_notes or ''
                        }
                    )
            
            elif input.status == 'PAYMENT_CONFIRMED' and is_seller:
                # Seller confirmed payment received - notify buyer
                if other_party_user:
                    create_p2p_notification(
                        notification_type='P2P_PAYMENT_CONFIRMED',
                        user=other_party_user,
                        business=trade.buyer_business,  # Pass buyer's business context
                        trade_id=str(trade.id),
                        offer_id=str(trade.offer.id),
                        amount=str(trade.crypto_amount),
                        token_type=trade.offer.token_type,
                        counterparty_name=seller_name,
                        additional_data={
                            'fiat_amount': str(trade.fiat_amount),
                            'fiat_currency': trade.offer.currency_code,
                            'message': 'El vendedor ha confirmado recibir el pago'
                        }
                    )
            
            elif input.status == 'CRYPTO_RELEASED' and is_seller:
                # Seller released crypto - notify buyer
                if other_party_user:
                    create_p2p_notification(
                        notification_type='P2P_CRYPTO_RELEASED',
                        user=other_party_user,
                        business=trade.buyer_business,  # Pass buyer's business context
                        trade_id=str(trade.id),
                        offer_id=str(trade.offer.id),
                        amount=str(trade.crypto_amount),
                        token_type=trade.offer.token_type,
                        counterparty_name=seller_name,
                        additional_data={
                            'fiat_amount': str(trade.fiat_amount),
                            'fiat_currency': trade.offer.currency_code
                        }
                    )
            
            elif input.status == 'COMPLETED':
                # Trade completed - notify both parties
                buyer_user = trade.buyer_user if trade.buyer_user else (trade.buyer_business.accounts.first().user if trade.buyer_business else None)
                seller_user = trade.seller_user if trade.seller_user else (trade.seller_business.accounts.first().user if trade.seller_business else None)
                
                if buyer_user:
                    create_p2p_notification(
                        notification_type='P2P_TRADE_COMPLETED',
                        user=buyer_user,
                        business=trade.buyer_business,  # Pass buyer's business context
                        trade_id=str(trade.id),
                        offer_id=str(trade.offer.id),
                        amount=str(trade.crypto_amount),
                        token_type=trade.offer.token_type,
                        counterparty_name=seller_name,
                        additional_data={
                            'fiat_amount': str(trade.fiat_amount),
                            'fiat_currency': trade.offer.currency_code,
                            'trade_type': 'buy'
                        }
                    )
                
                if seller_user:
                    create_p2p_notification(
                        notification_type='P2P_TRADE_COMPLETED',
                        user=seller_user,
                        business=trade.seller_business,  # Pass seller's business context
                        trade_id=str(trade.id),
                        offer_id=str(trade.offer.id),
                        amount=str(trade.crypto_amount),
                        token_type=trade.offer.token_type,
                        counterparty_name=buyer_name,
                        additional_data={
                            'fiat_amount': str(trade.fiat_amount),
                            'fiat_currency': trade.offer.currency_code,
                            'trade_type': 'sell'
                        }
                    )
            
            elif input.status == 'CANCELLED':
                # Trade cancelled - notify the other party
                if other_party_user:
                    # Pass the other party's business context
                    other_party_business = trade.seller_business if is_buyer else trade.buyer_business
                    create_p2p_notification(
                        notification_type='P2P_TRADE_CANCELLED',
                        user=other_party_user,
                        business=other_party_business,
                        trade_id=str(trade.id),
                        offer_id=str(trade.offer.id),
                        amount=str(trade.crypto_amount),
                        token_type=trade.offer.token_type,
                        counterparty_name=buyer_name if is_buyer else seller_name,
                        additional_data={
                            'fiat_amount': str(trade.fiat_amount),
                            'fiat_currency': trade.offer.currency_code,
                            'cancelled_by': 'buyer' if is_buyer else 'seller'
                        }
                    )
            
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
            # If we have a known expires_at (e.g., after accept or extension), include it
            try:
                if getattr(trade, 'expires_at', None):
                    broadcast_data['expires_at'] = trade.expires_at.isoformat()
            except Exception:
                pass
            
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

            # Get JWT context with validation and permission check
            from users.jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission='manage_p2p')
            if not jwt_context:
                return SendP2PMessage(
                    message=None,
                    success=False,
                    errors=["No access or permission to manage P2P trades"]
                )
            active_account_type = jwt_context['account_type']
            active_account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')
            
            print(f"SendP2PMessage - JWT account context: type={active_account_type}, index={active_account_index}, business_id={business_id}")
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
            
            # Get JWT context with validation and permission check
            from users.jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission='manage_p2p')
            if not jwt_context:
                return RateP2PTrade(
                    rating=None,
                    trade=None,
                    success=False,
                    errors=["No access or permission to manage P2P trades"]
                )
            active_account_type = jwt_context['account_type']
            active_account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')
            
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

"""
Removed: HTTP mutation for opening disputes.
Clients must use WebSocket prepare/submit flow to open disputes on-chain.
"""


class PresignedUploadInfo(graphene.ObjectType):
    url = graphene.String()
    key = graphene.String()
    method = graphene.String()
    headers = graphene.JSONString()
    expires_in = graphene.Int()
    fields = graphene.JSONString()  # For presigned POST
    confio_code = graphene.String()


class RequestDisputeEvidenceUpload(graphene.Mutation):
    class Arguments:
        trade_id = graphene.ID(required=True)
        filename = graphene.String(required=False)
        content_type = graphene.String(required=False, default_value='video/mp4')
        sha256 = graphene.String(required=False, description="Client-computed SHA-256 for metadata")

    upload = graphene.Field(PresignedUploadInfo)
    success = graphene.Boolean()
    error = graphene.String()

    @classmethod
    def mutate(cls, root, info, trade_id, filename=None, content_type='video/mp4', sha256=None):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return RequestDisputeEvidenceUpload(upload=None, success=False, error="Authentication required")

        trade = P2PTrade.objects.filter(id=trade_id).first()
        if not trade:
            return RequestDisputeEvidenceUpload(upload=None, success=False, error="Trade not found")
        # Must be one of the parties (user or through business account)
        if user not in [trade.buyer_user, trade.seller_user]:
            if not (
                (trade.buyer_business and trade.buyer_business.accounts.filter(user=user).exists()) or
                (trade.seller_business and trade.seller_business.accounts.filter(user=user).exists())
            ):
                return RequestDisputeEvidenceUpload(upload=None, success=False, error="Access denied")

        if content_type not in ['video/mp4', 'video/quicktime']:
            return RequestDisputeEvidenceUpload(upload=None, success=False, error="Unsupported content type")

        try:
            prefix = getattr(settings, 'AWS_S3_DISPUTE_PREFIX', 'disputes/')
            prefix = getattr(settings, 'AWS_S3_DISPUTE_PREFIX', '')
            base = f"{str(trade_id)}" if not prefix else f"{prefix}{trade_id}"
            key = build_s3_key(base, (filename or 'evidence.mp4'))
            metadata = {
                'trade-id': str(trade_id),
                'uploader-id': str(user.id),
            }
            if sha256:
                metadata['sha256'] = sha256
            # Ensure dispute exists and code is available
            from .models import P2PDispute
            dispute = getattr(trade, 'dispute_details', None)
            if not dispute:
                dispute = P2PDispute.objects.create(
                    trade=trade,
                    initiator_user=user,
                    reason='Evidence pending',
                    priority=2,
                )
            code = dispute.evidence_code
            now = timezone.now()
            if not code or not dispute.code_expires_at or dispute.code_expires_at <= now:
                code = f"D-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
                dispute.evidence_code = code
                dispute.code_generated_at = now
                # 2 hours validity
                dispute.code_expires_at = now + timezone.timedelta(hours=2)
                dispute.save(update_fields=['evidence_code', 'code_generated_at', 'code_expires_at', 'last_updated'])
            metadata['confio-code'] = code
            dispute_bucket = getattr(settings, 'AWS_DISPUTE_BUCKET', None)
            # Prefer presigned POST for mobile-friendliness; client can also handle PUT if needed
            try:
                from security.s3_utils import generate_presigned_post
                # Enforce max 200MB at S3 level
                max_bytes = 200 * 1024 * 1024
                presigned = generate_presigned_post(
                    key=key,
                    content_type=content_type,
                    metadata=metadata,
                    bucket=dispute_bucket,
                    conditions=[["content-length-range", 0, max_bytes]],
                )
            except Exception:
                presigned = generate_presigned_put(key=key, content_type=content_type, metadata=metadata, bucket=dispute_bucket)
            return RequestDisputeEvidenceUpload(
                upload=PresignedUploadInfo(
                    url=presigned['url'],
                    key=presigned['key'],
                    method=presigned['method'],
                    headers=presigned.get('headers'),
                    fields=presigned.get('fields'),
                    expires_in=presigned['expires_in'],
                    confio_code=code,
                ),
                success=True,
                error=None,
            )
        except Exception as e:
            return RequestDisputeEvidenceUpload(upload=None, success=False, error=str(e))


class AttachDisputeEvidence(graphene.Mutation):
    class Arguments:
        trade_id = graphene.ID(required=True)
        key = graphene.String(required=True)
        size = graphene.Int(required=False)
        sha256 = graphene.String(required=False)
        etag = graphene.String(required=False)

    dispute = graphene.Field('p2p_exchange.schema.P2PDisputeType')
    success = graphene.Boolean()
    error = graphene.String()

    @classmethod
    def mutate(cls, root, info, trade_id, key, size=None, sha256=None, etag=None):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return AttachDisputeEvidence(dispute=None, success=False, error="Authentication required")

        trade = P2PTrade.objects.filter(id=trade_id).first()
        if not trade:
            return AttachDisputeEvidence(dispute=None, success=False, error="Trade not found")
        if user not in [trade.buyer_user, trade.seller_user]:
            if not (
                (trade.buyer_business and trade.buyer_business.accounts.filter(user=user).exists()) or
                (trade.seller_business and trade.seller_business.accounts.filter(user=user).exists())
            ):
                return AttachDisputeEvidence(dispute=None, success=False, error="Access denied")

        dispute = getattr(trade, 'dispute_details', None)
        if not dispute:
            # Create a minimal dispute record if missing
            dispute = P2PDispute.objects.create(
                trade=trade,
                initiator_user=user,
                reason='Evidence submitted',
                priority=2,
            )

        # Validate S3 object in dispute bucket before attaching
        dispute_bucket = getattr(settings, 'AWS_DISPUTE_BUCKET', None)
        try:
            from security.s3_utils import head_object
            head = head_object(key=key, bucket=dispute_bucket)
        except Exception as e:
            return AttachDisputeEvidence(dispute=None, success=False, error=f"Unable to read evidence object: {e}")

        # Constraints: content type and size
        allowed_types = ['video/mp4', 'video/quicktime']
        if (head.get('content_type') or '') not in allowed_types:
            return AttachDisputeEvidence(dispute=None, success=False, error="Unsupported content type; only screen recordings (mp4/mov) are accepted")
        max_bytes = 200 * 1024 * 1024
        if (head.get('content_length') or 0) > max_bytes:
            return AttachDisputeEvidence(dispute=None, success=False, error="File too large; max 200MB")

        # Retrieve object metadata; do not fail hard on mismatches
        md = head.get('metadata') or {}
        # If client provided sha256, ensure it matches metadata (if present)
        if sha256 and md.get('sha256') and md.get('sha256') != sha256:
            pass

        # Build URL pointing to the dispute bucket
        url = public_s3_url(key, bucket=dispute_bucket)
        # Persist evidence record
        try:
            from .models import P2PDisputeEvidence
            # Determine uploader context (personal vs business)
            uploader_business = None
            try:
                from users.jwt_context import get_jwt_business_context_with_validation
                ctx = get_jwt_business_context_with_validation(info, required_permission=None) or {}
                if ctx.get('account_type') == 'business' and ctx.get('business_id'):
                    from users.models import Business
                    uploader_business = Business.objects.filter(id=ctx.get('business_id')).first()
            except Exception:
                pass
            ct = head.get('content_type') or ''
            sz = head.get('content_length') or size or None
            P2PDisputeEvidence.objects.create(
                dispute=dispute,
                trade=trade,
                uploader_user=user,
                uploader_business=uploader_business,
                s3_bucket=(dispute_bucket or ''),
                s3_key=key,
                url=url,
                content_type=ct,
                size_bytes=sz,
                sha256=(md.get('sha256') or sha256 or ''),
                etag=(head.get('etag') or etag or ''),
                confio_code=md.get('confio-code') or '',
                metadata=md or {},
                source='mobile',
                status='validated',
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to create P2PDisputeEvidence for trade {trade_id}, key {key}: {e}")
            # Continue; legacy list below still records URL

        # Maintain legacy URL list
        evidence = list(dispute.evidence_urls or [])
        evidence.append(url)
        dispute.evidence_urls = evidence
        dispute.save(update_fields=['evidence_urls', 'last_updated'])

        return AttachDisputeEvidence(dispute=dispute, success=True, error=None)


class GetDisputeEvidenceCodePayload(graphene.ObjectType):
    success = graphene.Boolean()
    error = graphene.String()
    confio_code = graphene.String()
    expires_at = graphene.DateTime()


class GetDisputeEvidenceCode(graphene.Mutation):
    class Arguments:
        trade_id = graphene.ID(required=True)

    Output = GetDisputeEvidenceCodePayload

    @classmethod
    def mutate(cls, root, info, trade_id):
        user = getattr(info.context, 'user', None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return GetDisputeEvidenceCodePayload(success=False, error="Authentication required")

        trade = P2PTrade.objects.filter(id=trade_id).first()
        if not trade:
            return GetDisputeEvidenceCodePayload(success=False, error="Trade not found")
        if user not in [trade.buyer_user, trade.seller_user]:
            if not (
                (trade.buyer_business and trade.buyer_business.accounts.filter(user=user).exists()) or
                (trade.seller_business and trade.seller_business.accounts.filter(user=user).exists())
            ):
                return GetDisputeEvidenceCodePayload(success=False, error="Access denied")

        from .models import P2PDispute
        dispute = getattr(trade, 'dispute_details', None)
        if not dispute:
            dispute = P2PDispute.objects.create(
                trade=trade,
                initiator_user=user,
                reason='Evidence pending',
                priority=2,
            )
        now = timezone.now()
        code = dispute.evidence_code
        if not code or not dispute.code_expires_at or dispute.code_expires_at <= now:
            code = f"D-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            dispute.evidence_code = code
            dispute.code_generated_at = now
            dispute.code_expires_at = now + timezone.timedelta(hours=2)
            dispute.save(update_fields=['evidence_code', 'code_generated_at', 'code_expires_at', 'last_updated'])
        return GetDisputeEvidenceCodePayload(success=True, error=None, confio_code=code, expires_at=dispute.code_expires_at)

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
            
            # Get JWT context with validation and permission check
            from users.jwt_context import get_jwt_business_context_with_validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission='manage_p2p')
            if not jwt_context:
                return ConfirmP2PTradeStep(
                    confirmation=None,
                    trade=None,
                    success=False,
                    errors=["No access or permission to manage P2P trades"]
                )
            active_account_type = jwt_context['account_type']
            active_account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')
            
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
                    
                    # Auto-complete the trade when seller confirms payment
                    # In a real implementation, this would trigger the blockchain release
                    trade.status = 'COMPLETED'
                    trade.completed_at = timezone.now()
                    
                    # Update escrow status
                    if hasattr(trade, 'escrow'):
                        escrow = trade.escrow
                        escrow.is_released = True
                        escrow.released_at = timezone.now()
                        escrow.save()
                        
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
                
                # Create notifications based on status change
                from notifications.utils import create_p2p_notification
                from notifications.models import NotificationType as NotificationTypeChoices
                
                # Get the other party info
                if is_buyer:
                    other_user = trade.seller_user
                    other_name = trade.seller_display_name
                else:
                    other_user = trade.buyer_user
                    other_name = trade.buyer_display_name
                
                # Send notification based on status
                notification_data = {
                    'amount': str(trade.crypto_amount),
                    'token_type': trade.offer.token_type,
                    'trade_id': str(trade.id),
                    'counterparty_name': other_name,
                    'fiat_amount': str(trade.fiat_amount),
                    'fiat_currency': trade.offer.currency_code,
                    'payment_method': trade.payment_method.name if trade.payment_method else '',
                    'trader_name': trade.seller_display_name if is_buyer else trade.buyer_display_name,
                    'trader_phone': trade.seller_user.phone_number if is_buyer and trade.seller_user else trade.buyer_user.phone_number if is_seller and trade.buyer_user else None,
                    'counterparty_phone': other_user.phone_number if other_user else None
                }
                
                if trade.status == 'PAYMENT_SENT':
                    # Notify seller that buyer marked as paid
                    # Get seller user (either direct user or from business account)
                    seller_user = trade.seller_user if trade.seller_user else (trade.seller_business.accounts.first().user if trade.seller_business else None)
                    if seller_user:
                        create_p2p_notification(
                            notification_type=NotificationTypeChoices.P2P_PAYMENT_CONFIRMED,
                            user=seller_user,
                            business=trade.seller_business,
                            trade_id=str(trade.id),
                            amount=str(trade.crypto_amount),
                            token_type=trade.offer.token_type,
                            counterparty_name=trade.buyer_display_name,
                            additional_data=notification_data
                        )
                elif trade.status == 'PAYMENT_CONFIRMED':
                    # This case won't happen anymore as we auto-complete on PAYMENT_RECEIVED
                    pass
                elif trade.status == 'COMPLETED':
                    # When trade is completed, send completion notification to both parties
                    # Both buyer and seller get "Intercambio Completado" notification
                    # Get buyer user (either direct user or from business account)
                    buyer_user = trade.buyer_user if trade.buyer_user else (trade.buyer_business.accounts.first().user if trade.buyer_business else None)
                    if buyer_user:
                        create_p2p_notification(
                            notification_type=NotificationTypeChoices.P2P_TRADE_COMPLETED,
                            user=buyer_user,
                            business=trade.buyer_business,
                            trade_id=str(trade.id),
                            amount=str(trade.crypto_amount),
                            token_type=trade.offer.token_type,
                            counterparty_name=trade.seller_display_name,
                            additional_data=notification_data
                        )
                    # Get seller user (either direct user or from business account)
                    seller_user = trade.seller_user if trade.seller_user else (trade.seller_business.accounts.first().user if trade.seller_business else None)
                    if seller_user:
                        create_p2p_notification(
                            notification_type=NotificationTypeChoices.P2P_TRADE_COMPLETED,
                            user=seller_user,
                            business=trade.seller_business,
                            trade_id=str(trade.id),
                            amount=str(trade.crypto_amount),
                            token_type=trade.offer.token_type,
                            counterparty_name=trade.buyer_display_name,
                            additional_data=notification_data
                        )
                
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
                    f'trade_chat_{trade.id}',
                    {
                        'type': 'trade_status_update',
                        'status': trade.status,
                        'updated_by': str(user.id),
                        'payment_reference': '',
                        'payment_notes': ''
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
    my_p2p_offers = graphene.List(P2POfferType)
    my_p2p_trades = graphene.Field(
        P2PTradePaginatedType, 
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
                
                # Get JWT context for account determination
                from users.jwt_context import get_jwt_business_context_with_validation
                try:
                    jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
                    active_account_type = jwt_context['account_type']
                    active_account_index = jwt_context['account_index']
                    business_id = jwt_context.get('business_id')
                except:
                    # Fallback for unauthenticated users
                    active_account_type = 'personal'
                    active_account_index = 0
                    business_id = None
                
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

    def resolve_my_p2p_offers(self, info):
        """Resolve P2P offers using JWT account context"""
        from users.jwt_context import get_jwt_business_context_with_validation
        from django.db.models import Q
        from users.models import Account, Business
        
        # Get JWT context with validation
        jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
        if not jwt_context:
            return []
            
        # Get the user from the request
        user = info.context.user
        if not user or not user.is_authenticated:
            return []
            
        account_type = jwt_context['account_type']
        account_index = jwt_context['account_index']
        business_id = jwt_context.get('business_id')
        
        print(f"P2P offers resolver - JWT context: user_id={user.id}, account_type={account_type}, account_index={account_index}, business_id={business_id}")
        
        if account_type == 'business' and business_id:
            # For business accounts, filter by business using JWT business_id
            from users.models import Business
            try:
                business = Business.objects.get(id=business_id)
                print(f"P2P offers resolver - Filtering offers for business id={business.id}, name={business.name}")
                return P2POffer.objects.filter(
                    offer_business=business
                ).order_by('-created_at')
            except Business.DoesNotExist:
                print(f"P2P offers resolver - Business not found: {business_id}")
                return []
        else:
            # For personal accounts, filter by user and exclude business offers
            print(f"P2P offers resolver - Filtering personal offers for user {user.id}")
            return P2POffer.objects.filter(
                Q(offer_user=user) | Q(user=user)  # Include legacy offers
            ).exclude(
                offer_business__isnull=False  # Exclude business offers
            ).order_by('-created_at')

    def resolve_my_p2p_trades(self, info, offset=0, limit=10):
        """Resolve P2P trades using JWT account context"""
        try:
            from users.jwt_context import get_jwt_business_context_with_validation
            from users.models import Business
            
            # Get JWT context with validation
            jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
            if not jwt_context:
                return P2PTradePaginatedType(
                    trades=[],
                    total_count=0,
                    has_more=False,
                    offset=offset,
                    limit=limit,
                    active_count=0
                )
                
            # Get the user from the request
            user = info.context.user
            if not user or not user.is_authenticated:
                return P2PTradePaginatedType(
                    trades=[],
                    total_count=0,
                    has_more=False,
                    offset=offset,
                    limit=limit,
                    active_count=0
                )
                
            account_type = jwt_context['account_type']
            account_index = jwt_context['account_index']
            business_id = jwt_context.get('business_id')
            
            print(f"P2P trades resolver - JWT context: user_id={user.id}, account_type={account_type}, account_index={account_index}, business_id={business_id}")
            
            if account_type == 'business' and business_id:
                # For business accounts, filter by business using JWT business_id
                try:
                    business = Business.objects.get(id=business_id)
                    print(f"P2P trades resolver - Filtering trades for business id={business.id}, name={business.name}")
                    
                    # Show only business trades for this specific business, excluding cancelled
                    base_trades = P2PTrade.objects.filter(
                        models.Q(buyer_business=business) | models.Q(seller_business=business)
                    ).exclude(status='CANCELLED').prefetch_related('ratings')
                    
                    # Apply sorting
                    trades = Query._get_sorted_trades_queryset(base_trades)
                    
                    total_count = trades.count()
                    active_count = trades.exclude(status='COMPLETED').count()
                    
                    print(f"P2P trades resolver - Found {total_count} business trades ({active_count} active), returning offset={offset}, limit={limit}")
                    paginated_trades = trades[offset:offset+limit]
                    
                    return P2PTradePaginatedType(
                        trades=paginated_trades,
                        total_count=total_count,
                        has_more=(offset + limit) < total_count,
                        offset=offset,
                        limit=limit,
                        active_count=active_count
                    )
                except Business.DoesNotExist:
                    print(f"P2P trades resolver - Business not found: {business_id}")
                    return P2PTradePaginatedType(
                        trades=[],
                        total_count=0,
                        has_more=False,
                        offset=offset,
                        limit=limit,
                        active_count=0
                    )
            else:
                # For personal accounts, filter by user and exclude business trades
                print(f"P2P trades resolver - Filtering personal trades for user {user.id}")
                
                # Show only personal trades for this user, excluding cancelled
                base_trades = P2PTrade.objects.filter(
                    models.Q(buyer_user=user) | models.Q(seller_user=user)
                ).exclude(status='CANCELLED').prefetch_related('ratings')
                
                # Apply sorting
                trades = Query._get_sorted_trades_queryset(base_trades)
                
                total_count = trades.count()
                active_count = trades.exclude(status='COMPLETED').count()
                
                print(f"P2P trades resolver - Found {total_count} personal trades ({active_count} active), returning offset={offset}, limit={limit}")
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
            print(f"P2P trades resolver - Error: {str(e)}")
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
        # Prioritize ongoing trades over rating-only or completed
        status_ordering = Case(
            When(status='DISPUTED', then=1),
            When(status='PENDING', then=2),
            When(status='PAYMENT_PENDING', then=3),
            When(status='PAYMENT_SENT', then=4),
            When(status='PAYMENT_CONFIRMED', then=5),
            # Treat CRYPTO_RELEASED as near-complete (rating flow in legacy), after ongoing states
            When(status='CRYPTO_RELEASED', then=6),
            When(status='COMPLETED', then=7),
            default=999,
            output_field=IntegerField()
        )
        
        # Order by status priority, then most recently updated, then most recently created
        return base_queryset.annotate(
            status_priority=status_ordering
        ).order_by('status_priority', '-updated_at', '-created_at')

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
        
        # Get JWT context with validation and permission check
        from users.jwt_context import get_jwt_business_context_with_validation
        jwt_context = get_jwt_business_context_with_validation(info, required_permission='manage_p2p')
        if not jwt_context:
            return ToggleFavoriteTrader(
                success=False,
                is_favorite=False,
                message="Invalid JWT context, access denied, or lacking permission"
            )
            
        active_account_type = jwt_context['account_type']
        active_account_index = jwt_context['account_index']
        business_id = jwt_context.get('business_id')
        employee_record = jwt_context.get('employee_record')
        
        try:
            # Determine favoriter_business if acting as business account
            favoriter_business = None
            if active_account_type == 'business' and business_id:
                # Permission already checked in get_jwt_business_context_with_validation
                from users.models import Business
                favoriter_business = Business.objects.get(id=business_id)
            
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
    # dispute_p2p_trade removed: use WebSocket on-chain flow
    request_dispute_evidence_upload = RequestDisputeEvidenceUpload.Field()
    attach_dispute_evidence = AttachDisputeEvidence.Field()
    get_dispute_evidence_code = GetDisputeEvidenceCode.Field()
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

            # Send notifications to both parties about the resolution
            try:
                from notifications.utils import create_p2p_dispute_resolution_notifications
                create_p2p_dispute_resolution_notifications(
                    trade=trade,
                    resolution_type=resolution_type,
                    resolution_amount=str(getattr(trade, 'crypto_amount', '')),
                    admin_notes=resolution_notes or '',
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Failed to send dispute resolution notifications')

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
