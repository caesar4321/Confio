import graphene
from graphene_django import DjangoObjectType
from django.contrib.auth import get_user_model
from .models import User, Account, IdentityVerification, Business
from .country_codes import COUNTRY_CODES
from graphql_jwt.utils import jwt_encode, jwt_decode
from graphql_jwt.shortcuts import create_refresh_token
from datetime import datetime, timedelta
import logging
from django.utils.translation import gettext as _
from .legal.documents import TERMS, PRIVACY, DELETION
from graphql import GraphQLError

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
	# Define computed fields explicitly
	is_identity_verified = graphene.Boolean()
	last_verified_date = graphene.DateTime()
	verification_status = graphene.String()
	
	class Meta:
		model = User
		fields = ('id', 'username', 'email', 'first_name', 'last_name', 'phone_country', 'phone_number')
	
	def resolve_is_identity_verified(self, info):
		return self.is_identity_verified
	
	def resolve_last_verified_date(self, info):
		return self.last_verified_date
	
	def resolve_verification_status(self, info):
		return self.verification_status

class IdentityVerificationType(DjangoObjectType):
	class Meta:
		model = IdentityVerification
		fields = ('id', 'user', 'verified_first_name', 'verified_last_name', 'verified_date_of_birth', 'verified_nationality', 'verified_address', 'verified_city', 'verified_state', 'verified_country', 'verified_postal_code', 'document_type', 'document_number', 'document_issuing_country', 'document_expiry_date', 'status', 'verified_by', 'verified_at', 'rejected_reason', 'created_at', 'updated_at')

class BusinessType(DjangoObjectType):
	class Meta:
		model = Business
		fields = ('id', 'name', 'description', 'category', 'business_registration_number', 'address', 'created_at', 'updated_at')

class AccountType(DjangoObjectType):
	# Define computed fields explicitly
	account_id = graphene.String()
	display_name = graphene.String()
	avatar_letter = graphene.String()
	
	class Meta:
		model = Account
		fields = ('id', 'user', 'account_type', 'account_index', 'business', 'sui_address', 'created_at', 'last_login_at')
	
	def resolve_account_id(self, info):
		return self.account_id
	
	def resolve_display_name(self, info):
		return self.display_name
	
	def resolve_avatar_letter(self, info):
		return self.avatar_letter

class CountryCodeType(graphene.ObjectType):
	code = graphene.String()
	name = graphene.String()
	flag = graphene.String()

class BusinessCategoryType(graphene.ObjectType):
	id = graphene.String()
	name = graphene.String()

class LegalDocumentType(graphene.ObjectType):
	title = graphene.String()
	content = graphene.List(graphene.JSONString)
	version = graphene.String()
	last_updated = graphene.String()
	language = graphene.String()
	is_legally_binding = graphene.Boolean()

class LegalDocumentError(GraphQLError):
	"""Custom error for legal document related issues"""
	def __init__(self, message, code=None, params=None):
		super().__init__(message)
		self.code = code or 'LEGAL_DOCUMENT_ERROR'
		self.params = params or {}

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
	business_categories = graphene.List(BusinessCategoryType)
	user_verifications = graphene.List(IdentityVerificationType, user_id=graphene.ID())
	user_accounts = graphene.List(AccountType)
	legalDocument = graphene.Field(
		LegalDocumentType,
		docType=graphene.String(required=True),
		language=graphene.String()
	)

	def resolve_legalDocument(self, info, docType, language=None):
		logger.info(f"Received legal document request for type: {docType}, language: {language}")
		
		# For now, we'll always return Spanish content
		if docType == 'terms':
			return LegalDocumentType(
				title=TERMS['title'],
				content=TERMS['sections'],
				version=TERMS['version'],
				last_updated=TERMS['last_updated'],
				language='es',
				is_legally_binding=TERMS['is_legally_binding']
			)
		elif docType == 'privacy':
			return LegalDocumentType(
				title=PRIVACY['title'],
				content=PRIVACY['sections'],
				version=PRIVACY['version'],
				last_updated=PRIVACY['last_updated'],
				language='es',
				is_legally_binding=PRIVACY['is_legally_binding']
			)
		elif docType == 'deletion':
			return LegalDocumentType(
				title=DELETION['title'],
				content=DELETION['sections'],
				version=DELETION['version'],
				last_updated=DELETION['last_updated'],
				language='es',
				is_legally_binding=DELETION['is_legally_binding']
			)
		return None

	def resolve_me(self, info):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return None
		return user

	def resolve_country_codes(self, info):
		return [CountryCodeType(code=code[1], name=code[0], flag=code[3]) for code in COUNTRY_CODES]

	def resolve_business_categories(self, info):
		from .models import Business
		return [BusinessCategoryType(id=choice[0], name=choice[1]) for choice in Business.BUSINESS_CATEGORY_CHOICES]

	def resolve_user_verifications(self, info, user_id=None):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return []
		
		# If user_id is provided, check if current user is admin or the same user
		if user_id:
			if not user.is_staff and str(user.id) != user_id:
				return []
			return IdentityVerification.objects.filter(user_id=user_id)
		
		# If no user_id provided, return current user's verifications
		return IdentityVerification.objects.filter(user=user)

	def resolve_user_accounts(self, info):
		user = getattr(info.context, 'user', None)
		print(f"resolve_user_accounts - user: {user}")
		print(f"resolve_user_accounts - user authenticated: {user and getattr(user, 'is_authenticated', False)}")
		
		if not (user and getattr(user, 'is_authenticated', False)):
			print("resolve_user_accounts - returning empty list (not authenticated)")
			return []
		
		accounts = Account.objects.filter(user=user).select_related('business')
		print(f"resolve_user_accounts - found {accounts.count()} accounts for user {user.id}")
		for account in accounts:
			print(f"  Account: {account.id} ({account.account_type}_{account.account_index}) - business: {account.business}")
		
		# Return accounts sorted by custom ordering: personal first, then business by index
		return sorted(accounts, key=lambda acc: acc.get_ordering_key())

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

		# Validate country code and get ISO code
		iso_country_code = None
		for code in COUNTRY_CODES:
			if code[1] == country_code:  # code[1] is phone code (e.g., '+58')
				iso_country_code = code[2]  # code[2] is ISO code (e.g., 'VE')
				break

		if not iso_country_code:
			return UpdatePhoneNumber(success=False, error="Invalid country code")

		# Update user's phone number
		try:
			user.phone_country = iso_country_code  # Store ISO code
			user.phone_number = phone_number
			user.save()
			return UpdatePhoneNumber(success=True, error=None)
		except Exception as e:
			return UpdatePhoneNumber(success=False, error=str(e))

class UpdateUsername(graphene.Mutation):
	class Arguments:
		username = graphene.String(required=True)

	success = graphene.Boolean()
	error = graphene.String()
	user = graphene.Field(UserType)

	@classmethod
	def mutate(cls, root, info, username):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return UpdateUsername(success=False, error="Authentication required", user=None)

		# Validate input
		username = username.strip()
		if not username:
			return UpdateUsername(success=False, error="Username is required", user=None)

		# Server-side validation for username format and length
		from .validators import validate_username
		is_valid, error_message = validate_username(username)
		if not is_valid:
			return UpdateUsername(success=False, error=error_message, user=None)

		# Check if username is already taken (case-insensitive)
		existing_user = User.objects.filter(username__iexact=username).exclude(id=user.id).first()
		if existing_user:
			return UpdateUsername(success=False, error="Este nombre de usuario ya está en uso. Intenta con otro nombre.", user=None)

		# Update user's username (preserve case as entered)
		try:
			user.username = username
			user.save()
			return UpdateUsername(success=True, error=None, user=user)
		except Exception as e:
			return UpdateUsername(success=False, error=str(e), user=None)

class UpdateUserProfile(graphene.Mutation):
	class Arguments:
		first_name = graphene.String(required=True)
		last_name = graphene.String(required=True)

	success = graphene.Boolean()
	error = graphene.String()
	user = graphene.Field(UserType)

	@classmethod
	def mutate(cls, root, info, first_name, last_name):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return UpdateUserProfile(success=False, error="Authentication required", user=None)

		# Check if user is verified - if so, don't allow name changes
		if user.is_identity_verified:
			return UpdateUserProfile(success=False, error="No se puede modificar el nombre de un usuario verificado", user=None)

		# Validate input
		if not first_name.strip():
			return UpdateUserProfile(success=False, error="First name is required", user=None)

		# Update user's profile
		try:
			user.first_name = first_name.strip()
			user.last_name = last_name.strip()
			user.save()
			return UpdateUserProfile(success=True, error=None, user=user)
		except Exception as e:
			return UpdateUserProfile(success=False, error=str(e), user=None)

class SubmitIdentityVerification(graphene.Mutation):
	class Arguments:
		verified_first_name = graphene.String(required=True)
		verified_last_name = graphene.String(required=True)
		verified_date_of_birth = graphene.Date(required=True)
		verified_nationality = graphene.String(required=True)
		verified_address = graphene.String(required=True)
		verified_city = graphene.String(required=True)
		verified_state = graphene.String(required=True)
		verified_country = graphene.String(required=True)
		verified_postal_code = graphene.String()
		document_type = graphene.String(required=True)
		document_number = graphene.String(required=True)
		document_issuing_country = graphene.String(required=True)
		document_expiry_date = graphene.Date()
		document_front_image = graphene.String(required=True)  # Base64 encoded
		document_back_image = graphene.String()  # Base64 encoded
		selfie_with_document = graphene.String(required=True)  # Base64 encoded

	success = graphene.Boolean()
	error = graphene.String()
	verification = graphene.Field(IdentityVerificationType)

	@classmethod
	def mutate(cls, root, info, **kwargs):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return SubmitIdentityVerification(success=False, error="Authentication required", verification=None)

		try:
			# Create verification record
			verification = IdentityVerification.objects.create(
				user=user,
				verified_first_name=kwargs['verified_first_name'],
				verified_last_name=kwargs['verified_last_name'],
				verified_date_of_birth=kwargs['verified_date_of_birth'],
				verified_nationality=kwargs['verified_nationality'],
				verified_address=kwargs['verified_address'],
				verified_city=kwargs['verified_city'],
				verified_state=kwargs['verified_state'],
				verified_country=kwargs['verified_country'],
				verified_postal_code=kwargs.get('verified_postal_code'),
				document_type=kwargs['document_type'],
				document_number=kwargs['document_number'],
				document_issuing_country=kwargs['document_issuing_country'],
				document_expiry_date=kwargs.get('document_expiry_date'),
				# Note: File handling would need to be implemented separately
				# For now, we'll store the base64 data as text
				document_front_image=kwargs['document_front_image'],
				document_back_image=kwargs.get('document_back_image'),
				selfie_with_document=kwargs['selfie_with_document'],
			)
			
			return SubmitIdentityVerification(success=True, error=None, verification=verification)
		except Exception as e:
			return SubmitIdentityVerification(success=False, error=str(e), verification=None)

class ApproveIdentityVerification(graphene.Mutation):
	class Arguments:
		verification_id = graphene.ID(required=True)

	success = graphene.Boolean()
	error = graphene.String()
	verification = graphene.Field(IdentityVerificationType)

	@classmethod
	def mutate(cls, root, info, verification_id):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return ApproveIdentityVerification(success=False, error="Authentication required", verification=None)

		# Check if the current user has admin permissions
		if not user.is_staff:
			return ApproveIdentityVerification(success=False, error="Permisos insuficientes", verification=None)

		try:
			verification = IdentityVerification.objects.get(id=verification_id)
			verification.approve_verification(user)
			return ApproveIdentityVerification(success=True, error=None, verification=verification)
		except IdentityVerification.DoesNotExist:
			return ApproveIdentityVerification(success=False, error="Verificación no encontrada", verification=None)
		except Exception as e:
			return ApproveIdentityVerification(success=False, error=str(e), verification=None)

class RejectIdentityVerification(graphene.Mutation):
	class Arguments:
		verification_id = graphene.ID(required=True)
		reason = graphene.String(required=True)

	success = graphene.Boolean()
	error = graphene.String()
	verification = graphene.Field(IdentityVerificationType)

	@classmethod
	def mutate(cls, root, info, verification_id, reason):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return RejectIdentityVerification(success=False, error="Authentication required", verification=None)

		# Check if the current user has admin permissions
		if not user.is_staff:
			return RejectIdentityVerification(success=False, error="Permisos insuficientes", verification=None)

		try:
			verification = IdentityVerification.objects.get(id=verification_id)
			verification.reject_verification(user, reason)
			return RejectIdentityVerification(success=True, error=None, verification=verification)
		except IdentityVerification.DoesNotExist:
			return RejectIdentityVerification(success=False, error="Verificación no encontrada", verification=None)
		except Exception as e:
			return RejectIdentityVerification(success=False, error=str(e), verification=None)

class CreateBusiness(graphene.Mutation):
	class Arguments:
		name = graphene.String(required=True)
		description = graphene.String()
		category = graphene.String(required=True)
		business_registration_number = graphene.String()
		address = graphene.String()

	success = graphene.Boolean()
	error = graphene.String()
	business = graphene.Field(BusinessType)
	account = graphene.Field(AccountType)

	@classmethod
	def mutate(cls, root, info, name, category, description=None, business_registration_number=None, address=None):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return CreateBusiness(success=False, error="Authentication required")

		try:
			# Validate business name
			if not name.strip():
				return CreateBusiness(success=False, error="El nombre del negocio es requerido")

			# Validate category
			valid_categories = [choice[0] for choice in Business.BUSINESS_CATEGORY_CHOICES]
			if category not in valid_categories:
				return CreateBusiness(success=False, error="Categoría de negocio inválida")

			# Rate limiting: Check if user has created a business in the last 30 seconds
			from django.utils import timezone
			from datetime import timedelta
			
			recent_business = Business.objects.filter(
				accounts__user=user,
				created_at__gte=timezone.now() - timedelta(seconds=30)
			).first()
			
			if recent_business:
				return CreateBusiness(
					success=False, 
					error="Has intentado crear un negocio muy recientemente. Por favor, espera unos segundos antes de intentar de nuevo."
				)

			# Check for duplicate business name for this user
			existing_business = Business.objects.filter(
				accounts__user=user,
				name__iexact=name.strip()
			).first()
			
			if existing_business:
				return CreateBusiness(
					success=False, 
					error=f"Ya tienes un negocio con el nombre '{name.strip()}'. Por favor, usa un nombre diferente."
				)

			# Create the business
			business = Business.objects.create(
				name=name.strip(),
				description=description.strip() if description else None,
				category=category,
				business_registration_number=business_registration_number.strip() if business_registration_number else None,
				address=address.strip() if address else None
			)

			# Get the next available business account index for this user
			# Include soft-deleted accounts to prevent index reuse
			next_index = Account.all_objects.filter(
				user=user,
				account_type='business'
			).count()

			# Create the business account
			account = Account.objects.create(
				user=user,
				account_type='business',
				account_index=next_index,
				business=business
			)

			return CreateBusiness(
				success=True,
				error=None,
				business=business,
				account=account
			)

		except Exception as e:
			logger.error(f"Error creating business: {str(e)}")
			return CreateBusiness(success=False, error="Error interno del servidor")

class UpdateBusiness(graphene.Mutation):
	class Arguments:
		business_id = graphene.ID(required=True)
		name = graphene.String(required=True)
		description = graphene.String()
		category = graphene.String(required=True)
		business_registration_number = graphene.String()
		address = graphene.String()

	success = graphene.Boolean()
	error = graphene.String()
	business = graphene.Field(BusinessType)

	@classmethod
	def mutate(cls, root, info, business_id, name, category, description=None, business_registration_number=None, address=None):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return UpdateBusiness(success=False, error="Authentication required")

		try:
			# Get the business and verify it belongs to the user
			business = Business.objects.get(
				id=business_id,
				accounts__user=user
			)
			
			# Validate business name
			if not name.strip():
				return UpdateBusiness(success=False, error="El nombre del negocio es requerido")

			# Validate category
			valid_categories = [choice[0] for choice in Business.BUSINESS_CATEGORY_CHOICES]
			if category not in valid_categories:
				return UpdateBusiness(success=False, error="Categoría de negocio inválida")

			# Check for duplicate business name for this user (excluding current business)
			existing_business = Business.objects.filter(
				accounts__user=user,
				name__iexact=name.strip()
			).exclude(id=business_id).first()
			
			if existing_business:
				return UpdateBusiness(
					success=False, 
					error=f"Ya tienes un negocio con el nombre '{name.strip()}'. Por favor, usa un nombre diferente."
				)

			# Update the business
			business.name = name.strip()
			business.description = description.strip() if description else None
			business.category = category
			business.business_registration_number = business_registration_number.strip() if business_registration_number else None
			business.address = address.strip() if address else None
			business.save()

			return UpdateBusiness(
				success=True,
				error=None,
				business=business
			)

		except Business.DoesNotExist:
			return UpdateBusiness(success=False, error="Negocio no encontrado")
		except Exception as e:
			logger.error(f"Error updating business: {str(e)}")
			return UpdateBusiness(success=False, error="Error interno del servidor")

class UpdateAccountSuiAddress(graphene.Mutation):
	class Arguments:
		account_id = graphene.ID(required=True)
		sui_address = graphene.String(required=True)

	success = graphene.Boolean()
	error = graphene.String()
	account = graphene.Field(AccountType)

	@classmethod
	def mutate(cls, root, info, account_id, sui_address):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return UpdateAccountSuiAddress(success=False, error="Authentication required")

		try:
			# Get the account and verify it belongs to the user
			account = Account.objects.get(id=account_id, user=user)
			
			# Update the Sui address
			account.sui_address = sui_address
			account.save()
			
			return UpdateAccountSuiAddress(
				success=True,
				error=None,
				account=account
			)

		except Account.DoesNotExist:
			return UpdateAccountSuiAddress(success=False, error="Cuenta no encontrada")
		except Exception as e:
			logger.error(f"Error updating account Sui address: {str(e)}")
			return UpdateAccountSuiAddress(success=False, error="Error interno del servidor")

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
	update_username = UpdateUsername.Field()
	update_user_profile = UpdateUserProfile.Field()
	invalidate_auth_tokens = InvalidateAuthTokens.Field()
	refresh_token = RefreshToken.Field()
	submit_identity_verification = SubmitIdentityVerification.Field()
	approve_identity_verification = ApproveIdentityVerification.Field()
	reject_identity_verification = RejectIdentityVerification.Field()
	create_business = CreateBusiness.Field()
	update_business = UpdateBusiness.Field()
	update_account_sui_address = UpdateAccountSuiAddress.Field()
