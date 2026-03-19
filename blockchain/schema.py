"""
Blockchain GraphQL schema - Algorand operations
"""
import graphene
from graphene_django import DjangoObjectType
from graphql import GraphQLError
from blockchain.models import PendingAutoSwap
from users.models import Account
from .mutations import (
    EnsureAlgorandReadyMutation,
    GenerateOptInTransactionsMutation,
    GenerateAppOptInTransactionMutation,
    OptInToAssetMutation,
    OptInToAssetByTypeMutation,
    CheckAssetOptInsQuery,
    AlgorandSponsoredSendMutation,
    SubmitSponsoredGroupMutation,
    AlgorandSponsoredOptInMutation,
    CheckSponsorHealthQuery,
    CheckBusinessOptInMutation,
    CompleteBusinessOptInMutation,
    SubmitBusinessOptInGroupMutation,
    PrepareAtomicMigrationMutation,
    BuildAutoSwapTransactionsMutation,
    SubmitAutoSwapTransactionsMutation,
    BuildBurnAndSendMutation,
)
from .payment_mutations import (
    CreateSponsoredPaymentMutation,
    SubmitSponsoredPaymentMutation,
)
from .invite_send_mutations import (
    PrepareInviteForPhone,
    SubmitInviteForPhone,
    ClaimInviteForPhoneField,
    InviteReceiptType,
    PendingInviteType,
    get_invite_receipt_for_phone,
    get_all_pending_invites_for_phone,
)
from .p2p_trade_mutations import P2PTradeMutations, P2PTradePrepareMutations


class Query(graphene.ObjectType):
    """Blockchain-related queries"""
    check_asset_opt_ins = graphene.Field(CheckAssetOptInsQuery)
    check_sponsor_health = graphene.Field(CheckSponsorHealthQuery)
    p2p_trade_box_exists = graphene.Field(graphene.Boolean, trade_id=graphene.String(required=True))
    invite_receipt_for_phone = graphene.Field(
        InviteReceiptType,
        phone=graphene.String(required=True),
        phone_country=graphene.String(required=False)
    )
    all_pending_invites_for_phone = graphene.List(
        PendingInviteType,
        phone=graphene.String(required=True),
        phone_country=graphene.String(required=False)
    )
    pending_auto_swap = graphene.Field(
        lambda: PendingAutoSwapType,
        account_id=graphene.ID(required=False),
    )
    
    def resolve_check_asset_opt_ins(self, info):
        return CheckAssetOptInsQuery()
    
    def resolve_check_sponsor_health(self, info):
        return CheckSponsorHealthQuery()

    def resolve_p2p_trade_box_exists(self, info, trade_id: str):
        """Return True if the P2P trade box exists on-chain for the given trade_id."""
        try:
            from blockchain.algorand_config import get_algod_client
            client = get_algod_client()
            app_id = getattr(settings, 'ALGORAND_P2P_TRADE_APP_ID', 0)
            if not app_id:
                return False
            # Will raise if not found
            client.application_box_by_name(app_id, trade_id.encode('utf-8'))
            return True
        except Exception:
            return False

    def resolve_invite_receipt_for_phone(self, info, phone, phone_country=None):
        user = info.context.user
        if not user or not user.is_authenticated:
            return None
        res = get_invite_receipt_for_phone(phone, phone_country)
        return InviteReceiptType(**res) if res else None

    def resolve_all_pending_invites_for_phone(self, info, phone, phone_country=None):
        user = info.context.user
        if not user or not user.is_authenticated:
            return []
        results = get_all_pending_invites_for_phone(phone, phone_country)
        return [PendingInviteType(**r) for r in results]

    def resolve_pending_auto_swap(self, info, account_id=None):
        user = info.context.user
        if not user or not user.is_authenticated:
            return None

        queryset = PendingAutoSwap.objects.filter(status='PENDING')
        if account_id:
            account = _resolve_account_for_pending_auto_swap(user=user, account_ref=account_id)
            if not account:
                return None
            queryset = queryset.filter(account=account)
        else:
            queryset = queryset.filter(actor_user=user)

        return queryset.select_related('account', 'usdc_deposit', 'conversion').order_by('-created_at').first()


class PendingAutoSwapType(DjangoObjectType):
    class Meta:
        model = PendingAutoSwap
        fields = (
            'id',
            'asset_type',
            'amount_micro',
            'amount_decimal',
            'status',
            'error_message',
            'source_address',
            'source_tx_hash',
            'created_at',
            'updated_at',
        )


class Mutation(graphene.ObjectType):
    """Blockchain-related mutations"""
    ensure_algorand_ready = EnsureAlgorandReadyMutation.Field()
    generate_opt_in_transactions = GenerateOptInTransactionsMutation.Field()
    generate_app_opt_in_transaction = GenerateAppOptInTransactionMutation.Field()
    opt_in_to_asset = OptInToAssetMutation.Field()
    opt_in_to_asset_by_type = OptInToAssetByTypeMutation.Field()
    algorand_sponsored_send = AlgorandSponsoredSendMutation.Field()
    algorand_sponsored_opt_in = AlgorandSponsoredOptInMutation.Field()
    submit_sponsored_group = SubmitSponsoredGroupMutation.Field()
    prepare_atomic_migration = PrepareAtomicMigrationMutation.Field()
    build_auto_swap_transactions = BuildAutoSwapTransactionsMutation.Field()
    submit_auto_swap_transactions = SubmitAutoSwapTransactionsMutation.Field()
    build_burn_and_send = BuildBurnAndSendMutation.Field()
    
    # Business opt-in mutations
    check_business_opt_in = CheckBusinessOptInMutation.Field()
    complete_business_opt_in = CompleteBusinessOptInMutation.Field()
    submit_business_opt_in_group = SubmitBusinessOptInGroupMutation.Field()
    
    # Payment contract mutations
    create_sponsored_payment = CreateSponsoredPaymentMutation.Field()
    submit_sponsored_payment = SubmitSponsoredPaymentMutation.Field()

    # Invite & Send contract mutations
    prepare_invite_for_phone = PrepareInviteForPhone.Field()
    submit_invite_for_phone = SubmitInviteForPhone.Field()
    claim_invite_for_phone = ClaimInviteForPhoneField

    # P2P Trade: HTTP GraphQL mutations removed in favor of WebSocket session
    # Use ws endpoint: /ws/p2p_session to prepare/submit P2P txns


__all__ = ['Query', 'Mutation']


def _resolve_account_for_pending_auto_swap(*, user, account_ref):
    raw = str(account_ref or '').strip()
    if not raw:
        return None

    if raw.isdigit():
        account = Account.objects.filter(id=raw, deleted_at__isnull=True).first()
        if not account:
            return None
        if account.account_type == 'personal':
            return account if account.user_id == user.id else None
        if account.account_type == 'business':
            is_owner = Account.objects.filter(
                user_id=user.id,
                business_id=account.business_id,
                account_type='business',
                deleted_at__isnull=True,
            ).exists()
            return account if is_owner else None
        return None

    parts = raw.split('_')
    if len(parts) == 2 and parts[0] == 'personal':
        try:
            account_index = int(parts[1])
        except ValueError:
            return None
        return Account.objects.filter(
            user_id=user.id,
            account_type='personal',
            account_index=account_index,
            deleted_at__isnull=True,
        ).first()

    if len(parts) == 3 and parts[0] == 'business':
        business_id, account_index_raw = parts[1], parts[2]
        try:
            account_index = int(account_index_raw)
        except ValueError:
            return None
        return Account.objects.filter(
            user_id=user.id,
            business_id=business_id,
            account_type='business',
            account_index=account_index,
            deleted_at__isnull=True,
        ).first()

    raise GraphQLError('Invalid account reference')
