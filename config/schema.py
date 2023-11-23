import graphene
from graphene_django.types import DjangoObjectType

class Query(DjangoObjectType):
	pass

class Mutation(DjangoObjectType):
	pass

class Subscription(DjangoObjectType):
	pass

schema = graphene.Schema(query=Query, mutation=Mutation, subscription=Subscription)