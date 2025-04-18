import graphene

class Query(graphene.ObjectType):
	ping = graphene.String()

	def resolve_ping(self, info):
		return "pong"