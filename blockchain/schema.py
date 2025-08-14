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


class Query(graphene.ObjectType):
    """Blockchain-related queries"""
    check_asset_opt_ins = graphene.Field(CheckAssetOptInsQuery)
    check_sponsor_health = graphene.Field(CheckSponsorHealthQuery)
    
    def resolve_check_asset_opt_ins(self, info):
        return CheckAssetOptInsQuery()
    
    def resolve_check_sponsor_health(self, info):
        return CheckSponsorHealthQuery()


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


__all__ = ['Query', 'Mutation']
