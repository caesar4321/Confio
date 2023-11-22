import graphene
from users import schema as users_schema
from notifications import schema as notifications_schema
from finance import schema as finance_schema
from exchange import schema as exchange_schema
from shopping import schema as shopping_schema
from business import schema as business_schema
from analytics import schema as analytics_schema

class Query(users_schema.Query, notifications_schema.Query, finance_schema.Query, exchange_schema.Query, shopping_schema.Query, business_schema.Query, analytics_schema.Query,  graphene.ObjectType):
	pass

class Mutation(users_schema.Mutation, notifications_schema.Mutation, finance_schema.Mutation, exchange_schema.Mutation, shopping_schema.Mutation, analytics_schema.Mutation, graphene.ObjectType):
	pass

class Subscription(users_schema.Subscription, notifications_schema.Subscription, finance_schema.Subscription, exchange_schema.Subscription, shopping_schema.Subscription, graphene.ObjectType):
	pass

schema = graphene.Schema(query=Query, mutation=Mutation, subscription=Subscription)