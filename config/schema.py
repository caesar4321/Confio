from users import schema as users_schema
from prover import schema as prover_schema
from telegram_verification import schema as telegram_verification_schema
import graphene
import logging

logger = logging.getLogger(__name__)

class Query(users_schema.Query, graphene.ObjectType):
	# Override the legalDocument field to make it public
	legalDocument = users_schema.Query.legalDocument

class Mutation(
	users_schema.Mutation,
	prover_schema.Mutation,
	telegram_verification_schema.Mutation,
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
]

schema = graphene.Schema(
	query=Query,
	mutation=Mutation,
	types=types
)

__all__ = ['schema'] 