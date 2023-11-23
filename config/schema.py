import graphene

class Query(graphene.ObjectType):
	pass

class Mutation(graphene.ObjectType):
	pass

class Subscription(graphene.ObjectType):
	pass

schema = graphene.Schema(query=Query, mutation=Mutation, subscription=Subscription)