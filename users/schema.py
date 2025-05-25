import graphene
from graphene_django import DjangoObjectType
from django.contrib.auth import get_user_model
from .models import User, UserProfile
from .country_codes import COUNTRY_CODES
from graphql_jwt.utils import jwt_encode, jwt_decode
from graphql_jwt.shortcuts import create_refresh_token
from datetime import datetime, timedelta
import logging

User = get_user_model()
logger = logging.getLogger(__name__)

def jwt_payload_handler(user):
	"""Add auth_token_version to the JWT payload"""
	# Ensure user has auth_token_version
	if not hasattr(user, 'auth_token_version'):
		user.auth_token_version = 1
		user.save()
	
	# Get current timestamp
	now = datetime.utcnow()
	
	# Create the payload with all required fields
	payload = {
		'user_id': user.id,
		'username': user.get_username(),
		'origIat': int(now.timestamp()),
		'auth_token_version': user.auth_token_version,
		'exp': int((now + timedelta(days=7)).timestamp()),  # 7 days for access token
		'type': 'access'  # Indicate this is an access token
	}
	return payload

class UserType(DjangoObjectType):
	class Meta:
		model = User
		fields = ('id', 'username', 'email', 'first_name', 'last_name', 'phone_country', 'phone_number')

class UserProfileType(DjangoObjectType):
	class Meta:
		model = UserProfile
		fields = ('id', 'user', 'sui_address', 'created_at', 'last_login_at')

class CountryCodeType(graphene.ObjectType):
	code = graphene.String()
	name = graphene.String()
	flag = graphene.String()

class InvalidateAuthTokens(graphene.Mutation):
	class Arguments:
		pass  # No arguments needed, uses the authenticated user

	success = graphene.Boolean()
	error = graphene.String()

	@classmethod
	def mutate(cls, root, info):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return InvalidateAuthTokens(success=False, error="Authentication required")

		try:
			user.increment_auth_token_version()
			return InvalidateAuthTokens(success=True, error=None)
		except Exception as e:
			return InvalidateAuthTokens(success=False, error=str(e))

class Query(graphene.ObjectType):
	me = graphene.Field(UserType)
	country_codes = graphene.List(CountryCodeType)

	def resolve_me(self, info):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return None
		return user

	def resolve_country_codes(self, info):
		return [CountryCodeType(code=code[1], name=code[0], flag=code[3]) for code in COUNTRY_CODES]

class UpdatePhoneNumber(graphene.Mutation):
	class Arguments:
		country_code = graphene.String(required=True)
		phone_number = graphene.String(required=True)

	success = graphene.Boolean()
	error = graphene.String()

	@classmethod
	def mutate(cls, root, info, country_code, phone_number):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return UpdatePhoneNumber(success=False, error="Authentication required")

		# Validate country code
		valid_country = False
		for code in COUNTRY_CODES:
			if code[1] == country_code:
				valid_country = True
				break

		if not valid_country:
			return UpdatePhoneNumber(success=False, error="Invalid country code")

		# Update user's phone number
		try:
			user.phone_country = country_code
			user.phone_number = phone_number
			user.save()
			return UpdatePhoneNumber(success=True, error=None)
		except Exception as e:
			return UpdatePhoneNumber(success=False, error=str(e))

class RefreshToken(graphene.Mutation):
	class Arguments:
		refreshToken = graphene.String(required=True)

	token = graphene.String()
	payload = graphene.JSONString()
	refreshExpiresIn = graphene.Int()

	def __init__(self, *args, **kwargs):
		print('RefreshToken mutation class constructed')
		super().__init__(*args, **kwargs)

	@classmethod
	def mutate(cls, root, info, refreshToken):
		logger.info("RefreshToken mutation called")
		try:
			logger.info("Received refreshToken: %s", refreshToken)
			# Verify the refresh token
			payload = jwt_decode(refreshToken)
			logger.info("Decoded payload: %s", payload)
			user_id = payload.get('user_id')
			token_version = payload.get('auth_token_version')
			
			if not user_id or not token_version:
				raise Exception("Invalid refresh token")
			
			User = get_user_model()
			try:
				user = User.objects.get(id=user_id)
			except User.DoesNotExist:
				raise Exception("User not found")
			
			# Verify token version
			if user.auth_token_version != token_version:
				raise Exception("Token version mismatch")
			
			# Generate new access token
			new_access_token = jwt_encode(jwt_payload_handler(user))
			
			# Calculate refresh expiration
			refresh_exp = int((datetime.utcnow() + timedelta(days=365)).timestamp())
			
			return RefreshToken(
				token=new_access_token,
				payload=jwt_payload_handler(user),
				refreshExpiresIn=refresh_exp
			)
		except Exception as e:
			raise Exception(str(e))

class Mutation(graphene.ObjectType):
	update_phone_number = UpdatePhoneNumber.Field()
	invalidate_auth_tokens = InvalidateAuthTokens.Field()
	refresh_token = RefreshToken.Field()
