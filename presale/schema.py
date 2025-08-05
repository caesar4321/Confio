import graphene
from graphene_django import DjangoObjectType
from graphql_jwt.decorators import login_required
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from graphql import GraphQLError

from .models import PresalePhase, PresalePurchase, PresaleStats, UserPresaleLimit, PresaleSettings
from users.models import Account


class PresalePhaseType(DjangoObjectType):
    total_raised = graphene.Decimal()
    total_participants = graphene.Int()
    tokens_sold = graphene.Decimal()
    progress_percentage = graphene.Float()
    vision_points = graphene.List(graphene.String)
    status = graphene.String()
    
    class Meta:
        model = PresalePhase
        fields = '__all__'
    
    def resolve_status(self, info):
        return self.status
    
    def resolve_total_raised(self, info):
        return self.total_raised
    
    def resolve_total_participants(self, info):
        return self.total_participants
    
    def resolve_tokens_sold(self, info):
        return self.tokens_sold
    
    def resolve_progress_percentage(self, info):
        return float(self.progress_percentage)


class PresalePurchaseType(DjangoObjectType):
    class Meta:
        model = PresalePurchase
        fields = '__all__'


class PresaleStatsType(DjangoObjectType):
    class Meta:
        model = PresaleStats
        fields = '__all__'


class UserPresaleLimitType(DjangoObjectType):
    class Meta:
        model = UserPresaleLimit
        fields = '__all__'


class PresaleQueries(graphene.ObjectType):
    """Queries for presale data"""
    
    is_presale_active = graphene.Boolean()
    active_presale_phase = graphene.Field(PresalePhaseType)
    all_presale_phases = graphene.List(PresalePhaseType)
    presale_phase = graphene.Field(
        PresalePhaseType,
        phase_number=graphene.Int(required=True)
    )
    my_presale_purchases = graphene.List(PresalePurchaseType)
    my_presale_limit = graphene.Field(
        UserPresaleLimitType,
        phase_number=graphene.Int(required=True)
    )
    
    def resolve_is_presale_active(self, info):
        """Check if presale is globally enabled - no login required for this check"""
        settings = PresaleSettings.get_settings()
        return settings.is_presale_active
    
    @login_required
    def resolve_active_presale_phase(self, info):
        """Get the currently active presale phase"""
        # First check if presale is globally enabled
        settings = PresaleSettings.get_settings()
        if not settings.is_presale_active:
            return None
        return PresalePhase.objects.filter(status='active').first()
    
    @login_required
    def resolve_all_presale_phases(self, info):
        """Get all presale phases"""
        return PresalePhase.objects.all().order_by('phase_number')
    
    @login_required
    def resolve_presale_phase(self, info, phase_number):
        """Get a specific presale phase by number"""
        try:
            return PresalePhase.objects.get(phase_number=phase_number)
        except PresalePhase.DoesNotExist:
            return None
    
    @login_required
    def resolve_my_presale_purchases(self, info):
        """Get user's presale purchases"""
        user = info.context.user
        return PresalePurchase.objects.filter(user=user).select_related('phase')
    
    @login_required
    def resolve_my_presale_limit(self, info, phase_number):
        """Get user's purchase limit for a phase"""
        user = info.context.user
        try:
            phase = PresalePhase.objects.get(phase_number=phase_number)
            limit, _ = UserPresaleLimit.objects.get_or_create(
                user=user,
                phase=phase
            )
            return limit
        except PresalePhase.DoesNotExist:
            return None


class PurchasePresaleTokens(graphene.Mutation):
    """Mutation to purchase CONFIO tokens during presale"""
    
    class Arguments:
        cusd_amount = graphene.Decimal(required=True)
        phase_number = graphene.Int(required=False)
    
    success = graphene.Boolean()
    message = graphene.String()
    purchase = graphene.Field(PresalePurchaseType)
    
    @login_required
    @transaction.atomic
    def mutate(self, info, cusd_amount, phase_number=None):
        user = info.context.user
        
        # Get active phase or specified phase
        if phase_number:
            try:
                phase = PresalePhase.objects.get(
                    phase_number=phase_number,
                    status='active'
                )
            except PresalePhase.DoesNotExist:
                raise GraphQLError(f"Phase {phase_number} is not active")
        else:
            phase = PresalePhase.objects.filter(status='active').first()
            if not phase:
                raise GraphQLError("No active presale phase")
        
        # Validate amount
        if cusd_amount < phase.min_purchase:
            raise GraphQLError(
                f"Minimum purchase is {phase.min_purchase} cUSD"
            )
        
        if cusd_amount > phase.max_purchase:
            raise GraphQLError(
                f"Maximum purchase is {phase.max_purchase} cUSD"
            )
        
        # Check user's total purchases for this phase
        user_limit, _ = UserPresaleLimit.objects.get_or_create(
            user=user,
            phase=phase
        )
        
        if phase.max_per_user:
            if user_limit.total_purchased + cusd_amount > phase.max_per_user:
                remaining = phase.max_per_user - user_limit.total_purchased
                raise GraphQLError(
                    f"This would exceed your limit for Phase {phase.phase_number}. "
                    f"You can purchase up to {remaining} cUSD more."
                )
        
        # Get user's cUSD account
        try:
            cusd_account = user.accounts.filter(
                account_type='personal'
            ).first()
            
            if not cusd_account:
                raise GraphQLError("Personal account not found")
        except Exception as e:
            raise GraphQLError(f"Error finding account: {str(e)}")
        
        # Check cUSD balance (you'll need to implement this based on your balance tracking)
        # For now, assuming you have a method to get balance
        # cusd_balance = cusd_account.get_balance('cusd')
        # if cusd_balance < cusd_amount:
        #     raise GraphQLError("Insufficient cUSD balance")
        
        # Calculate CONFIO amount
        confio_amount = cusd_amount / phase.price_per_token
        
        # Create purchase record
        purchase = PresalePurchase.objects.create(
            user=user,
            phase=phase,
            cusd_amount=cusd_amount,
            confio_amount=confio_amount,
            price_per_token=phase.price_per_token,
            status='processing',
            from_address=cusd_account.aptos_address
        )
        
        # TODO: Execute blockchain transaction here
        # For now, we'll simulate success
        
        # Update purchase status
        purchase.complete_purchase(
            transaction_hash="0x" + "0" * 64  # Placeholder
        )
        
        # Update user's limit
        user_limit.total_purchased += cusd_amount
        user_limit.last_purchase_at = timezone.now()
        user_limit.save()
        
        # Update phase stats (could be done async)
        if hasattr(phase, 'stats'):
            phase.stats.update_stats()
        
        return PurchasePresaleTokens(
            success=True,
            message=f"Successfully purchased {confio_amount} CONFIO tokens!",
            purchase=purchase
        )


class PresaleMutations(graphene.ObjectType):
    """Mutations for presale operations"""
    purchase_presale_tokens = PurchasePresaleTokens.Field()