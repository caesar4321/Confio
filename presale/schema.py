import graphene
from graphene_django import DjangoObjectType
from graphql_jwt.decorators import login_required
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from graphql import GraphQLError

from .models import PresalePhase, PresalePurchase, PresaleStats, UserPresaleLimit, PresaleSettings, PresaleWaitlist
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


class PresaleOnchainInfo(graphene.ObjectType):
    purchased = graphene.Float()
    claimed = graphene.Float()
    claimable = graphene.Float()
    locked = graphene.Boolean()


class PresaleQueries(graphene.ObjectType):
    """Queries for presale data"""
    
    is_presale_active = graphene.Boolean()
    is_presale_claims_unlocked = graphene.Boolean()
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
    my_presale_onchain_info = graphene.Field(PresaleOnchainInfo)
    
    def resolve_is_presale_active(self, info):
        """Check if presale is globally enabled - no login required for this check"""
        settings = PresaleSettings.get_settings()
        return settings.is_presale_active

    def resolve_is_presale_claims_unlocked(self, info):
        """Check if presale claims are globally unlocked - no login required for this check"""
        settings = PresaleSettings.get_settings()
        return settings.is_presale_claims_unlocked
    
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

    @login_required
    def resolve_my_presale_onchain_info(self, info):
        """Get purchased/claimed/claimable and locked status from on-chain state"""
        try:
            from users.models import Account
            from django.conf import settings as dj_settings
            from algosdk.v2client import algod
            from blockchain.algorand_account_manager import AlgorandAccountManager
            from contracts.presale.state_utils import decode_state, decode_local_state

            app_id = getattr(dj_settings, 'ALGORAND_PRESALE_APP_ID', None)
            if not app_id:
                return PresaleOnchainInfo(purchased=0.0, claimed=0.0, claimable=0.0, locked=True)

            user = info.context.user
            account = Account.objects.filter(user=user, account_type='personal', deleted_at__isnull=True).first()
            if not account or not account.algorand_address:
                return PresaleOnchainInfo(purchased=0.0, claimed=0.0, claimable=0.0, locked=True)

            algod_client = algod.AlgodClient(
                AlgorandAccountManager.ALGOD_TOKEN,
                AlgorandAccountManager.ALGOD_ADDRESS,
            )
            # Global locked flag
            app_info = algod_client.application_info(int(app_id))
            global_state = decode_state(app_info['params']['global-state'])
            locked = bool(global_state.get('locked', 1) == 1)

            # Local state
            acct_info = algod_client.account_info(account.algorand_address)
            local = decode_local_state(acct_info, int(app_id)) or {}
            purchased = float((local.get('user_confio', 0) or 0) / 10**6)
            claimed = float((local.get('claimed', 0) or 0) / 10**6)
            claimable = max(purchased - claimed, 0.0)
            return PresaleOnchainInfo(purchased=purchased, claimed=claimed, claimable=claimable, locked=locked)
        except Exception:
            return PresaleOnchainInfo(purchased=0.0, claimed=0.0, claimable=0.0, locked=True)


class PurchasePresaleTokens(graphene.Mutation):
    """Mutation to purchase CONFIO tokens during presale"""

    class Arguments:
        cusd_amount = graphene.Decimal(required=True)
        phase_number = graphene.Int(required=False)

    success = graphene.Boolean()
    message = graphene.String()
    purchase = graphene.Field(PresalePurchaseType)

    @login_required
    def mutate(self, info, cusd_amount, phase_number=None):
        # The presale purchase flow is implemented over WebSocket for a fully
        # sponsored, two-step (prepare/submit) UX similar to Pay/Send/Conversion.
        # Use ws endpoint /ws/presale_session to prepare and submit transactions.
        raise GraphQLError("Use WebSocket /ws/presale_session for presale purchases (prepare + submit)")


class JoinPresaleWaitlist(graphene.Mutation):
    """Mutation to join the presale waitlist"""

    class Arguments:
        pass

    success = graphene.Boolean()
    message = graphene.String()
    already_joined = graphene.Boolean()

    @login_required
    def mutate(self, info):
        user = info.context.user

        # Check if user already joined
        existing = PresaleWaitlist.objects.filter(user=user).first()
        if existing:
            return JoinPresaleWaitlist(
                success=True,
                message="Ya estás en la lista de espera. Te notificaremos cuando la preventa esté disponible.",
                already_joined=True
            )

        # Create new waitlist entry
        PresaleWaitlist.objects.create(user=user)

        return JoinPresaleWaitlist(
            success=True,
            message="¡Te has unido a la lista de espera! Te notificaremos cuando la preventa esté disponible.",
            already_joined=False
        )


class PresaleMutations(graphene.ObjectType):
    """Mutations for presale operations"""
    purchase_presale_tokens = PurchasePresaleTokens.Field()
    join_presale_waitlist = JoinPresaleWaitlist.Field()
