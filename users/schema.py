import graphene
import channels_graphql_ws
from graphene_django.types import DjangoObjectType
from . import Confio_Terms_of_Service, Confio_Privacy_Policy, Confio_Frequently_Asked_Questions
import json

class Query(graphene.ObjectType):
	terms_of_service = graphene.String(language=graphene.String())
	privacy_policy = graphene.String(language=graphene.String())
	frequently_asked_questions = graphene.String(language=graphene.String())
	update_online = graphene.Boolean()


	def resolve_terms_of_service(self, info, **kwargs):
		language = kwargs.get('language')
		safe_language = language.lower()[:2]
		try:
			Confio_Terms_of_Service.data[safe_language]
		except KeyError:
			safe_language = 'en'
		return json.dumps(Confio_Terms_of_Service.data[safe_language])
		

	def resolve_privacy_policy(self, info, **kwargs):
		language = kwargs.get('language')
		safe_language = language.lower()[:2]
		try:
			Confio_Privacy_Policy.data[safe_language]
		except KeyError:
			safe_language = 'en'
		return json.dumps(Confio_Privacy_Policy.data[safe_language])

	def resolve_frequently_asked_questions(self, info, **kwargs):
		language = kwargs.get('language')
		safe_language = language.lower()[:2]
		try:
			Confio_Frequently_Asked_Questions.data[safe_language]
		except KeyError:
			safe_language = 'en'
		return json.dumps(Confio_Frequently_Asked_Questions.data[safe_language])

	def resolve_career(self, info, **kwargs):
		name = kwargs.get('name')
		if name == 'programmer':
			return json.dumps(programmer.data)
		elif name == 'content_creator':
			return json.dumps(content_creator.data)

	def resolve_update_online(self, info, **kwargs):
		return True