from users import schema as users_schema
from prover import schema as prover_schema
from telegram_verification import schema as telegram_verification_schema
from send import schema as send_schema
from payments import schema as payments_schema
from p2p_exchange import schema as p2p_exchange_schema
import graphene
import logging

logger = logging.getLogger(__name__)

class Query(users_schema.Query, send_schema.Query, payments_schema.Query, p2p_exchange_schema.Query, graphene.ObjectType):
	# Override the legalDocument field to make it public
	legalDocument = users_schema.Query.legalDocument

class Mutation(
	users_schema.Mutation,
	prover_schema.Mutation,
	telegram_verification_schema.Mutation,
	send_schema.Mutation,
	payments_schema.Mutation,
	p2p_exchange_schema.Mutation,
	graphene.ObjectType
):
	pass

# Register all types
types = [
	users_schema.UserType,
	users_schema.AccountType,
	users_schema.CountryCodeType,
	users_schema.BusinessCategoryType,
	users_schema.LegalDocumentType,
	send_schema.SendTransactionType,
	payments_schema.InvoiceType,
	payments_schema.PaymentTransactionType,
	p2p_exchange_schema.P2POfferType,
	p2p_exchange_schema.P2PTradeType,
	p2p_exchange_schema.P2PMessageType,
	p2p_exchange_schema.P2PPaymentMethodType,
	p2p_exchange_schema.P2PUserStatsType,
]

schema = graphene.Schema(
	query=Query,
	mutation=Mutation,
	types=types
)

__all__ = ['schema'] 