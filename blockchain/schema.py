"""
Blockchain GraphQL schema - Algorand operations
"""
import graphene
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
    SubmitBusinessOptInGroupMutation
)
from .payment_mutations import (
    CreateSponsoredPaymentMutation,
    SubmitSponsoredPaymentMutation,
    CreateDirectPaymentMutation
)
from .invite_send_mutations import (
    PrepareInviteForPhone,
    SubmitInviteForPhone,
    ClaimInviteForPhoneField,
    InviteReceiptType,
    get_invite_receipt_for_phone,
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
    
    def resolve_check_asset_opt_ins(self, info):
        return CheckAssetOptInsQuery()
    
    def resolve_check_sponsor_health(self, info):
        return CheckSponsorHealthQuery()

    def resolve_p2p_trade_box_exists(self, info, trade_id: str):
        """Return True if the P2P trade box exists on-chain for the given trade_id."""
        try:
            from algosdk.v2client import algod
            client = algod.AlgodClient(settings.ALGORAND_ALGOD_TOKEN, settings.ALGORAND_ALGOD_ADDRESS)
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
    
    # Business opt-in mutations
    check_business_opt_in = CheckBusinessOptInMutation.Field()
    complete_business_opt_in = CompleteBusinessOptInMutation.Field()
    submit_business_opt_in_group = SubmitBusinessOptInGroupMutation.Field()
    
    # Payment contract mutations
    create_sponsored_payment = CreateSponsoredPaymentMutation.Field()
    submit_sponsored_payment = SubmitSponsoredPaymentMutation.Field()
    create_direct_payment = CreateDirectPaymentMutation.Field()

    # Invite & Send contract mutations
    prepare_invite_for_phone = PrepareInviteForPhone.Field()
    submit_invite_for_phone = SubmitInviteForPhone.Field()
    claim_invite_for_phone = ClaimInviteForPhoneField

    # P2P Trade mutations
    prepare_p2p_create_trade = P2PTradeMutations.prepare_p2p_create_trade
    submit_p2p_create_trade = P2PTradeMutations.submit_p2p_create_trade
    accept_p2p_trade = P2PTradeMutations.accept_p2p_trade
    prepare_p2p_accept_trade = P2PTradeMutations.prepare_p2p_accept_trade
    submit_p2p_accept_trade = P2PTradeMutations.submit_p2p_accept_trade
    mark_p2p_trade_paid = P2PTradeMutations.mark_p2p_trade_paid
    confirm_p2p_trade_received = P2PTradeMutations.confirm_p2p_trade_received
    prepare_p2p_mark_paid = P2PTradePrepareMutations.prepare_p2p_mark_paid
    prepare_p2p_confirm_received = P2PTradePrepareMutations.prepare_p2p_confirm_received
    # Cancel expired trades
    prepare_p2p_cancel = P2PTradePrepareMutations.prepare_p2p_cancel
    cancel_p2p_trade = P2PTradeMutations.cancel_p2p_trade


__all__ = ['Query', 'Mutation']
