import graphene
from graphene_django import DjangoObjectType
from django.contrib.auth import get_user_model
from .models import User, Account, IdentityVerification, Business, Country, Bank, BankInfo
from .country_codes import COUNTRY_CODES
from graphql_jwt.utils import jwt_encode, jwt_decode
from graphql_jwt.shortcuts import create_refresh_token
from datetime import datetime, timedelta
import logging
from django.utils.translation import gettext as _
from .legal.documents import TERMS, PRIVACY, DELETION
from graphql import GraphQLError
from .graphql_employee import (
    EmployeeQueries, EmployeeMutations,
    BusinessEmployeeType, EmployerBusinessType
)
# Removed circular import - P2PPaymentMethodType will be referenced by string

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
	accounts = graphene.List(lambda: AccountType)
	
	class Meta:
		model = User
		fields = ('id', 'username', 'email', 'first_name', 'last_name', 'phone_country', 'phone_number')
	
	def resolve_is_identity_verified(self, info):
		return self.is_identity_verified
	
	def resolve_last_verified_date(self, info):
		return self.last_verified_date
	
	def resolve_verification_status(self, info):
		return self.verification_status
	
	def resolve_accounts(self, info):
		return Account.objects.filter(user=self).select_related('business')

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
	
	# Employee-related fields
	is_employee = graphene.Boolean()
	employee_role = graphene.String()
	employee_permissions = graphene.JSONString()
	employee_record_id = graphene.ID()
	
	class Meta:
		model = Account
		fields = ('id', 'user', 'account_type', 'account_index', 'business', 'sui_address', 'created_at', 'last_login_at')
	
	@classmethod
	def get_queryset(cls, queryset, info):
		# This ensures we can handle both Account querysets and mixed lists
		return queryset
	
	def resolve_account_id(self, info):
		if hasattr(self, 'account_id'):
			return self.account_id
		# Generate account_id
		# For employee accounts, use a special format to distinguish them
		if getattr(self, 'is_employee', False):
			return f"employee_{self.account_type}_{self.id}"
		return f"{self.account_type}_{self.account_index}"
	
	def resolve_display_name(self, info):
		if hasattr(self, 'display_name'):
			return self.display_name
		# Generate display name for regular accounts
		if self.account_type == 'personal':
			user = self.user
			if user.first_name or user.last_name:
				return f"Personal - {user.first_name} {user.last_name}".strip()
			return f"Personal - {user.username}"
		elif self.business:
			# Check if this is an employee account
			if getattr(self, 'is_employee', False):
				return f"{self.business.name} (Empleado)"
			return f"Negocio - {self.business.name}"
		return "Account"
	
	def resolve_is_employee(self, info):
		return getattr(self, 'is_employee', False)
	
	def resolve_employee_role(self, info):
		return getattr(self, 'employee_role', None)
	
	def resolve_sui_address(self, info):
		"""Custom resolver for sui_address to check permissions"""
		# If this is an employee accessing business account
		if self.account_type == 'business' and hasattr(info.context, 'active_business_id'):
			business_id = getattr(info.context, 'active_business_id', None)
			user = getattr(info.context, 'user', None)
			
			if business_id and user and str(self.business_id) == str(business_id):
				# Employee accessing business account
				try:
					from .permissions import check_employee_permission
					from django.core.exceptions import PermissionDenied
					check_employee_permission(user, self.business, 'view_business_address')
				except PermissionDenied:
					# Employee doesn't have permission to view business address
					return None
		
		# Return the actual address for owners or employees with permission
		return self.sui_address
	
	def resolve_employee_permissions(self, info):
		return getattr(self, 'employee_permissions', None)
	
	def resolve_employee_record_id(self, info):
		return getattr(self, 'employee_record_id', None)
	
	def resolve_avatar_letter(self, info):
		if hasattr(self, 'avatar_letter'):
			return self.avatar_letter
		# Generate avatar letter for regular accounts
		display_name = self.resolve_display_name(info)
		return display_name[0].upper() if display_name else 'A'


class CountryType(DjangoObjectType):
	class Meta:
		model = Country
		fields = ('id', 'code', 'name', 'flag_emoji', 'currency_code', 'currency_symbol', 
		         'requires_identification', 'identification_name', 'identification_format',
		         'account_number_length', 'supports_phone_payments', 'is_active', 'display_order')


class BankType(DjangoObjectType):
	account_type_choices = graphene.List(graphene.String)
	
	class Meta:
		model = Bank
		fields = ('id', 'country', 'code', 'name', 'short_name', 'supports_checking', 
		         'supports_savings', 'supports_payroll', 'is_active', 'display_order')
	
	def resolve_account_type_choices(self, info):
		return [choice[0] for choice in self.get_account_type_choices()]


class BankInfoType(DjangoObjectType):
	# Define computed fields explicitly
	masked_account_number = graphene.String()
	full_bank_name = graphene.String()
	summary_text = graphene.String()
	requires_identification = graphene.Boolean()
	identification_label = graphene.String()
	payment_details = graphene.JSONString()
	payment_method = graphene.Field('p2p_exchange.schema.P2PPaymentMethodType')
	
	class Meta:
		model = BankInfo
		fields = ('id', 'account', 'country', 'bank', 'account_holder_name', 'account_number',
		         'account_type', 'identification_number', 'phone_number', 'email', 'username', 'is_default',
		         'is_public', 'is_verified', 'verified_at', 'created_at', 'updated_at')
	
	def resolve_masked_account_number(self, info):
		return self.get_masked_account_number()
	
	def resolve_full_bank_name(self, info):
		return self.full_bank_name
	
	def resolve_summary_text(self, info):
		return self.summary_text
	
	def resolve_requires_identification(self, info):
		return self.requires_identification
	
	def resolve_identification_label(self, info):
		return self.identification_label
	
	def resolve_payment_details(self, info):
		return self.get_payment_details()
	
	def resolve_payment_method(self, info):
		return self.payment_method

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

class UserByPhoneType(graphene.ObjectType):
	phone_number = graphene.String()
	user_id = graphene.ID()
	username = graphene.String()
	first_name = graphene.String()
	last_name = graphene.String()
	is_on_confio = graphene.Boolean()
	active_account_id = graphene.ID()
	active_account_sui_address = graphene.String()

class Query(EmployeeQueries, graphene.ObjectType):
	me = graphene.Field(UserType)
	user = graphene.Field(UserType, id=graphene.ID(required=True))
	business = graphene.Field(BusinessType, id=graphene.ID(required=True))
	country_codes = graphene.List(CountryCodeType)
	business_categories = graphene.List(BusinessCategoryType)
	user_verifications = graphene.List(IdentityVerificationType, user_id=graphene.ID())
	user_accounts = graphene.List(AccountType)
	account_balance = graphene.String(token_type=graphene.String(required=True))
	current_account_permissions = graphene.Field(graphene.JSONString)
	legalDocument = graphene.Field(
		LegalDocumentType,
		docType=graphene.String(required=True),
		language=graphene.String()
	)
	
	# Bank info queries
	countries = graphene.List(CountryType, is_active=graphene.Boolean())
	banks = graphene.List(BankType, country_code=graphene.String())
	user_bank_accounts = graphene.List(BankInfoType, account_id=graphene.ID())
	bank_info = graphene.Field(BankInfoType, id=graphene.ID(required=True))
	
	# Contact sync queries
	check_users_by_phones = graphene.List(UserByPhoneType, phone_numbers=graphene.List(graphene.String, required=True))

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
	
	def resolve_user(self, info, id):
		"""Resolve user by ID"""
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return None
		
		try:
			# For security, only allow fetching user details if they have interacted with the current user
			# or if the current user is fetching their own details
			requested_user = User.objects.get(id=id)
			
			# For now, allow fetching any user's basic info (can add more restrictions later)
			return requested_user
		except User.DoesNotExist:
			return None

	def resolve_business(self, info, id):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return None
		
		try:
			# Check if the user has access to this business through their accounts
			from .models import Business, Account
			business = Business.objects.get(id=id)
			
			# Verify that the current user has an account linked to this business
			user_has_access = Account.objects.filter(
				user=user,
				business=business,
				account_type='business'
			).exists()
			
			if user_has_access:
				return business
			else:
				return None
		except Business.DoesNotExist:
			return None

	def resolve_country_codes(self, info):
		# Map ISO codes to flag emojis
		flag_map = {
			'AF': '🇦🇫', 'AL': '🇦🇱', 'DZ': '🇩🇿', 'AS': '🇦🇸', 'AD': '🇦🇩',
			'AO': '🇦🇴', 'AI': '🇦🇮', 'AG': '🇦🇬', 'AR': '🇦🇷', 'AM': '🇦🇲',
			'AW': '🇦🇼', 'AU': '🇦🇺', 'AT': '🇦🇹', 'AZ': '🇦🇿', 'BS': '🇧🇸',
			'BH': '🇧🇭', 'BD': '🇧🇩', 'BB': '🇧🇧', 'BY': '🇧🇾', 'BE': '🇧🇪',
			'BZ': '🇧🇿', 'BJ': '🇧🇯', 'BM': '🇧🇲', 'BT': '🇧🇹', 'BO': '🇧🇴',
			'BA': '🇧🇦', 'BW': '🇧🇼', 'BR': '🇧🇷', 'IO': '🇮🇴', 'VG': '🇻🇬',
			'BN': '🇧🇳', 'BG': '🇧🇬', 'BF': '🇧🇫', 'BI': '🇧🇮', 'KH': '🇰🇭',
			'CM': '🇨🇲', 'CA': '🇨🇦', 'CV': '🇨🇻', 'BQ': '🇧🇶', 'KY': '🇰🇾',
			'CF': '🇨🇫', 'TD': '🇹🇩', 'CL': '🇨🇱', 'CN': '🇨🇳', 'CX': '🇨🇽',
			'CC': '🇨🇨', 'CO': '🇨🇴', 'KM': '🇰🇲', 'CD': '🇨🇩', 'CG': '🇨🇬',
			'CK': '🇨🇰', 'CR': '🇨🇷', 'CI': '🇨🇮', 'HR': '🇭🇷', 'CU': '🇨🇺',
			'CW': '🇨🇼', 'CY': '🇨🇾', 'CZ': '🇨🇿', 'DK': '🇩🇰', 'DJ': '🇩🇯',
			'DM': '🇩🇲', 'DO': '🇩🇴', 'EC': '🇪🇨', 'EG': '🇪🇬', 'SV': '🇸🇻',
			'GQ': '🇬🇶', 'ER': '🇪🇷', 'EE': '🇪🇪', 'ET': '🇪🇹', 'FK': '🇫🇰',
			'FO': '🇫🇴', 'FJ': '🇫🇯', 'FI': '🇫🇮', 'FR': '🇫🇷', 'GF': '🇬🇫',
			'PF': '🇵🇫', 'GA': '🇬🇦', 'GM': '🇬🇲', 'GE': '🇬🇪', 'DE': '🇩🇪',
			'GH': '🇬🇭', 'GI': '🇬🇮', 'GR': '🇬🇷', 'GL': '🇬🇱', 'GD': '🇬🇩',
			'GP': '🇬🇵', 'GU': '🇬🇺', 'GT': '🇬🇹', 'GG': '🇬🇬', 'GN': '🇬🇳',
			'GW': '🇬🇼', 'GY': '🇬🇾', 'HT': '🇭🇹', 'HN': '🇭🇳', 'HK': '🇭🇰',
			'HU': '🇭🇺', 'IS': '🇮🇸', 'IN': '🇮🇳', 'ID': '🇮🇩', 'IR': '🇮🇷',
			'IQ': '🇮🇶', 'IE': '🇮🇪', 'IM': '🇮🇲', 'IL': '🇮🇱', 'IT': '🇮🇹',
			'JM': '🇯🇲', 'JP': '🇯🇵', 'JE': '🇯🇪', 'JO': '🇯🇴', 'KZ': '🇰🇿',
			'KE': '🇰🇪', 'KI': '🇰🇮', 'XK': '🇽🇰', 'KW': '🇰🇼', 'KG': '🇰🇬',
			'LA': '🇱🇦', 'LV': '🇱🇻', 'LB': '🇱🇧', 'LS': '🇱🇸', 'LR': '🇱🇷',
			'LY': '🇱🇾', 'LI': '🇱🇮', 'LT': '🇱🇹', 'LU': '🇱🇺', 'MO': '🇲🇴',
			'MK': '🇲🇰', 'MG': '🇲🇬', 'MW': '🇲🇼', 'MY': '🇲🇾', 'MV': '🇲🇻',
			'ML': '🇲🇱', 'MT': '🇲🇹', 'MH': '🇲🇭', 'MQ': '🇲🇶', 'MR': '🇲🇷',
			'MU': '🇲🇺', 'YT': '🇾🇹', 'MX': '🇲🇽', 'FM': '🇫🇲', 'MD': '🇲🇩',
			'MC': '🇲🇨', 'MN': '🇲🇳', 'ME': '🇲🇪', 'MS': '🇲🇸', 'MA': '🇲🇦',
			'MZ': '🇲🇿', 'MM': '🇲🇲', 'NA': '🇳🇦', 'NR': '🇳🇷', 'NP': '🇳🇵',
			'NL': '🇳🇱', 'NC': '🇳🇨', 'NZ': '🇳🇿', 'NI': '🇳🇮', 'NE': '🇳🇪',
			'NG': '🇳🇬', 'NU': '🇳🇺', 'NF': '🇳🇫', 'KP': '🇰🇵', 'MP': '🇲🇵',
			'NO': '🇳🇴', 'OM': '🇴🇲', 'PK': '🇵🇰', 'PW': '🇵🇼', 'PS': '🇵🇸',
			'PA': '🇵🇦', 'PG': '🇵🇬', 'PY': '🇵🇾', 'PE': '🇵🇪', 'PH': '🇵🇭',
			'PL': '🇵🇱', 'PT': '🇵🇹', 'PR': '🇵🇷', 'QA': '🇶🇦', 'RE': '🇷🇪',
			'RO': '🇷🇴', 'RU': '🇷🇺', 'RW': '🇷🇼', 'BL': '🇧🇱', 'SH': '🇸🇭',
			'KN': '🇰🇳', 'LC': '🇱🇨', 'MF': '🇲🇫', 'PM': '🇵🇲', 'VC': '🇻🇨',
			'WS': '🇼🇸', 'SM': '🇸🇲', 'ST': '🇸🇹', 'SA': '🇸🇦', 'SN': '🇸🇳',
			'RS': '🇷🇸', 'SC': '🇸🇨', 'SL': '🇸🇱', 'SG': '🇸🇬', 'SX': '🇸🇽',
			'SK': '🇸🇰', 'SI': '🇸🇮', 'SB': '🇸🇧', 'SO': '🇸🇴', 'ZA': '🇿🇦',
			'KR': '🇰🇷', 'SS': '🇸🇸', 'ES': '🇪🇸', 'LK': '🇱🇰', 'SD': '🇸🇩',
			'SR': '🇸🇷', 'SJ': '🇸🇯', 'SZ': '🇸🇿', 'SE': '🇸🇪', 'CH': '🇨🇭',
			'SY': '🇸🇾', 'TW': '🇹🇼', 'TJ': '🇹🇯', 'TZ': '🇹🇿', 'TH': '🇹🇭',
			'TL': '🇹🇱', 'TG': '🇹🇬', 'TK': '🇹🇰', 'TO': '🇹🇴', 'TT': '🇹🇹',
			'TN': '🇹🇳', 'TR': '🇹🇷', 'TM': '🇹🇲', 'TC': '🇹🇨', 'TV': '🇹🇻',
			'VI': '🇻🇮', 'UG': '🇺🇬', 'UA': '🇺🇦', 'AE': '🇦🇪', 'GB': '🇬🇧',
			'US': '🇺🇸', 'UY': '🇺🇾', 'UZ': '🇺🇿', 'VU': '🇻🇺', 'VA': '🇻🇦',
			'VE': '🇻🇪', 'VN': '🇻🇳', 'WF': '🇼🇫', 'EH': '🇪🇭', 'YE': '🇾🇪',
			'ZM': '🇿🇲', 'ZW': '🇿🇼'
		}
		return [
			CountryCodeType(
				code=code[2],  # ISO code (e.g., 'VE')
				name=f"{code[0]} ({code[1]})",  # e.g., "Venezuela (+58)"
				flag=flag_map.get(code[2], '🏳️')  # Flag emoji or default flag
			) 
			for code in COUNTRY_CODES
		]

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
		
		# Get owned accounts (excluding soft-deleted ones)
		owned_accounts = Account.objects.filter(
			user=user,
			deleted_at__isnull=True
		).select_related('business')
		print(f"resolve_user_accounts - found {owned_accounts.count()} owned accounts for user {user.id}")
		
		# Start with owned accounts
		all_accounts = list(owned_accounts)
		
		# Get businesses where user is an employee
		from .models_employee import BusinessEmployee
		employee_records = BusinessEmployee.objects.filter(
			user=user,
			is_active=True,
			deleted_at__isnull=True
		).select_related('business')
		
		print(f"resolve_user_accounts - found {employee_records.count()} employee relationships for user {user.id}")
		
		# For each employee relationship, get the business owner's account
		for emp_record in employee_records:
			# Skip if user is the owner (they already have the account in owned_accounts)
			# Owner role means they own the business, so skip to avoid duplicates
			if emp_record.role == 'owner':
				continue
				
			# Find the business account (owned by someone else)
			business_account = Account.objects.filter(
				business=emp_record.business,
				account_type='business',
				deleted_at__isnull=True
			).first()
			
			if business_account:
				# Clone the account object and add employee metadata
				# We can't modify the original as it might affect other queries
				from copy import copy
				employee_account = copy(business_account)
				employee_account.is_employee = True
				employee_account.employee_role = emp_record.role
				employee_account.employee_permissions = emp_record.get_effective_permissions()
				employee_account.employee_record_id = emp_record.id
				# Ensure this account is marked as not owned by this user
				employee_account._is_employee_view = True
				all_accounts.append(employee_account)
		
		# Sort accounts: personal first, owned business, then employee business
		def get_sort_key(acc):
			if acc.account_type == 'personal':
				return (0, acc.account_index, '')
			elif getattr(acc, 'is_employee', False):
				return (2, acc.account_index, acc.business.name if acc.business else '')
			else:
				return (1, acc.account_index, acc.business.name if acc.business else '')
		
		return sorted(all_accounts, key=get_sort_key)

	def resolve_account_balance(self, info, token_type):
		"""Resolve account balance for a specific token type and active account"""
		user = getattr(info.context, 'user', None)
		
		# Log authentication status for debugging
		print(f"AccountBalance resolver - User: {user}, Authenticated: {getattr(user, 'is_authenticated', False) if user else False}")
		
		if not (user and getattr(user, 'is_authenticated', False)):
			print(f"AccountBalance resolver - Returning 0 for unauthenticated user")
			return "0"
		
		# Get JWT context with validation and permission check
		from .jwt_context import get_jwt_business_context_with_validation
		jwt_context = get_jwt_business_context_with_validation(info, required_permission='view_balance')
		if not jwt_context:
			print(f"AccountBalance resolver - No JWT context found, access denied, or lacking permission")
			return "0"
			
		account_type = jwt_context['account_type']
		account_index = jwt_context['account_index']
		business_id_from_context = jwt_context.get('business_id')
		employee_record = jwt_context.get('employee_record')
		
		print(f"AccountBalance resolver - JWT Account: {account_type}_{account_index}")
		print(f"AccountBalance resolver - JWT Business ID: {business_id_from_context}")
		
		# Get the specific account
		try:
			from .models import Account
			from .permissions import check_employee_permission
			from django.core.exceptions import PermissionDenied
			
			# For business accounts, permission is already checked via role-based matrix
			if account_type == 'business' and business_id_from_context and employee_record:
				# Permission already validated in get_jwt_business_context_with_validation
				# and check_role_permission ensures only authorized roles can view balance
				
				# Get the business account
				account = Account.objects.get(
					business_id=business_id_from_context,
					account_type='business',
					account_index=account_index
				)
			else:
				# Personal account - user must own it
				account = Account.objects.get(
					user=user,
					account_type=account_type,
					account_index=account_index
				)
				
			print(f"AccountBalance resolver - Found account with Sui address: {account.sui_address}")
		except (Account.DoesNotExist, Business.DoesNotExist) as e:
			print(f"AccountBalance resolver - Account not found: {account_type}_{account_index}")
			return "0"
		except PermissionDenied:
			# Already handled above
			pass
		
		# Normalize token type
		normalized_token_type = token_type.upper()
		if normalized_token_type == 'CUSD':
			normalized_token_type = 'cUSD'
		
		# For now, return mock balances based on account type and token type
		# In production, this would query the blockchain using account.sui_address
		if account_type == 'personal':
			mock_balances = {
				'cUSD': '150.00',
				'CONFIO': '50.00',
				'USDC': '200.00'
			}
		else:
			# Create deterministic balances per business ID for debugging
			# This helps identify which business context is being used
			# Use business_id from JWT context to ensure proper differentiation
			business_id = int(business_id_from_context) if business_id_from_context else 0
			base_multiplier = business_id * 1000  # Each business gets unique base amount
			
			print(f"AccountBalance resolver - DEBUG: JWT business_id={business_id_from_context}, account.business.id={account.business.id if account.business else None}")
			print(f"AccountBalance resolver - Using business_id={business_id} for balance calculation")
			
			mock_balances = {
				'cUSD': f'{10000 + base_multiplier}.00',     # Business 1: 11000, Business 2: 12000, etc.
				'CONFIO': f'{5000 + base_multiplier}.00',    # Business 1: 6000, Business 2: 7000, etc. 
				'USDC': f'{20000 + base_multiplier}.00'      # Business 1: 21000, Business 2: 22000, etc.
			}
			
			print(f"AccountBalance resolver - Business ID {business_id} deterministic balances: {mock_balances}")
		
		balance = mock_balances.get(normalized_token_type, '0')
		print(f"AccountBalance resolver - Returning {balance} for {normalized_token_type} on {account_type} account")
		return balance
	
	def resolve_current_account_permissions(self, info):
		"""Get permissions for the current active account"""
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return {}
		
		# Get JWT context for account determination
		from .jwt_context import get_jwt_business_context
		jwt_context = get_jwt_business_context(info)
		if not jwt_context:
			return {}
			
		account_type = jwt_context['account_type']
		business_id = jwt_context.get('business_id')
		
		# Personal accounts have no permission restrictions
		if account_type == 'personal':
			return {
				'accept_payments': True,
				'view_transactions': True,
				'view_balance': True,
				'send_funds': True,
				'manage_employees': False,
				'view_business_address': False,
				'view_analytics': False,
				'delete_business': False,
				'edit_business_info': False,
				'manage_bank_accounts': True,
			}
		
		# Business accounts - check employee permissions
		from .permissions import get_user_permissions_for_business
		
		if business_id:
			try:
				business = Business.objects.get(id=business_id)
				return get_user_permissions_for_business(user, business)
			except Business.DoesNotExist:
				return {}
		else:
			# Owner accessing their own business - full permissions
			from .models_employee import BusinessEmployee
			return BusinessEmployee.DEFAULT_PERMISSIONS['owner']

	def resolve_countries(self, info, is_active=None):
		"""Resolve available countries for bank accounts"""
		queryset = Country.objects.all()
		if is_active is not None:
			queryset = queryset.filter(is_active=is_active)
		return queryset.order_by('display_order', 'name')

	def resolve_banks(self, info, country_code=None):
		"""Resolve banks for a specific country"""
		queryset = Bank.objects.filter(is_active=True)
		if country_code:
			queryset = queryset.filter(country__code=country_code)
		return queryset.order_by('country__display_order', 'display_order', 'name')

	def resolve_user_bank_accounts(self, info, account_id=None):
		"""Resolve bank accounts for the current user based on active account context"""
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return []
		
		# Get account context from middleware
		account_type = getattr(info.context, 'active_account_type', 'personal')
		account_index = getattr(info.context, 'active_account_index', 0)
		business_id = getattr(info.context, 'active_business_id', None)
		
		queryset = BankInfo.objects.select_related('country', 'bank', 'account')
		
		if account_type == 'business' and business_id:
			# Business account context - filter by business
			try:
				business = Business.objects.get(id=business_id)
				
				# Check if user has access to this business (owner or employee)
				has_access = False
				
				# Check if user owns this business
				if Account.objects.filter(user=user, business=business, account_type='business').exists():
					has_access = True
				else:
					# Check if user is an employee with permission
					from .models_employee import BusinessEmployee
					employee_record = BusinessEmployee.objects.filter(
						user=user, 
						business=business, 
						is_active=True,
						deleted_at__isnull=True
					).first()
					
					if employee_record:
						try:
							from .permissions import check_employee_permission
							check_employee_permission(user, business, 'manage_bank_accounts')
							has_access = True
						except PermissionDenied:
							has_access = False
				
				if has_access:
					# Filter by business accounts
					queryset = queryset.filter(account__business=business, account__account_type='business')
				else:
					return []
					
			except Business.DoesNotExist:
				return []
		else:
			# Personal account context - filter by user's personal accounts
			queryset = queryset.filter(account__user=user, account__account_type='personal')
		
		return queryset.order_by('-is_default', '-created_at')

	def resolve_bank_info(self, info, id):
		"""Resolve specific bank info by ID"""
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return None
		
		try:
			bank_info = BankInfo.objects.select_related('country', 'bank', 'account').get(
				id=id, 
				account__user=user
			)
			
			# Check permissions for business accounts
			if bank_info.account.account_type == 'business':
				business = bank_info.account.get_business()
				if business:
					# Check if user is an employee accessing business account
					business_id = getattr(info.context, 'active_business_id', None)
					if business_id and str(business.id) == str(business_id):
						# Employee accessing business account
						try:
							check_employee_permission(user, business, 'manage_bank_accounts')
						except PermissionDenied:
							# Employee without permission - return None
							return None
			
			return bank_info
		except BankInfo.DoesNotExist:
			return None

	def resolve_check_users_by_phones(self, info, phone_numbers):
		"""Check which phone numbers belong to Confío users"""
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return []
		
		results = []
		
		# Clean and normalize phone numbers
		for phone in phone_numbers:
			# Clean the phone number - remove all non-digits
			cleaned_phone = ''.join(filter(str.isdigit, phone))
			
			if not cleaned_phone:
				continue
			
			# Try to find user by phone number
			# Check both with and without country code
			found_user = None
			
			# First, try exact match
			found_user = User.objects.filter(phone_number=cleaned_phone).first()
			
			# If not found, try without country code (last 10 digits for Venezuelan numbers)
			if not found_user and len(cleaned_phone) > 10:
				phone_without_code = cleaned_phone[-10:]
				found_user = User.objects.filter(phone_number=phone_without_code).first()
			
			# If not found, try with Venezuelan country code
			if not found_user and not cleaned_phone.startswith('58'):
				phone_with_ve_code = '58' + cleaned_phone
				found_user = User.objects.filter(phone_number=phone_with_ve_code).first()
			
			if found_user:
				# Get the user's active account
				active_account = found_user.accounts.filter(account_type='personal', account_index=0).first()
				
				results.append(UserByPhoneType(
					phone_number=phone,  # Return original phone number for matching
					user_id=found_user.id,
					username=found_user.username,
					first_name=found_user.first_name,
					last_name=found_user.last_name,
					is_on_confio=True,
					active_account_id=active_account.id if active_account else None,
					active_account_sui_address=active_account.sui_address if active_account else None
				))
			else:
				# User not found on Confío
				results.append(UserByPhoneType(
					phone_number=phone,
					user_id=None,
					username=None,
					first_name=None,
					last_name=None,
					is_on_confio=False,
					active_account_id=None,
					active_account_sui_address=None
				))
		
		return results

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

			# Automatically create BusinessEmployee record with owner role
			from .models_employee import BusinessEmployee
			BusinessEmployee.objects.create(
				business=business,
				user=user,
				role='owner',
				hired_by=user,  # Owner hires themselves
				is_active=True
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

class SwitchAccountToken(graphene.Mutation):
	"""Generate a new JWT token with updated account context"""
	class Arguments:
		account_type = graphene.String(required=True)
		account_index = graphene.Int(required=True)
		business_id = graphene.ID(required=False)  # Optional, for employee switching to business
	
	token = graphene.String()
	payload = graphene.JSONString()
	
	@classmethod
	def mutate(cls, root, info, account_type, account_index, business_id=None):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			raise Exception("Authentication required")
		
		logger.info(f"SwitchAccountToken - Received parameters: account_type={account_type}, account_index={account_index}, business_id={business_id}")
		logger.info(f"SwitchAccountToken - User: {user.username} (id={user.id})")
		
		try:
			from .models import Account
			from .models_employee import BusinessEmployee
			
			# For business accounts with business_id, check if user is employee
			if account_type == 'business' and business_id:
				# Check if user has employee relation to this business
				employee_record = BusinessEmployee.objects.filter(
					user=user,
					business_id=business_id,
					is_active=True,
					deleted_at__isnull=True
				).first()
				
				if not employee_record:
					# Also check if user owns this business
					owned_account = Account.objects.filter(
						user=user,
						business_id=business_id,
						account_type='business',
						deleted_at__isnull=True
					).first()
					
					if not owned_account:
						raise Exception("You don't have access to this business account")
			else:
				# For personal accounts or business without business_id, find owned account
				account = Account.objects.get(
					user=user,
					account_type=account_type,
					account_index=account_index,
					deleted_at__isnull=True
				)
				
				# If it's a business account and no business_id was provided, get it from the account
				if account_type == 'business' and not business_id and hasattr(account, 'business') and account.business:
					business_id = str(account.business.id)
					logger.info(f"SwitchAccountToken - Retrieved business_id from owned account: {business_id}")
			
			# Generate new token with account context
			from users.jwt import refresh_token_payload_handler
			from graphql_jwt.settings import jwt_settings
			import jwt
			
			# Use the refresh_token_payload_handler which accepts account context directly
			# but modify the expiry and type for access token
			now = datetime.utcnow()
			new_payload = {
				'user_id': user.id,
				'username': user.get_username(),
				'origIat': int(now.timestamp()),
				'auth_token_version': user.auth_token_version,
				'exp': int((now + timedelta(hours=1)).timestamp()),  # 1 hour for access token
				'type': 'access',
				# Account context fields
				'account_type': account_type,
				'account_index': account_index,
				'business_id': business_id  # Will be set for BOTH owned and employee business accounts
			}
			
			logger.info(f"SwitchAccountToken - Generated payload with: account_type={account_type}, account_index={account_index}, business_id={business_id}")
			
			# Encode the token manually to ensure our payload is used
			new_token = jwt.encode(
				new_payload,
				jwt_settings.JWT_SECRET_KEY,
				jwt_settings.JWT_ALGORITHM
			)
			
			return SwitchAccountToken(
				token=new_token,
				payload=new_payload
			)
			
		except Account.DoesNotExist:
			raise Exception("Account not found")
		except Exception as e:
			logger.error(f"Error switching account token: {str(e)}")
			raise Exception(str(e))


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
			
			# Extract account context from refresh token
			account_type = payload.get('account_type', 'personal')
			account_index = payload.get('account_index', 0)
			business_id = payload.get('business_id')
			
			# Create a mock context object with account info
			class MockContext:
				def __init__(self, account_type, account_index):
					self.active_account_type = account_type
					self.active_account_index = account_index
			
			context = MockContext(account_type, account_index)
			
			# Generate new access token with account context
			from users.jwt import jwt_payload_handler
			new_payload = jwt_payload_handler(user, context)
			new_access_token = jwt_encode(new_payload)
			
			# Calculate refresh expiration
			refresh_exp = int((datetime.utcnow() + timedelta(days=365)).timestamp())
			
			return RefreshToken(
				token=new_access_token,
				payload=new_payload,
				refreshExpiresIn=refresh_exp
			)
		except Exception as e:
			raise Exception(str(e))


class CreateBankInfo(graphene.Mutation):
	class Arguments:
		account_id = graphene.ID(required=True)
		payment_method_id = graphene.ID(required=True)
		account_holder_name = graphene.String(required=True)
		account_number = graphene.String()
		phone_number = graphene.String()
		email = graphene.String()
		username = graphene.String()
		account_type = graphene.String()
		identification_number = graphene.String()
		is_default = graphene.Boolean()

	success = graphene.Boolean()
	error = graphene.String()
	bank_info = graphene.Field(BankInfoType)

	@classmethod
	def mutate(cls, root, info, account_id, payment_method_id, account_holder_name, 
	          account_number=None, phone_number=None, email=None, username=None,
	          account_type=None, identification_number=None, is_default=False):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return CreateBankInfo(success=False, error="Authentication required")

		try:
			# Verify account belongs to user
			account = Account.objects.get(id=account_id, user=user)
			
			# Check employee permissions for business accounts
			if account.account_type == 'business':
				business = account.get_business()
				if business:
					# Check if user is an employee accessing business account
					business_id = getattr(info.context, 'active_business_id', None)
					if business_id and str(business.id) == str(business_id):
						# Employee accessing business account
						try:
							check_employee_permission(user, business, 'manage_bank_accounts')
						except PermissionDenied:
							return CreateBankInfo(
								success=False,
								error="You don't have permission to manage bank accounts for this business"
							)
			
			# Import P2PPaymentMethod
			from p2p_exchange.models import P2PPaymentMethod
			
			# Verify payment method exists
			payment_method = P2PPaymentMethod.objects.get(id=payment_method_id, is_active=True)
			
			# Validate required fields based on payment method type
			if payment_method.requires_account_number and not account_number:
				return CreateBankInfo(
					success=False,
					error="Número de cuenta es requerido para este método de pago"
				)
			
			if payment_method.requires_phone and not phone_number:
				return CreateBankInfo(
					success=False,
					error="Número de teléfono es requerido para este método de pago"
				)
			
			if payment_method.requires_email and not email:
				return CreateBankInfo(
					success=False,
					error="Email es requerido para este método de pago"
				)
			
			# For bank payment methods, validate identification requirement
			if payment_method.bank and payment_method.bank.country.requires_identification and not identification_number:
				return CreateBankInfo(
					success=False,
					error=f"{payment_method.bank.country.identification_name} es requerido para cuentas bancarias en {payment_method.bank.country.name}"
				)
			
			# Check for duplicate payment method
			duplicate_filter = {
				'account': account,
				'payment_method': payment_method
			}
			
			# Add specific duplicate checks based on payment method type
			if payment_method.requires_account_number and account_number:
				duplicate_filter['account_number'] = account_number
			elif payment_method.requires_phone and phone_number:
				duplicate_filter['phone_number'] = phone_number
			elif payment_method.requires_email and email:
				duplicate_filter['email'] = email
			
			existing = BankInfo.objects.filter(**duplicate_filter).first()
			
			if existing:
				return CreateBankInfo(
					success=False,
					error="Ya tienes registrado este método de pago"
				)

			# Create bank info
			bank_info = BankInfo.objects.create(
				account=account,
				payment_method=payment_method,
				account_holder_name=account_holder_name.strip(),
				account_number=account_number.strip() if account_number else None,
				phone_number=phone_number.strip() if phone_number else None,
				email=email.strip() if email else None,
				username=username.strip() if username else None,
				account_type=account_type,
				identification_number=identification_number.strip() if identification_number else None,
				is_default=is_default
			)
			
			# Set legacy fields for backward compatibility (if it's a bank payment method)
			if payment_method.bank:
				bank_info.bank = payment_method.bank
				bank_info.country = payment_method.bank.country
				bank_info.save()

			return CreateBankInfo(success=True, error=None, bank_info=bank_info)

		except Account.DoesNotExist:
			return CreateBankInfo(success=False, error="Cuenta no encontrada")
		except P2PPaymentMethod.DoesNotExist:
			return CreateBankInfo(success=False, error="Método de pago no encontrado")
		except Exception as e:
			logger.error(f"Error creating bank info: {str(e)}")
			return CreateBankInfo(success=False, error="Error interno del servidor")


class UpdateBankInfo(graphene.Mutation):
	class Arguments:
		bank_info_id = graphene.ID(required=True)
		account_holder_name = graphene.String(required=True)
		account_number = graphene.String(required=True)
		account_type = graphene.String(required=True)
		identification_number = graphene.String()
		is_default = graphene.Boolean()

	success = graphene.Boolean()
	error = graphene.String()
	bank_info = graphene.Field(BankInfoType)

	@classmethod
	def mutate(cls, root, info, bank_info_id, account_holder_name, account_number,
	          account_type, identification_number=None, is_default=False):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return UpdateBankInfo(success=False, error="Authentication required")

		try:
			# Get bank info and verify ownership
			bank_info = BankInfo.objects.select_related('country', 'bank', 'account').get(
				id=bank_info_id,
				account__user=user
			)
			
			# Check employee permissions for business accounts
			if bank_info.account.account_type == 'business':
				business = bank_info.account.get_business()
				if business:
					# Check if user is an employee accessing business account
					business_id = getattr(info.context, 'active_business_id', None)
					if business_id and str(business.id) == str(business_id):
						# Employee accessing business account
						try:
							check_employee_permission(user, business, 'manage_bank_accounts')
						except PermissionDenied:
							return UpdateBankInfo(
								success=False,
								error="You don't have permission to manage bank accounts for this business"
							)
			
			# Validate identification requirement
			if bank_info.country.requires_identification and not identification_number:
				return UpdateBankInfo(
					success=False,
					error=f"{bank_info.country.identification_name} es requerido para cuentas bancarias en {bank_info.country.name}"
				)

			# Update bank info
			bank_info.account_holder_name = account_holder_name.strip()
			bank_info.account_number = account_number.strip()
			bank_info.account_type = account_type
			bank_info.identification_number = identification_number.strip() if identification_number else None
			bank_info.is_default = is_default
			bank_info.save()

			return UpdateBankInfo(success=True, error=None, bank_info=bank_info)

		except BankInfo.DoesNotExist:
			return UpdateBankInfo(success=False, error="Información bancaria no encontrada")
		except Exception as e:
			logger.error(f"Error updating bank info: {str(e)}")
			return UpdateBankInfo(success=False, error="Error interno del servidor")


class DeleteBankInfo(graphene.Mutation):
	class Arguments:
		bank_info_id = graphene.ID(required=True)

	success = graphene.Boolean()
	error = graphene.String()

	@classmethod
	def mutate(cls, root, info, bank_info_id):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return DeleteBankInfo(success=False, error="Authentication required")

		try:
			# Get bank info and verify ownership
			bank_info = BankInfo.objects.get(
				id=bank_info_id,
				account__user=user
			)
			
			# Check employee permissions for business accounts
			if bank_info.account.account_type == 'business':
				business = bank_info.account.get_business()
				if business:
					# Check if user is an employee accessing business account
					business_id = getattr(info.context, 'active_business_id', None)
					if business_id and str(business.id) == str(business_id):
						# Employee accessing business account
						try:
							check_employee_permission(user, business, 'manage_bank_accounts')
						except PermissionDenied:
							return DeleteBankInfo(
								success=False,
								error="You don't have permission to manage bank accounts for this business"
							)

			# Soft delete the bank info
			bank_info.soft_delete()

			return DeleteBankInfo(success=True, error=None)

		except BankInfo.DoesNotExist:
			return DeleteBankInfo(success=False, error="Información bancaria no encontrada")
		except Exception as e:
			logger.error(f"Error deleting bank info: {str(e)}")
			return DeleteBankInfo(success=False, error="Error interno del servidor")


class CreateTestUsers(graphene.Mutation):
	"""Test mutation to create users based on phone numbers - FOR TESTING ONLY"""
	class Arguments:
		phone_numbers = graphene.List(graphene.String, required=True)
	
	success = graphene.Boolean()
	error = graphene.String()
	created_count = graphene.Int()
	users_created = graphene.List(UserByPhoneType)
	
	@classmethod
	def mutate(cls, root, info, phone_numbers):
		# Only allow in development/testing
		from django.conf import settings
		if not settings.DEBUG:
			return CreateTestUsers(
				success=False, 
				error="This mutation is only available in DEBUG mode",
				created_count=0,
				users_created=[]
			)
		
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return CreateTestUsers(success=False, error="Authentication required", created_count=0, users_created=[])
		
		import random
		
		created_users = []
		skipped_reasons = []
		
		# Randomly select 30% of phone numbers to be Confío users
		total_phones = len(phone_numbers)
		confio_count = int(total_phones * 0.3)  # 30% will be Confío users
		
		# Shuffle the phone numbers and select the first 30%
		shuffled_phones = phone_numbers.copy()
		random.shuffle(shuffled_phones)
		confio_phones = set(shuffled_phones[:confio_count])
		
		logger.info(f"Creating test users for {confio_count} out of {total_phones} contacts (30%)")
		
		for phone in phone_numbers:
			# Only process phones that should be Confío users
			if phone not in confio_phones:
				skipped_reasons.append(f"{phone}: Not selected as Confío user (70% are external)")
				continue
			
			# Clean the phone number
			cleaned_phone = ''.join(filter(str.isdigit, phone))
			if not cleaned_phone:
				skipped_reasons.append(f"{phone}: Empty after cleaning")
				continue
			
			# Check if user already exists (try multiple formats)
			existing_user = None
			
			# Try exact match
			existing_user = User.objects.filter(phone_number=cleaned_phone).first()
			
			# Try without country code (last 10 digits for Venezuelan numbers)
			if not existing_user and len(cleaned_phone) > 10:
				phone_without_code = cleaned_phone[-10:]
				existing_user = User.objects.filter(phone_number=phone_without_code).first()
			
			# Try with Venezuelan country code
			if not existing_user and not cleaned_phone.startswith('58'):
				phone_with_ve_code = '58' + cleaned_phone
				existing_user = User.objects.filter(phone_number=phone_with_ve_code).first()
			
			if existing_user:
				skipped_reasons.append(f"{phone}: User already exists with username {existing_user.username}")
				logger.info(f"User already exists for phone {cleaned_phone}: {existing_user.username}")
				continue
			
			# Create a test user
			try:
				# Generate a unique username based on phone (max 66 chars)
				# Use last 6 digits of phone for base username
				phone_suffix = cleaned_phone[-6:] if len(cleaned_phone) >= 6 else cleaned_phone
				base_username = f"test_{phone_suffix}"
				username = base_username
				counter = 1
				while User.objects.filter(username=username).exists():
					username = f"{base_username}_{counter}"
					counter += 1
					# Ensure username doesn't exceed 66 chars
					if len(username) > 66:
						username = f"t_{phone_suffix}_{counter}"
				
				# Create the user with a unique firebase_uid
				new_user = User.objects.create(
					username=username,
					phone_number=cleaned_phone,
					phone_country='VE',  # Default to Venezuela
					first_name=f"Test",
					last_name=f"User {cleaned_phone[-4:]}",
					email=f"{username}@test.com",  # Use shorter email based on username
					firebase_uid=f"test_uid_{cleaned_phone}"  # Unique firebase UID for test users
				)
				
				# Create personal account
				from .models import Account
				import hashlib
				
				# Generate a valid Sui address using hash of phone number
				# Sui addresses are 0x + 64 hex characters (32 bytes)
				phone_hash = hashlib.sha256(cleaned_phone.encode()).hexdigest()
				test_sui_address = f"0x{phone_hash}"
				
				personal_account = Account.objects.create(
					user=new_user,
					account_type='personal',
					account_index=0,
					sui_address=test_sui_address  # Valid Sui address format
				)
				
				created_users.append(UserByPhoneType(
					phone_number=phone,
					user_id=new_user.id,
					username=new_user.username,
					first_name=new_user.first_name,
					last_name=new_user.last_name,
					is_on_confio=True,
					active_account_id=personal_account.id,
					active_account_sui_address=personal_account.sui_address
				))
				
				logger.info(f"Created test user: {username} for phone: {cleaned_phone}")
			except Exception as e:
				logger.error(f"Error creating test user for {phone}: {str(e)}")
				continue
		
		# Build summary message
		summary = f"Created {len(created_users)} test users from {total_phones} contacts ({confio_count} selected as Confío users - 30%)"
		
		return CreateTestUsers(
			success=True,
			error=summary,  # Using error field to return the informative message
			created_count=len(created_users),
			users_created=created_users
		)


class DeleteTestUsers(graphene.Mutation):
	"""Delete test users - FOR TESTING ONLY"""
	class Arguments:
		pass  # No arguments needed, deletes all test users
	
	success = graphene.Boolean()
	error = graphene.String()
	deleted_count = graphene.Int()
	
	@classmethod
	def mutate(cls, root, info):
		# Only allow in development/testing
		from django.conf import settings
		if not settings.DEBUG:
			return DeleteTestUsers(
				success=False, 
				error="This mutation is only available in DEBUG mode",
				deleted_count=0
			)
		
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return DeleteTestUsers(success=False, error="Authentication required", deleted_count=0)
		
		# Delete all test users (username starts with 'test_')
		deleted_count = User.objects.filter(username__startswith='test_').delete()[0]
		
		return DeleteTestUsers(
			success=True,
			error=None,
			deleted_count=deleted_count
		)


class SetDefaultBankInfo(graphene.Mutation):
	class Arguments:
		bank_info_id = graphene.ID(required=True)

	success = graphene.Boolean()
	error = graphene.String()
	bank_info = graphene.Field(BankInfoType)

	@classmethod
	def mutate(cls, root, info, bank_info_id):
		user = getattr(info.context, 'user', None)
		if not (user and getattr(user, 'is_authenticated', False)):
			return SetDefaultBankInfo(success=False, error="Authentication required")

		try:
			# Get bank info and verify ownership
			bank_info = BankInfo.objects.get(
				id=bank_info_id,
				account__user=user
			)
			
			# Check employee permissions for business accounts
			if bank_info.account.account_type == 'business':
				business = bank_info.account.get_business()
				if business:
					# Check if user is an employee accessing business account
					business_id = getattr(info.context, 'active_business_id', None)
					if business_id and str(business.id) == str(business_id):
						# Employee accessing business account
						try:
							check_employee_permission(user, business, 'manage_bank_accounts')
						except PermissionDenied:
							return SetDefaultBankInfo(
								success=False,
								error="You don't have permission to manage bank accounts for this business"
							)

			# Set as default (this will unset others automatically)
			bank_info.set_as_default()

			return SetDefaultBankInfo(success=True, error=None, bank_info=bank_info)

		except BankInfo.DoesNotExist:
			return SetDefaultBankInfo(success=False, error="Información bancaria no encontrada")
		except Exception as e:
			logger.error(f"Error setting default bank info: {str(e)}")
			return SetDefaultBankInfo(success=False, error="Error interno del servidor")

class Mutation(EmployeeMutations, graphene.ObjectType):
	update_phone_number = UpdatePhoneNumber.Field()
	update_username = UpdateUsername.Field()
	update_user_profile = UpdateUserProfile.Field()
	invalidate_auth_tokens = InvalidateAuthTokens.Field()
	refresh_token = RefreshToken.Field()
	switch_account_token = SwitchAccountToken.Field()
	submit_identity_verification = SubmitIdentityVerification.Field()
	approve_identity_verification = ApproveIdentityVerification.Field()
	reject_identity_verification = RejectIdentityVerification.Field()
	create_business = CreateBusiness.Field()
	update_business = UpdateBusiness.Field()
	update_account_sui_address = UpdateAccountSuiAddress.Field()
	
	# Bank info mutations
	create_bank_info = CreateBankInfo.Field()
	update_bank_info = UpdateBankInfo.Field()
	delete_bank_info = DeleteBankInfo.Field()
	set_default_bank_info = SetDefaultBankInfo.Field()
	
	# Test mutations (only in DEBUG mode)
	create_test_users = CreateTestUsers.Field()
	delete_test_users = DeleteTestUsers.Field()
