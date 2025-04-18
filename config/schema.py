from users import schema as users_schema
from prover import schema as prover_schema
import graphene

class Query(users_schema.Query, graphene.ObjectType):
	pass

class Mutation(prover_schema.Mutation, graphene.ObjectType):
	pass

schema = graphene.Schema(query=Query, mutation=Mutation)

__all__ = ['schema'] 