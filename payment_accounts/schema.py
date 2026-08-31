import graphene
import logging
from django.conf import settings
from graphene_django import DjangoObjectType

from payment_accounts.eligibility import (
    EligibilityDenied,
    EligibilityPolicyNotConfigured,
    context_from_identity,
    evaluate_active_policy,
)
from payment_accounts.clients import (
    ComplianceHandoffError,
    ProviderAPIError,
    ProviderConfigurationError,
)
from payment_accounts.models import (
    AccountCapability,
    FinancialAccount,
    FundingInstruction,
    MoneyFlow,
    MoneyOperation,
    PayoutDestination,
    ProviderProfile,
)
from payment_accounts.services import (
    PaymentAccountError,
    create_and_submit_payout,
    create_funding_instruction,
    create_payout_destination,
    create_and_submit_transfer,
    provision_payment_account,
)
from security.models import IdentityVerification
from users.jwt_context import get_jwt_business_context_with_validation, is_business_employee
from users.models import Account

logger = logging.getLogger(__name__)


def _public_error(exc):
    if isinstance(exc, (
        PaymentAccountError, ComplianceHandoffError,
        EligibilityDenied, EligibilityPolicyNotConfigured,
    )):
        return str(exc)
    if isinstance(exc, ProviderConfigurationError):
        return 'Payment provider is not configured'
    if isinstance(exc, ProviderAPIError):
        logger.warning('Payment provider request failed', exc_info=True)
        return 'Payment provider request failed'
    logger.exception('Unexpected payment account error')
    return 'Unable to complete the payment account request'


def _active_account(info, *, permission=None, owner_only=False):
    context = get_jwt_business_context_with_validation(info, required_permission=permission)
    if not context:
        raise PaymentAccountError('Invalid or unauthorized account context')
    if context['account_type'] == 'business' and context.get('business_id'):
        if owner_only and is_business_employee(info.context.user, context['business_id']):
            raise PaymentAccountError('Only the business owner can manage provider accounts')
        account = Account.objects.filter(
            business_id=context['business_id'],
            account_type='business',
            account_index=context.get('account_index', 0),
            deleted_at__isnull=True,
        ).first()
    else:
        account = Account.objects.filter(
            user=info.context.user,
            account_type='personal',
            account_index=context.get('account_index', 0),
            deleted_at__isnull=True,
        ).first()
    if not account:
        raise PaymentAccountError('Active Confío account not found')
    return account


def _verified_identity(account):
    identities = IdentityVerification.objects.filter(user=account.user, status='verified')
    if account.account_type == 'business':
        identities = identities.filter(
            risk_factors__provider='didit',
            risk_factors__account_type='business',
            risk_factors__business_id=str(account.business_id),
            risk_factors__didit__session__session_kind='business',
        )
    else:
        identities = identities.filter(risk_factors__provider='didit').exclude(
            risk_factors__account_type='business'
        )
    identity = identities.order_by('-updated_at').first()
    if not identity:
        requirement = 'business Didit KYB' if account.account_type == 'business' else 'Didit KYC'
        raise PaymentAccountError(f'Verified {requirement} required')
    return identity


class ProviderProfileType(DjangoObjectType):
    class Meta:
        model = ProviderProfile
        fields = ('internal_id', 'provider', 'owner_type', 'status', 'provider_status', 'created_at')

    kyc_url = graphene.String()

    def resolve_kyc_url(self, info):
        latest = (self.provider_data or {}).get('latest') or {}
        return latest.get('kyc_url') or latest.get('kycUrl') or ''


class ProxyAccountInput(graphene.InputObjectType):
    beneficiary_address_line = graphene.String()
    beneficiary_city = graphene.String()
    beneficiary_country = graphene.String()
    beneficiary_birthdate = graphene.String()
    beneficiary_email = graphene.String()
    business_type = graphene.String()
    business_registration_number = graphene.String()
    business_contact_name = graphene.String()
    business_phone_number = graphene.String()
    business_address_line = graphene.String()
    business_city = graphene.String()
    business_country = graphene.String()


class PayoutDestinationDetailsInput(graphene.InputObjectType):
    type = graphene.String()
    key_value = graphene.String()
    cbu = graphene.String()
    alias = graphene.String()
    qr_code = graphene.String()
    account_number = graphene.String()
    name = graphene.String()
    document_number = graphene.String()
    reference = graphene.String()
    bank_code = graphene.String()
    bank_branch = graphene.String()
    client_id = graphene.String()
    ispb = graphene.String()
    number = graphene.String()
    issuer = graphene.String()
    account_type = graphene.String()
    br_code = graphene.String()
    chave_pix = graphene.String()
    currency = graphene.String()
    document_type = graphene.String()
    full_name = graphene.String()
    breb_key = graphene.String()
    clabe = graphene.String()
    latitude = graphene.Float()
    longitude = graphene.Float()
    cci_number = graphene.String()
    state = graphene.String()
    email = graphene.String()
    iban = graphene.String()
    sort_code = graphene.String()
    beneficiary_type = graphene.String()
    beneficiary_first_name = graphene.String()
    beneficiary_last_name = graphene.String()
    beneficiary_country = graphene.String()
    beneficiary_city = graphene.String()
    beneficiary_postal_code = graphene.String()
    proxy_account = graphene.InputField(ProxyAccountInput)
    instant = graphene.Boolean()
    address = graphene.String()
    accepts_retries = graphene.Boolean()


_CAMEL_DESTINATION_FIELDS = {
    'qr_code': 'qrCode', 'account_number': 'accountNumber',
    'document_number': 'documentNumber', 'bank_code': 'bankCode',
    'bank_branch': 'bankBranch', 'client_id': 'clientId',
    'account_type': 'accountType', 'br_code': 'brCode',
    'chave_pix': 'chavePix', 'document_type': 'documentType',
    'full_name': 'fullName', 'breb_key': 'brebKey',
    'cci_number': 'cciNumber', 'sort_code': 'sortCode',
    'beneficiary_type': 'beneficiaryType',
    'beneficiary_first_name': 'beneficiaryFirstName',
    'beneficiary_last_name': 'beneficiaryLastName',
    'beneficiary_country': 'beneficiaryCountry',
    'beneficiary_city': 'beneficiaryCity',
    'beneficiary_postal_code': 'beneficiaryPostalCode',
    'proxy_account': 'proxyAccount', 'accepts_retries': 'acceptsRetries',
    'beneficiary_address_line': 'beneficiaryAddressLine',
    'beneficiary_birthdate': 'beneficiaryBirthdate',
    'beneficiary_email': 'beneficiaryEmail', 'business_type': 'businessType',
    'business_registration_number': 'businessRegistrationNumber',
    'business_contact_name': 'businessContactName',
    'business_phone_number': 'businessPhoneNumber',
    'business_address_line': 'businessAddressLine',
    'business_city': 'businessCity', 'business_country': 'businessCountry',
}


def _destination_details(value):
    def convert(mapping):
        output = {}
        for key, item in dict(mapping or {}).items():
            if item is None:
                continue
            if key == 'proxy_account':
                item = convert(item)
            output[_CAMEL_DESTINATION_FIELDS.get(key, key)] = item
        return output

    return convert(value)


class FundingInstructionType(DjangoObjectType):
    class Meta:
        model = FundingInstruction
        fields = (
            'internal_id', 'kind', 'status', 'reusable', 'expires_at',
            'display_value', 'holder_display_name', 'ownership_evidence_available',
        )


class AccountCapabilityType(DjangoObjectType):
    class Meta:
        model = AccountCapability
        fields = ('capability', 'status', 'reason', 'evaluated_at')


class FinancialAccountType(DjangoObjectType):
    class Meta:
        model = FinancialAccount
        fields = (
            'internal_id', 'ownership_structure', 'country', 'asset', 'status',
            'provider_status', 'available_balance', 'current_balance',
            'balance_updated_at', 'funding_instructions', 'capabilities', 'created_at',
        )

    provider = graphene.String(required=True)

    def resolve_provider(self, info):
        return self.provider_profile.provider


class MoneyOperationType(DjangoObjectType):
    class Meta:
        model = MoneyOperation
        fields = (
            'internal_id', 'provider', 'operation_type', 'status', 'provider_status',
            'source_asset', 'source_amount', 'target_asset', 'target_amount',
            'provider_fee', 'failure_code', 'failure_detail',
            'created_at', 'submitted_at', 'settled_at',
        )


class MoneyFlowType(DjangoObjectType):
    class Meta:
        model = MoneyFlow
        fields = (
            'internal_id', 'kind', 'status', 'source_asset', 'source_amount',
            'target_asset', 'target_amount', 'gross_amount', 'net_amount',
            'provider_cost', 'created_at', 'completed_at', 'operations',
        )


class PayoutDestinationType(DjangoObjectType):
    class Meta:
        model = PayoutDestination
        fields = (
            'internal_id', 'provider', 'kind', 'country', 'asset', 'label',
            'holder_name', 'holder_id_type', 'status', 'created_at',
        )


class EligibilityResultType(graphene.ObjectType):
    decision = graphene.String(required=True)
    reason_code = graphene.String(required=True)
    allowed = graphene.Boolean(required=True)
    policy_version = graphene.Int(required=True)


class ProvisionPaymentAccount(graphene.Mutation):
    class Arguments:
        provider = graphene.String(required=True)
        country = graphene.String(required=True)
        asset = graphene.String(required=True)
        share_compliance_data = graphene.Boolean(required=False, default_value=False)

    success = graphene.Boolean(required=True)
    profile = graphene.Field(ProviderProfileType)
    account = graphene.Field(FinancialAccountType)
    errors = graphene.List(graphene.String, required=True)

    @classmethod
    def mutate(cls, root, info, provider, country, asset, share_compliance_data=False):
        try:
            provider = provider.strip().lower()
            if provider not in {'cobre', 'infinia'}:
                raise PaymentAccountError('Unsupported provider')
            infinia_kyc_mode = getattr(settings, 'INFINIA_KYC_MODE', '')
            if provider == 'infinia' and infinia_kyc_mode != 'SELF_DECLARED':
                raise PaymentAccountError(
                    'Infinia provisioning requires approved SELF_DECLARED mode'
                )
            if provider == 'infinia' and not share_compliance_data:
                raise PaymentAccountError(
                    'Consent to share Didit compliance data with Infinia is required'
                )
            account = _active_account(info, permission='manage_bank_accounts', owner_only=True)
            identity = _verified_identity(account)
            profile, financial_account = provision_payment_account(
                confio_account=account,
                provider=provider,
                identity=identity,
                country=country,
                asset=asset,
                ownership_structure=(
                    'omnibus_subledger' if provider == 'cobre' else 'provider_named'
                ),
                kyc_mode=infinia_kyc_mode if provider == 'infinia' else '',
                compliance_consent=share_compliance_data if provider == 'infinia' else False,
            )
            return cls(success=True, profile=profile, account=financial_account, errors=[])
        except Exception as exc:
            return cls(success=False, profile=None, account=None, errors=[_public_error(exc)])


class CreateReceivingInstruction(graphene.Mutation):
    class Arguments:
        financial_account_id = graphene.UUID(required=True)
        kind = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    account = graphene.Field(FinancialAccountType)
    errors = graphene.List(graphene.String, required=True)

    @classmethod
    def mutate(cls, root, info, financial_account_id, kind):
        try:
            account = _active_account(info, permission='manage_bank_accounts', owner_only=True)
            financial_account = FinancialAccount.objects.select_related(
                'provider_profile'
            ).filter(
                internal_id=financial_account_id,
                provider_profile__confio_account=account,
            ).first()
            if not financial_account:
                raise PaymentAccountError('Financial account not found')
            create_funding_instruction(financial_account=financial_account, kind=kind)
            return cls(success=True, account=financial_account, errors=[])
        except Exception as exc:
            return cls(success=False, account=None, errors=[_public_error(exc)])


class CreatePayoutDestination(graphene.Mutation):
    class Arguments:
        provider = graphene.String(required=True)
        kind = graphene.String(required=True)
        country = graphene.String(required=True)
        asset = graphene.String(required=True)
        label = graphene.String(required=True)
        holder_name = graphene.String(required=True)
        holder_id_type = graphene.String(default_value='')
        holder_id_number = graphene.String(default_value='')
        details = graphene.Argument(PayoutDestinationDetailsInput, required=True)

    success = graphene.Boolean(required=True)
    destination = graphene.Field(PayoutDestinationType)
    errors = graphene.List(graphene.String, required=True)

    @classmethod
    def mutate(cls, root, info, **kwargs):
        try:
            account = _active_account(info, permission='manage_bank_accounts', owner_only=True)
            provider = kwargs.pop('provider').strip().lower()
            if provider not in {'cobre', 'infinia'}:
                raise PaymentAccountError('Unsupported provider')
            kwargs['details'] = _destination_details(kwargs.get('details'))
            destination = create_payout_destination(
                confio_account=account, provider=provider, **kwargs
            )
            return cls(success=True, destination=destination, errors=[])
        except Exception as exc:
            return cls(success=False, destination=None, errors=[_public_error(exc)])


class CreatePaymentPayout(graphene.Mutation):
    class Arguments:
        financial_account_id = graphene.UUID(required=True)
        destination_id = graphene.UUID(required=True)
        amount = graphene.Decimal(required=True)
        request_id = graphene.UUID(required=True)

    success = graphene.Boolean(required=True)
    operation = graphene.Field(MoneyOperationType)
    errors = graphene.List(graphene.String, required=True)

    @classmethod
    def mutate(cls, root, info, financial_account_id, destination_id, amount, request_id):
        try:
            account = _active_account(info, permission='send_funds', owner_only=True)
            source = FinancialAccount.objects.select_related('provider_profile').filter(
                internal_id=financial_account_id,
                provider_profile__confio_account=account,
                status='active',
            ).first()
            destination = PayoutDestination.objects.filter(
                internal_id=destination_id, confio_account=account
            ).first()
            if not source or not destination:
                raise PaymentAccountError('Source account or destination not found')
            operation = create_and_submit_payout(
                confio_account=account,
                source_account=source,
                destination=destination,
                amount=amount,
                client_request_id=request_id,
            )
            return cls(success=True, operation=operation, errors=[])
        except Exception as exc:
            return cls(success=False, operation=None, errors=[_public_error(exc)])


class CreatePaymentTransfer(graphene.Mutation):
    class Arguments:
        source_account_id = graphene.UUID(required=True)
        destination_account_id = graphene.UUID(required=True)
        amount = graphene.Decimal(required=True)
        request_id = graphene.UUID(required=True)

    success = graphene.Boolean(required=True)
    operation = graphene.Field(MoneyOperationType)
    errors = graphene.List(graphene.String, required=True)

    @classmethod
    def mutate(
        cls, root, info, source_account_id, destination_account_id, amount, request_id
    ):
        try:
            account = _active_account(info, permission='send_funds', owner_only=True)
            owned = FinancialAccount.objects.select_related('provider_profile').filter(
                provider_profile__confio_account=account,
                status='active',
                internal_id__in=[source_account_id, destination_account_id],
            )
            by_id = {row.internal_id: row for row in owned}
            source = by_id.get(source_account_id)
            destination = by_id.get(destination_account_id)
            if not source or not destination:
                raise PaymentAccountError('Source account or destination account not found')
            operation = create_and_submit_transfer(
                confio_account=account,
                source_account=source,
                destination_account=destination,
                amount=amount,
                client_request_id=request_id,
            )
            return cls(success=True, operation=operation, errors=[])
        except Exception as exc:
            return cls(success=False, operation=None, errors=[_public_error(exc)])


class Query(graphene.ObjectType):
    my_payment_accounts = graphene.List(FinancialAccountType, required=True)
    my_money_flows = graphene.List(MoneyFlowType, required=True, limit=graphene.Int(default_value=50))
    my_payout_destinations = graphene.List(PayoutDestinationType, required=True)
    payment_account_eligibility = graphene.Field(
        EligibilityResultType,
        provider=graphene.String(required=True),
        scope=graphene.String(required=True),
        account_country=graphene.String(default_value=''),
        destination_country=graphene.String(default_value=''),
    )

    def resolve_my_payment_accounts(self, info):
        account = _active_account(info, permission='view_balance')
        return FinancialAccount.objects.filter(
            provider_profile__confio_account=account
        ).select_related('provider_profile').prefetch_related(
            'funding_instructions', 'capabilities'
        )

    def resolve_my_money_flows(self, info, limit=50):
        account = _active_account(info, permission='view_transactions')
        limit = max(1, min(int(limit or 50), 100))
        return MoneyFlow.objects.filter(confio_account=account).prefetch_related(
            'operations'
        )[:limit]

    def resolve_my_payout_destinations(self, info):
        account = _active_account(info, permission='manage_bank_accounts')
        return PayoutDestination.objects.filter(confio_account=account).order_by('-created_at')

    def resolve_payment_account_eligibility(
        self, info, provider, scope, account_country='', destination_country=''
    ):
        account = _active_account(info, permission='manage_bank_accounts')
        identity = _verified_identity(account)
        context = context_from_identity(
            identity,
            account_country=account_country,
            destination_country=destination_country,
        )
        try:
            result = evaluate_active_policy(
                provider=provider.lower(), scope=scope, context=context
            )
        except EligibilityPolicyNotConfigured as exc:
            return EligibilityResultType(
                decision='block', reason_code=str(exc), allowed=False, policy_version=0
            )
        return EligibilityResultType(
            decision=result.decision,
            reason_code=result.reason_code,
            allowed=result.allowed,
            policy_version=result.policy.version,
        )


class Mutation(graphene.ObjectType):
    provision_payment_account = ProvisionPaymentAccount.Field()
    create_receiving_instruction = CreateReceivingInstruction.Field()
    create_payout_destination = CreatePayoutDestination.Field()
    create_payment_payout = CreatePaymentPayout.Field()
    create_payment_transfer = CreatePaymentTransfer.Field()
