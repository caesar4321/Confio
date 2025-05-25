from users import schema as users_schema
from prover import schema as prover_schema
from telegram_verification import schema as telegram_verification_schema
import graphene

class Query(users_schema.Query, graphene.ObjectType):
	pass

class Mutation(
	users_schema.Mutation,
	prover_schema.Mutation,
	telegram_verification_schema.Mutation,
	graphene.ObjectType
):
	pass

schema = graphene.Schema(
	query=Query,
	mutation=Mutation,
	types=[users_schema.UserType]
)

__all__ = ['schema'] 