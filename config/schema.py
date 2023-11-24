import graphene
from users import schema as users_schema

class Query(users_schema.Query,graphene.ObjectType):
	pass

schema = graphene.Schema(query=Query)