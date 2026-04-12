import logging
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

import graphene
from graphene_django import DjangoObjectType
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone

from security.didit import ISO2_TO_ISO3
from security.models import IdentityVerification
from users.models import Account, BankInfo, Country
from ramps.models import KoyweBankInfo, RampPaymentMethod, RampTransaction, RampUserAddress
from ramps.koywe_sync import sync_koywe_ramp_transaction_from_order, upsert_koywe_ramp_transaction

from ramps.koywe_client import KoyweClient, KoyweConfigurationError, KoyweError
from ramps.koywe import (
    COUNTRY_METHODS,
    RAMP_NETWORK_DISPLAY,
    RAMP_NETWORK_SYMBOL,
    RAMP_USDC_ALGORAND_NOTE,
    RAMP_USDC_ALGORAND_SYMBOL,
    get_country_ramp_config,
    quote_ramp,
    sync_country_payment_methods,
)

logger = logging.getLogger(__name__)

_KOYWE_TEST_OVERRIDE_USERNAMES = {
    'julianmoonluna',
    'julianm',
}

_KOYWE_TEST_ACCOUNT_OVERRIDES = {
    'AR': {
        'email': 'duende-argentina@koywe-test.com',
        'documentType': 'DNI',
        'documentNumber': '30123457',
        'firstName': 'Duende',
        'lastName': 'Argentina',
    },
    'BO': {
        'email': 'duende-bolivia@koywe-test.com',
        'documentType': 'CI',
        'documentNumber': '1234567',
        'firstName': 'Duende',
        'lastName': 'Bolivia',
    },
    'BR': {
        'email': 'duende-brazil@koywe-test.com',
        'documentType': 'CPF',
        'documentNumber': '24085179403',
        'firstName': 'Duende',
        'lastName': 'Brazil',
    },
    'CL': {
        'email': 'duende-chile@koywe-test.com',
        'documentType': 'RUT',
        'documentNumber': '12345678-5',
        'firstName': 'Duende',
        'lastName': 'Chile',
    },
    'CO': {
        'email': 'duende-colombia@koywe-test.com',
        'documentType': 'CED_CIU',
        'documentNumber': '1234567890',
        'firstName': 'Duende',
        'lastName': 'Colombia',
    },
    'MX': {
        'email': 'duende-mexico@koywe-test.com',
        'documentType': 'RFC',
        'documentNumber': 'GODE561231GR8',
        'firstName': 'Duende',
        'lastName': 'Mexico',
    },
    'PE': {
        'email': 'duende-peru@koywe-test.com',
        'documentType': 'DNI',
        'documentNumber': '12345678',
        'firstName': 'Duende',
        'lastName': 'Peru',
    },
}


def _get_wallet_upgrade_blocker(*, user, account):
    if not user or not account:
        return None

    if getattr(account, 'account_type', None) != 'personal':
        return None

    if not getattr(account, 'is_keyless_migrated', False):
        return 'Actualiza tu app para completar la migracion de tu billetera antes de continuar.'

    if getattr(user, 'requires_backup_completion', False):
        return 'Por favor, realiza un respaldo en Google Drive para proteger tu cuenta antes de continuar.'

    return None


class KoyweBankInfoType(graphene.ObjectType):
    bank_code = graphene.String()
    name = graphene.String()
    institution_name = graphene.String()
    country_code = graphene.String()

    bankCode = graphene.String()
    institutionName = graphene.String()
    countryCode = graphene.String()

    def resolve_bankCode(self, info):
        return self.bank_code

    def resolve_institutionName(self, info):
        return self.institution_name

    def resolve_countryCode(self, info):
        return self.country_code


class RampPaymentMethodCatalogType(DjangoObjectType):
    field_schema = graphene.JSONString()

    class Meta:
        model = RampPaymentMethod
        fields = (
            'id',
            'code',
            'country_code',
            'display_name',
            'provider_type',
            'description',
            'icon',
            'is_active',
            'display_order',
            'country',
            'bank',
            'requires_phone',
            'requires_email',
            'requires_account_number',
            'requires_identification',
            'supports_on_ramp',
            'supports_off_ramp',
            'field_schema',
        )

    countryCode = graphene.String()
    displayName = graphene.String()
    providerType = graphene.String()
    isActive = graphene.Boolean()
    displayOrder = graphene.Int()
    requiresPhone = graphene.Boolean()
    requiresEmail = graphene.Boolean()
    requiresAccountNumber = graphene.Boolean()
    requiresIdentification = graphene.Boolean()
    supportsOnRamp = graphene.Boolean()
    supportsOffRamp = graphene.Boolean()
    fieldSchema = graphene.JSONString()

    def resolve_countryCode(self, info):
        return self.country_code

    def resolve_displayName(self, info):
        return self.display_name

    def resolve_providerType(self, info):
        return self.provider_type

    def resolve_isActive(self, info):
        return self.is_active

    def resolve_displayOrder(self, info):
        return self.display_order

    def resolve_requiresPhone(self, info):
        return self.requires_phone

    def resolve_requiresEmail(self, info):
        return self.requires_email

    def resolve_requiresAccountNumber(self, info):
        return self.requires_account_number

    def resolve_requiresIdentification(self, info):
        return self.requires_identification

    def resolve_supportsOnRamp(self, info):
        return self.supports_on_ramp

    def resolve_supportsOffRamp(self, info):
        return self.supports_off_ramp

    def resolve_fieldSchema(self, info):
        return self.field_schema or {}

class RampPaymentMethodType(graphene.ObjectType):
    payment_method_id = graphene.ID()
    code = graphene.String()
    display_name = graphene.String()
    description = graphene.String()
    provider_type = graphene.String()
    icon = graphene.String()
    requires_phone = graphene.Boolean()
    requires_email = graphene.Boolean()
    requires_account_number = graphene.Boolean()
    requires_identification = graphene.Boolean()
    supports_on_ramp = graphene.Boolean()
    supports_off_ramp = graphene.Boolean()
    fiat_currency = graphene.String()
    on_ramp_min_amount = graphene.String()
    on_ramp_max_amount = graphene.String()
    off_ramp_min_amount = graphene.String()
    off_ramp_max_amount = graphene.String()

    paymentMethodId = graphene.ID()
    displayName = graphene.String()
    providerType = graphene.String()
    requiresPhone = graphene.Boolean()
    requiresEmail = graphene.Boolean()
    requiresAccountNumber = graphene.Boolean()
    requiresIdentification = graphene.Boolean()
    supportsOnRamp = graphene.Boolean()
    supportsOffRamp = graphene.Boolean()
    onRampMinAmount = graphene.String()
    onRampMaxAmount = graphene.String()
    offRampMinAmount = graphene.String()
    offRampMaxAmount = graphene.String()

    def resolve_paymentMethodId(self, info):
        return self.payment_method_id

    def resolve_displayName(self, info):
        return self.display_name

    def resolve_providerType(self, info):
        return self.provider_type

    def resolve_requiresPhone(self, info):
        return self.requires_phone

    def resolve_requiresEmail(self, info):
        return self.requires_email

    def resolve_requiresAccountNumber(self, info):
        return self.requires_account_number

    def resolve_requiresIdentification(self, info):
        return self.requires_identification

    def resolve_supportsOnRamp(self, info):
        return self.supports_on_ramp

    def resolve_supportsOffRamp(self, info):
        return self.supports_off_ramp

    def resolve_onRampMinAmount(self, info):
        return self.on_ramp_min_amount

    def resolve_onRampMaxAmount(self, info):
        return self.on_ramp_max_amount

    def resolve_offRampMinAmount(self, info):
        return self.off_ramp_min_amount

    def resolve_offRampMaxAmount(self, info):
        return self.off_ramp_max_amount


class RampAvailabilityType(graphene.ObjectType):
    country_code = graphene.String()
    country_name = graphene.String()
    fiat_currency = graphene.String()
    on_ramp_enabled = graphene.Boolean()
    off_ramp_enabled = graphene.Boolean()
    on_ramp_methods = graphene.List(RampPaymentMethodType)
    off_ramp_methods = graphene.List(RampPaymentMethodType)
    token_symbol = graphene.String()
    network_symbol = graphene.String()
    network_display = graphene.String()
    asset_note = graphene.String()
    quote_disclaimer = graphene.String()

    countryCode = graphene.String()
    countryName = graphene.String()
    fiatCurrency = graphene.String()
    onRampEnabled = graphene.Boolean()
    offRampEnabled = graphene.Boolean()
    onRampMethods = graphene.List(RampPaymentMethodType)
    offRampMethods = graphene.List(RampPaymentMethodType)
    tokenSymbol = graphene.String()
    networkSymbol = graphene.String()
    networkDisplay = graphene.String()
    assetNote = graphene.String()
    quoteDisclaimer = graphene.String()

    def resolve_countryCode(self, info):
        return self.country_code

    def resolve_countryName(self, info):
        return self.country_name

    def resolve_fiatCurrency(self, info):
        return self.fiat_currency

    def resolve_onRampEnabled(self, info):
        return self.on_ramp_enabled

    def resolve_offRampEnabled(self, info):
        return self.off_ramp_enabled

    def resolve_onRampMethods(self, info):
        return self.on_ramp_methods

    def resolve_offRampMethods(self, info):
        return self.off_ramp_methods

    def resolve_tokenSymbol(self, info):
        return self.token_symbol

    def resolve_networkSymbol(self, info):
        return self.network_symbol

    def resolve_networkDisplay(self, info):
        return self.network_display

    def resolve_assetNote(self, info):
        return self.asset_note

    def resolve_quoteDisclaimer(self, info):
        return self.quote_disclaimer


class RampQuoteType(graphene.ObjectType):
    direction = graphene.String()
    country_code = graphene.String()
    fiat_currency = graphene.String()
    amount_in = graphene.String()
    amount_out = graphene.String()
    exchange_rate = graphene.String()
    fee_amount = graphene.String()
    fee_currency = graphene.String()
    network_fee_amount = graphene.String()
    network_fee_currency = graphene.String()
    rate_display = graphene.String()
    total_change_display = graphene.String()
    token_symbol = graphene.String()
    network_symbol = graphene.String()
    network_display = graphene.String()
    asset_note = graphene.String()

    countryCode = graphene.String()
    fiatCurrency = graphene.String()
    amountIn = graphene.String()
    amountOut = graphene.String()
    exchangeRate = graphene.String()
    feeAmount = graphene.String()
    feeCurrency = graphene.String()
    networkFeeAmount = graphene.String()
    networkFeeCurrency = graphene.String()
    rateDisplay = graphene.String()
    totalChangeDisplay = graphene.String()
    tokenSymbol = graphene.String()
    networkSymbol = graphene.String()
    networkDisplay = graphene.String()
    assetNote = graphene.String()

    def resolve_countryCode(self, info):
        return self.country_code

    def resolve_fiatCurrency(self, info):
        return self.fiat_currency

    def resolve_amountIn(self, info):
        return self.amount_in

    def resolve_amountOut(self, info):
        return self.amount_out

    def resolve_exchangeRate(self, info):
        return self.exchange_rate

    def resolve_feeAmount(self, info):
        return self.fee_amount

    def resolve_feeCurrency(self, info):
        return self.fee_currency

    def resolve_networkFeeAmount(self, info):
        return self.network_fee_amount

    def resolve_networkFeeCurrency(self, info):
        return self.network_fee_currency

    def resolve_rateDisplay(self, info):
        return self.rate_display

    def resolve_totalChangeDisplay(self, info):
        return self.total_change_display

    def resolve_tokenSymbol(self, info):
        return self.token_symbol

    def resolve_networkSymbol(self, info):
        return self.network_symbol

    def resolve_networkDisplay(self, info):
        return self.network_display

    def resolve_assetNote(self, info):
        return self.asset_note


class RampOrderType(graphene.ObjectType):
    success = graphene.Boolean()
    error = graphene.String()
    order_id = graphene.String()
    direction = graphene.String()
    country_code = graphene.String()
    fiat_currency = graphene.String()
    payment_method_code = graphene.String()
    payment_method_display = graphene.String()
    amount_in = graphene.String()
    amount_out = graphene.String()
    total_change_display = graphene.String()
    rate_display = graphene.String()
    next_step = graphene.String()
    next_action_url = graphene.String()
    payment_details = graphene.JSONString()

    orderId = graphene.String()
    countryCode = graphene.String()
    fiatCurrency = graphene.String()
    paymentMethodCode = graphene.String()
    paymentMethodDisplay = graphene.String()
    amountIn = graphene.String()
    amountOut = graphene.String()
    totalChangeDisplay = graphene.String()
    rateDisplay = graphene.String()
    nextStep = graphene.String()
    nextActionUrl = graphene.String()
    paymentDetails = graphene.JSONString()

    def resolve_orderId(self, info):
        return self.order_id

    def resolve_countryCode(self, info):
        return self.country_code

    def resolve_fiatCurrency(self, info):
        return self.fiat_currency

    def resolve_paymentMethodCode(self, info):
        return self.payment_method_code

    def resolve_paymentMethodDisplay(self, info):
        return self.payment_method_display

    def resolve_amountIn(self, info):
        return self.amount_in

    def resolve_amountOut(self, info):
        return self.amount_out

    def resolve_totalChangeDisplay(self, info):
        return self.total_change_display

    def resolve_rateDisplay(self, info):
        return self.rate_display

    def resolve_nextStep(self, info):
        return self.next_step

    def resolve_nextActionUrl(self, info):
        return self.next_action_url

    def resolve_paymentDetails(self, info):
        return self.payment_details


class RampOrderStatusType(graphene.ObjectType):
    success = graphene.Boolean()
    error = graphene.String()
    order_id = graphene.String()
    status = graphene.String()
    status_details = graphene.String()
    next_action_url = graphene.String()
    payment_details = graphene.JSONString()

    orderId = graphene.String()
    statusDetails = graphene.String()
    nextActionUrl = graphene.String()
    paymentDetails = graphene.JSONString()

    def resolve_orderId(self, info):
        return self.order_id

    def resolve_statusDetails(self, info):
        return self.status_details

    def resolve_nextActionUrl(self, info):
        return self.next_action_url

    def resolve_paymentDetails(self, info):
        return self.payment_details


class PendingRampTransactionType(graphene.ObjectType):
    internal_id = graphene.String()
    provider = graphene.String()
    direction = graphene.String()
    status = graphene.String()
    provider_order_id = graphene.String()
    external_id = graphene.String()
    country_code = graphene.String()
    created_at = graphene.DateTime()

    internalId = graphene.String()
    providerOrderId = graphene.String()
    externalId = graphene.String()
    countryCode = graphene.String()
    createdAt = graphene.DateTime()

    def resolve_internalId(self, info):
        return self.internal_id

    def resolve_providerOrderId(self, info):
        return self.provider_order_id

    def resolve_externalId(self, info):
        return self.external_id

    def resolve_countryCode(self, info):
        return self.country_code

    def resolve_createdAt(self, info):
        return self.created_at


class RampUserAddressType(graphene.ObjectType):
    address_street = graphene.String()
    address_city = graphene.String()
    address_state = graphene.String()
    address_zip_code = graphene.String()
    address_country = graphene.String()
    country_name = graphene.String()
    auth_email = graphene.String()
    is_complete = graphene.Boolean()
    updated_at = graphene.DateTime()

    addressStreet = graphene.String()
    addressCity = graphene.String()
    addressState = graphene.String()
    addressZipCode = graphene.String()
    addressCountry = graphene.String()
    countryName = graphene.String()
    authEmail = graphene.String()
    isComplete = graphene.Boolean()
    updatedAt = graphene.DateTime()

    def resolve_address_country(self, info):
        return _get_user_phone_country_alpha3(getattr(self, 'user', None))

    def resolve_country_name(self, info):
        user = getattr(self, 'user', None)
        return getattr(user, 'phone_country_name', None) or ''

    def resolve_auth_email(self, info):
        return str(getattr(self, 'auth_email', '') or '').strip()

    def resolve_is_complete(self, info):
        return _is_ramp_address_complete(self)

    def resolve_addressStreet(self, info):
        return self.address_street

    def resolve_addressCity(self, info):
        return self.address_city

    def resolve_addressState(self, info):
        return self.address_state

    def resolve_addressZipCode(self, info):
        return self.address_zip_code

    def resolve_addressCountry(self, info):
        return _get_user_phone_country_alpha3(getattr(self, 'user', None))

    def resolve_countryName(self, info):
        user = getattr(self, 'user', None)
        return getattr(user, 'phone_country_name', None) or ''

    def resolve_authEmail(self, info):
        return str(getattr(self, 'auth_email', '') or '').strip()

    def resolve_isComplete(self, info):
        return _is_ramp_address_complete(self)

    def resolve_updatedAt(self, info):
        return self.updated_at


class UpsertRampUserAddress(graphene.Mutation):
    class Arguments:
        address_street = graphene.String(required=True)
        address_city = graphene.String(required=True)
        address_state = graphene.String(required=True)
        address_zip_code = graphene.String(required=True)
        auth_email = graphene.String()

    success = graphene.Boolean()
    error = graphene.String()
    ramp_address = graphene.Field(RampUserAddressType)

    rampAddress = graphene.Field(RampUserAddressType)

    def resolve_rampAddress(self, info):
        return self.ramp_address

    @classmethod
    def mutate(cls, root, info, address_street, address_city, address_state, address_zip_code, auth_email=None):
        user = getattr(info.context, "user", None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return cls(success=False, error='Authentication required', ramp_address=None)

        if not _get_user_phone_country_alpha3(user):
            return cls(
                success=False,
                error='Debes tener un país de teléfono válido para guardar tu dirección de recargas y retiros.',
                ramp_address=None,
            )

        normalized_auth_email = str(auth_email or '').strip().lower()
        if normalized_auth_email:
            try:
                validate_email(normalized_auth_email)
            except ValidationError:
                return cls(
                    success=False,
                    error='Ingresa un email valido para recibir codigos del proveedor.',
                    ramp_address=None,
                )

        values = {
            'address_street': str(address_street or '').strip(),
            'address_city': str(address_city or '').strip(),
            'address_state': str(address_state or '').strip(),
            'address_zip_code': str(address_zip_code or '').strip(),
            'auth_email': normalized_auth_email,
        }
        missing = [label for label, value in (
            ('dirección', values['address_street']),
            ('ciudad', values['address_city']),
            ('provincia/estado', values['address_state']),
            ('código postal', values['address_zip_code']),
        ) if not value]
        if missing:
            return cls(
                success=False,
                error=f'Completa todos los campos de dirección: {", ".join(missing)}',
                ramp_address=None,
            )

        ramp_address, _ = RampUserAddress.objects.update_or_create(
            user=user,
            defaults=values,
        )
        return cls(success=True, error=None, ramp_address=ramp_address)


class CreateRampOrder(graphene.Mutation):
    class Arguments:
        direction = graphene.String(required=True)
        amount = graphene.String(required=True)
        country_code = graphene.String()
        fiat_currency = graphene.String()
        payment_method_code = graphene.String(required=True)
        bank_info_id = graphene.ID()
        auth_email = graphene.String()

    Output = RampOrderType

    def mutate(self, info, direction, amount, payment_method_code, country_code=None, fiat_currency=None, bank_info_id=None, auth_email=None):
        user = getattr(info.context, "user", None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return RampOrderType(success=False, error='Authentication required')

        resolved_country_code = _resolve_ramp_country_code(info, country_code)
        normalized_direction = (direction or '').strip().upper()
        if normalized_direction not in {'ON_RAMP', 'OFF_RAMP'}:
            return RampOrderType(success=False, error='direction must be ON_RAMP or OFF_RAMP')

        try:
            decimal_amount = Decimal(str(amount))
        except (InvalidOperation, TypeError):
            return RampOrderType(success=False, error='Invalid amount')

        if decimal_amount <= 0:
            return RampOrderType(success=False, error='Amount must be greater than zero')

        current_account = _get_ramp_account_for_user(info, user)
        if not current_account:
            return RampOrderType(success=False, error='No active account available for ramp operations')

        wallet_upgrade_blocker = _get_wallet_upgrade_blocker(user=user, account=current_account)
        if wallet_upgrade_blocker:
            return RampOrderType(success=False, error=wallet_upgrade_blocker)

        bank_info = None
        if normalized_direction == 'OFF_RAMP':
            if not bank_info_id:
                return RampOrderType(success=False, error='A saved payout method is required')
            bank_info = _get_saved_bank_info(current_account=current_account, bank_info_id=bank_info_id)
            if not bank_info:
                return RampOrderType(success=False, error='Saved payout method not found for the active account')

        client = KoyweClient()
        if not client.is_configured:
            if getattr(settings, 'KOYWE_USE_MOCK_RAMP', False):
                return CreateMockRampOrder().mutate(
                    info,
                    direction=direction,
                    amount=amount,
                    payment_method_code=payment_method_code,
                    country_code=country_code,
                    fiat_currency=fiat_currency,
                )
            return RampOrderType(success=False, error='Koywe credentials are not configured on the server')

        try:
            koywe_email = _get_koywe_auth_email(
                user=user,
                country_code=resolved_country_code,
                email_override=auth_email,
            )
            _store_koywe_auth_email(user=user, auth_email=koywe_email)
            external_id = f'confio-ramp-{normalized_direction.lower()}-{timezone.now().strftime("%Y%m%d%H%M%S")}'
            result = client.create_ramp_order(
                direction=normalized_direction,
                amount=decimal_amount,
                fiat_symbol=fiat_currency or _get_country_fiat_currency(resolved_country_code),
                payment_method_code=payment_method_code,
                email=koywe_email,
                wallet_address=_get_koywe_destination_address(current_account=current_account),
                country_code=resolved_country_code,
                bank_info=bank_info,
                external_id=external_id,
                contact_profile=_get_koywe_contact_profile(
                    user=user,
                    country_code=resolved_country_code,
                    email_override=koywe_email,
                ),
            )
        except KoyweConfigurationError as exc:
            return RampOrderType(success=False, error=str(exc))
        except KoyweError as exc:
            logger.warning('Koywe ramp order failed: %s', exc)
            return RampOrderType(success=False, error=str(exc))
        except Exception as exc:
            logger.exception('Unexpected Koywe ramp order failure')
            return RampOrderType(success=False, error='Unexpected Koywe error while creating the order')

        actor_business = current_account.business if current_account.account_type == 'business' else None
        actor_type = 'business' if current_account.account_type == 'business' else 'user'
        actor_display_name = current_account.display_name or user.get_full_name() or user.username or ''
        actor_address = current_account.algorand_address or ''
        upsert_koywe_ramp_transaction(
            actor_user=user,
            actor_business=actor_business,
            actor_type=actor_type,
            actor_display_name=actor_display_name,
            actor_address=actor_address,
            direction=normalized_direction,
            country_code=resolved_country_code,
            fiat_currency=fiat_currency or _get_country_fiat_currency(resolved_country_code),
            payment_method_code=payment_method_code,
            payment_method_display=result.payment_method_display,
            order_id=result.order_id,
            external_id=external_id,
            amount_in=result.amount_in,
            amount_out=result.amount_out,
            next_action_url=result.next_action_url,
            auth_email=koywe_email,
            order_payload=result.raw_response,
        )

        return RampOrderType(
            success=True,
            error=None,
            order_id=result.order_id,
            direction=normalized_direction,
            country_code=resolved_country_code,
            fiat_currency=fiat_currency or _get_country_fiat_currency(resolved_country_code),
            payment_method_code=payment_method_code,
            payment_method_display=result.payment_method_display,
            amount_in=result.amount_in,
            amount_out=result.amount_out,
            total_change_display=result.total_change_display,
            rate_display=result.rate_display,
            next_step=result.next_step,
            next_action_url=result.next_action_url,
            payment_details=result.raw_response,
        )


class CreateMockRampOrder(graphene.Mutation):
    class Arguments:
        direction = graphene.String(required=True)
        amount = graphene.String(required=True)
        country_code = graphene.String()
        fiat_currency = graphene.String()
        payment_method_code = graphene.String(required=True)

    Output = RampOrderType

    def mutate(self, info, direction, amount, payment_method_code, country_code=None, fiat_currency=None):
        user = getattr(info.context, "user", None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return RampOrderType(success=False, error='Authentication required')

        resolved_country_code = _resolve_ramp_country_code(info, country_code)
        normalized_direction = (direction or "").strip().upper()
        if normalized_direction not in {"ON_RAMP", "OFF_RAMP"}:
            return RampOrderType(success=False, error="direction must be ON_RAMP or OFF_RAMP")

        try:
            decimal_amount = Decimal(str(amount))
        except (InvalidOperation, TypeError):
            return RampOrderType(success=False, error="Invalid amount")

        if decimal_amount <= 0:
            return RampOrderType(success=False, error="Amount must be greater than zero")

        current_account = _get_ramp_account_for_user(info, user)
        if not current_account:
            return RampOrderType(success=False, error='No active account available for ramp operations')

        wallet_upgrade_blocker = _get_wallet_upgrade_blocker(user=user, account=current_account)
        if wallet_upgrade_blocker:
            return RampOrderType(success=False, error=wallet_upgrade_blocker)

        config = get_country_ramp_config(resolved_country_code)
        if not config:
            return RampOrderType(success=False, error="Unsupported country for ramp")

        method = next((item for item in config["methods"] if item["code"] == payment_method_code), None)
        if not method:
            return RampOrderType(success=False, error="Unsupported payment method for selected country")

        if normalized_direction == "ON_RAMP" and not method["supports_on_ramp"]:
            return RampOrderType(success=False, error="Payment method does not support on-ramp")
        if normalized_direction == "OFF_RAMP" and not method["supports_off_ramp"]:
            return RampOrderType(success=False, error="Payment method does not support off-ramp")

        quote = quote_ramp(
            direction=normalized_direction,
            amount=decimal_amount,
            country_code=resolved_country_code,
            fiat_currency=fiat_currency,
        )
        order_id = f"mock-{normalized_direction.lower()}-{resolved_country_code.lower()}-{timezone.now().strftime('%Y%m%d%H%M%S%f')}"
        next_step = "SHOW_PAYMENT_INSTRUCTIONS" if normalized_direction == "ON_RAMP" else "WAIT_FOR_USDC_TRANSFER"

        return RampOrderType(
            success=True,
            error=None,
            order_id=order_id,
            direction=normalized_direction,
            country_code=resolved_country_code,
            fiat_currency=quote["fiat_currency"],
            payment_method_code=method["code"],
            payment_method_display=method["display_name"],
            amount_in=str(quote["amount_in"]),
            amount_out=str(quote["amount_out"]),
            total_change_display=quote["total_change_display"],
            rate_display=quote["rate_display"],
            next_step=next_step,
            next_action_url=None,
            payment_details=None,
        )


class Query(graphene.ObjectType):
    koywe_bank_info = graphene.List(
        KoyweBankInfoType,
        country_code=graphene.String(required=True),
    )
    ramp_payment_methods = graphene.List(
        RampPaymentMethodCatalogType,
        country_code=graphene.String(),
        direction=graphene.String(),
        include_inactive=graphene.Boolean(),
    )
    ramp_availability = graphene.Field(
        RampAvailabilityType,
        country_code=graphene.String(),
    )
    ramp_quote = graphene.Field(
        RampQuoteType,
        direction=graphene.String(required=True),
        amount=graphene.String(required=True),
        country_code=graphene.String(),
        fiat_currency=graphene.String(),
        payment_method_code=graphene.String(),
    )
    ramp_order_status = graphene.Field(
        RampOrderStatusType,
        order_id=graphene.String(required=True),
        country_code=graphene.String(),
    )
    pending_ramp_transaction = graphene.Field(
        PendingRampTransactionType,
        provider=graphene.String(required=True),
        direction=graphene.String(),
    )
    my_ramp_address = graphene.Field(RampUserAddressType)

    def resolve_koywe_bank_info(self, info, country_code):
        alpha3 = country_code.upper()
        qs = KoyweBankInfo.objects.filter(country_code=alpha3, is_active=True)
        if not qs.exists():
            # Trigger a sync on cache miss
            try:
                client = KoyweClient()
                if client.is_configured:
                    banks = client.get_bank_info(country_code=alpha3)
                    for bank in banks:
                        bank_code = bank.get('bankCode') or ''
                        name = bank.get('name') or ''
                        if not bank_code or not name:
                            continue
                        KoyweBankInfo.objects.update_or_create(
                            bank_code=bank_code,
                            country_code=alpha3,
                            defaults={
                                'name': name,
                                'institution_name': bank.get('institutionName') or '',
                                'is_active': True,
                            },
                        )
                    qs = KoyweBankInfo.objects.filter(country_code=alpha3, is_active=True)
            except KoyweError as exc:
                logger.warning('Koywe bank info on-demand sync failed for %s: %s', alpha3, exc)
        return list(qs)

    def resolve_ramp_availability(self, info, country_code=None):
        resolved_country_code = _resolve_ramp_country_code(info, country_code)
        config = get_country_ramp_config(resolved_country_code)
        if not config:
            return None

        koywe_client = KoyweClient()
        dynamic_limits = {}
        try:
            dynamic_limits = koywe_client.get_public_ramp_limits(
                fiat_symbol=config["fiat_currency"],
            )
        except KoyweError as exc:
            logger.warning(
                "Falling back to static Koywe limits for %s: %s",
                resolved_country_code,
                exc,
            )

        sync_country_payment_methods(resolved_country_code)
        method_map = {
            method.code: method
            for method in RampPaymentMethod.objects.filter(
                country_code=resolved_country_code.upper(),
                is_active=True,
            )
        }
        country_name = _get_country_name(resolved_country_code)

        on_ramp_methods = []
        off_ramp_methods = []
        for method in config["methods"]:
            payment_method = method_map.get(method["code"])
            payload = _build_ramp_method_payload(
                country_code=resolved_country_code,
                fiat_currency=config["fiat_currency"],
                payment_method=payment_method,
                definition=method,
                limits=dynamic_limits,
            )
            if method["supports_on_ramp"]:
                on_ramp_methods.append(payload)
            if method["supports_off_ramp"]:
                off_ramp_methods.append(payload)

        return RampAvailabilityType(
            country_code=resolved_country_code,
            country_name=country_name,
            fiat_currency=config["fiat_currency"],
            on_ramp_enabled=bool(on_ramp_methods),
            off_ramp_enabled=bool(off_ramp_methods),
            on_ramp_methods=on_ramp_methods,
            off_ramp_methods=off_ramp_methods,
            token_symbol=RAMP_USDC_ALGORAND_SYMBOL,
            network_symbol=RAMP_NETWORK_SYMBOL,
            network_display=RAMP_NETWORK_DISPLAY,
            asset_note=RAMP_USDC_ALGORAND_NOTE,
            quote_disclaimer=(
                "Cotización estimada con datos de Koywe. Se enruta por Polygon hasta conectar Algorand."
            ),
        )

    def resolve_ramp_payment_methods(self, info, country_code=None, direction=None, include_inactive=False):
        resolved_country_code = _resolve_ramp_country_code(info, country_code)
        sync_country_payment_methods(resolved_country_code)
        queryset = RampPaymentMethod.objects.filter(country_code=resolved_country_code.upper())
        if not include_inactive:
            queryset = queryset.filter(is_active=True)
        normalized_direction = (direction or '').strip().upper()
        if normalized_direction == 'ON_RAMP':
            queryset = queryset.filter(supports_on_ramp=True)
        elif normalized_direction == 'OFF_RAMP':
            queryset = queryset.filter(supports_off_ramp=True)
        return queryset.select_related('country', 'bank', 'legacy_payment_method')

    def resolve_ramp_quote(self, info, direction, amount, country_code=None, fiat_currency=None, payment_method_code=None):
        resolved_country_code = _resolve_ramp_country_code(info, country_code)
        normalized_direction = (direction or "").strip().upper()
        if normalized_direction not in {"ON_RAMP", "OFF_RAMP"}:
            raise ValidationError("direction must be ON_RAMP or OFF_RAMP")

        try:
            decimal_amount = Decimal(str(amount))
        except (InvalidOperation, TypeError):
            raise ValidationError("Invalid amount")

        if decimal_amount <= 0:
            raise ValidationError("Amount must be greater than zero")

        if normalized_direction == "ON_RAMP" and not (payment_method_code or "").strip():
            raise ValidationError("paymentMethodCode is required for on-ramp quotes")

        client = KoyweClient()
        if not client.is_configured:
            raise ValidationError("Koywe credentials are not configured on the server")

        try:
            user = getattr(info.context, "user", None)
            koywe_email = _get_koywe_auth_email(
                user=user,
                country_code=resolved_country_code,
            ) if user and getattr(user, "is_authenticated", False) else None
            quote = client.get_ramp_quote(
                direction=normalized_direction,
                amount=decimal_amount,
                fiat_symbol=fiat_currency or _get_country_fiat_currency(resolved_country_code),
                payment_method_code=payment_method_code,
                email=koywe_email,
            )
        except KoyweError as exc:
            logger.warning(
                "Koywe ramp quote failed for %s %s: %s",
                normalized_direction,
                resolved_country_code,
                exc,
            )
            raise ValidationError(str(exc))

        return RampQuoteType(
            direction=quote["direction"],
            country_code=quote.get("country_code") or resolved_country_code,
            fiat_currency=quote.get("fiat_currency") or (fiat_currency or _get_country_fiat_currency(resolved_country_code)),
            amount_in=str(quote["amount_in"]),
            amount_out=str(quote["amount_out"]),
            exchange_rate=str(quote["exchange_rate"]),
            fee_amount=str(quote["fee_amount"]),
            fee_currency=quote["fee_currency"],
            network_fee_amount=str(quote["network_fee_amount"]),
            network_fee_currency=quote["network_fee_currency"],
            rate_display=quote["rate_display"],
            total_change_display=quote["total_change_display"],
            token_symbol=quote["token_symbol"],
            network_symbol=quote["network_symbol"],
            network_display=quote["network_display"],
            asset_note=quote["asset_note"],
        )

    def resolve_ramp_order_status(self, info, order_id, country_code=None):
        user = getattr(info.context, "user", None)
        if not (user and getattr(user, "is_authenticated", False)):
            return RampOrderStatusType(success=False, error="Authentication required")

        resolved_country_code = _resolve_ramp_country_code(info, country_code)
        client = KoyweClient()
        if not client.is_configured:
            return RampOrderStatusType(success=False, error="Koywe credentials are not configured on the server")

        ramp_tx = RampTransaction.objects.filter(
            provider='koywe',
            provider_order_id=order_id,
            actor_user=user,
        ).first()

        try:
            koywe_email = str((ramp_tx.metadata or {}).get('auth_email') or '').strip() if ramp_tx else ''
            if not koywe_email:
                koywe_email = _get_koywe_auth_email(
                    user=user,
                    country_code=resolved_country_code,
                )
            result = client.get_ramp_order_status(
                order_id=order_id,
                email=koywe_email,
            )
            if ramp_tx:
                sync_koywe_ramp_transaction_from_order(
                    ramp_tx=ramp_tx,
                    order_payload=result.raw_response,
                    next_action_url=result.next_action_url,
                )
        except KoyweConfigurationError as exc:
            return RampOrderStatusType(success=False, error=str(exc))
        except KoyweError as exc:
            logger.warning("Koywe ramp order status lookup failed: %s", exc)
            return RampOrderStatusType(success=False, error=str(exc))
        except Exception:
            logger.exception("Unexpected Koywe ramp order status failure")
            return RampOrderStatusType(success=False, error="Unexpected Koywe error while reading the order")

        return RampOrderStatusType(
            success=True,
            error=None,
            order_id=result.order_id,
            status=result.status,
            status_details=result.status_details,
            next_action_url=result.next_action_url,
            payment_details=result.raw_response,
        )

    def resolve_pending_ramp_transaction(self, info, provider, direction=None):
        user = getattr(info.context, "user", None)
        if not (user and getattr(user, "is_authenticated", False)):
            return None

        current_account = _get_ramp_account_for_user(info, user)
        if not current_account:
            return None

        queryset = RampTransaction.objects.filter(
            provider=(provider or "").strip().lower(),
            status__in=["PENDING", "PROCESSING", "AML_REVIEW"],
        )
        if direction:
            queryset = queryset.filter(direction=(direction or "").strip().lower())

        if current_account.account_type == 'business' and current_account.business_id:
            queryset = queryset.filter(actor_business_id=current_account.business_id)
        else:
            queryset = queryset.filter(actor_user=user)

        if getattr(current_account, 'algorand_address', None):
            queryset = queryset.filter(actor_address=current_account.algorand_address)

        ramp_tx = queryset.order_by('-created_at').first()
        if not ramp_tx:
            return None

        return PendingRampTransactionType(
            internal_id=str(ramp_tx.internal_id),
            provider=ramp_tx.provider,
            direction=ramp_tx.direction,
            status=ramp_tx.status,
            provider_order_id=ramp_tx.provider_order_id,
            external_id=ramp_tx.external_id,
            country_code=ramp_tx.country_code,
            created_at=ramp_tx.created_at,
        )

    def resolve_my_ramp_address(self, info):
        user = getattr(info.context, "user", None)
        if not (user and getattr(user, "is_authenticated", False)):
            return None
        return _build_effective_ramp_address_snapshot(user)


def _resolve_ramp_country_code(info, country_code=None):
    if country_code:
        return country_code.upper()

    user = getattr(info.context, "user", None)
    phone_country = getattr(user, "phone_country", None) if user and getattr(user, "is_authenticated", False) else None
    if phone_country and phone_country.upper() in COUNTRY_METHODS:
        return phone_country.upper()
    return "AR"


def _get_country_name(country_code: str) -> str:
    country = Country.objects.filter(code=country_code).first()
    if country:
        return country.name

    fallback_names = {
        "AR": "Argentina",
        "BO": "Bolivia",
        "BR": "Brasil",
        "CL": "Chile",
        "CO": "Colombia",
        "MX": "Mexico",
        "PE": "Peru",
        "US": "United States",
    }
    return fallback_names.get(country_code, country_code)


def _build_ramp_method_payload(*, country_code, fiat_currency, payment_method, definition, limits=None):
    country = Country.objects.filter(code=country_code).first()
    config = get_country_ramp_config(country_code) or {}
    limits = limits or {}
    requires_identification = bool(country.requires_identification) if country else False
    return RampPaymentMethodType(
        payment_method_id=str(payment_method.id) if payment_method else None,
        code=definition["code"],
        display_name=definition["display_name"],
        description=definition["description"],
        provider_type=definition["provider_type"],
        icon=definition["icon"],
        requires_phone=definition["requires_phone"],
        requires_email=definition["requires_email"],
        requires_account_number=definition["requires_account_number"],
        requires_identification=requires_identification,
        supports_on_ramp=definition["supports_on_ramp"],
        supports_off_ramp=definition["supports_off_ramp"],
        fiat_currency=fiat_currency,
        on_ramp_min_amount=str(limits.get("on_ramp_min_amount") or config.get("on_ramp_min_amount") or ""),
        on_ramp_max_amount=str(limits.get("on_ramp_max_amount") or config.get("on_ramp_max_amount") or ""),
        off_ramp_min_amount=str(limits.get("off_ramp_min_amount") or config.get("off_ramp_min_amount") or ""),
        off_ramp_max_amount=str(limits.get("off_ramp_max_amount") or config.get("off_ramp_max_amount") or ""),
    )

def _get_country_fiat_currency(country_code: str) -> str:
    config = get_country_ramp_config(country_code)
    if config and config.get('fiat_currency'):
        return config['fiat_currency']
    country = Country.objects.filter(code=country_code).first()
    return country.currency_code if country else 'USD'


def _get_ramp_account_for_user(info, user):
    from users.jwt_context import get_jwt_business_context_with_validation

    jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
    if jwt_context:
        account_type = jwt_context['account_type']
        account_index = jwt_context['account_index']
        business_id = jwt_context.get('business_id')
        if account_type == 'business' and business_id:
            return Account.objects.filter(
                business_id=business_id,
                account_type='business',
                account_index=account_index,
                deleted_at__isnull=True,
            ).first()
        return Account.objects.filter(
            user=user,
            account_type=account_type,
            account_index=account_index,
            deleted_at__isnull=True,
        ).first()

    return Account.objects.filter(
        user=user,
        account_type='personal',
        account_index=0,
        deleted_at__isnull=True,
    ).first()


def _get_saved_bank_info(*, current_account, bank_info_id):
    return BankInfo.objects.select_related('payment_method', 'bank', 'country').filter(
        id=bank_info_id,
        account=current_account,
        deleted_at__isnull=True,
    ).first()


def _get_koywe_destination_address(*, current_account) -> str | None:
    crypto_symbol = str(getattr(settings, 'KOYWE_CRYPTO_SYMBOL', '') or '').strip().lower()
    if 'algorand' in crypto_symbol or crypto_symbol == 'usdc-a':
        return getattr(current_account, 'algorand_address', None)

    # Temporary sandbox bridge: while Koywe is routed through Polygon, use a valid EVM test address
    # instead of the user's Algorand address. Replace this once Koywe supports Algorand directly.
    return getattr(settings, 'KOYWE_TEST_DESTINATION_ADDRESS', None)


def _get_koywe_test_account_override(*, user, country_code: str) -> dict[str, str] | None:
    if not user:
        return None
    username = str(getattr(user, 'username', '') or '').strip().lower()
    if username not in _KOYWE_TEST_OVERRIDE_USERNAMES:
        return None
    return _KOYWE_TEST_ACCOUNT_OVERRIDES.get((country_code or '').strip().upper())


def _get_koywe_auth_email(*, user, country_code: str, email_override: str | None = None) -> str:
    override = _get_koywe_test_account_override(user=user, country_code=country_code)
    normalized_override = str(email_override or '').strip()
    if normalized_override:
        try:
            validate_email(normalized_override)
        except ValidationError as exc:
            raise KoyweError('Ingresa un email valido para continuar con este pago') from exc
    stored_ramp_email = ''
    if user:
        stored_ramp_email = str(
            getattr(getattr(user, 'ramp_user_address', None), 'auth_email', '') or ''
        ).strip()
    email = str(
        normalized_override
        or stored_ramp_email
        or (override or {}).get('email')
        or getattr(user, 'email', None)
        or ''
    ).strip()
    if not email:
        raise KoyweError('Tu cuenta debe tener un email para usar recargas y retiros')
    return email


def _store_koywe_auth_email(*, user, auth_email: str | None) -> None:
    normalized_email = str(auth_email or '').strip().lower()
    if not user or not normalized_email:
        return
    try:
        validate_email(normalized_email)
    except ValidationError:
        return

    ramp_address, _ = RampUserAddress.objects.get_or_create(
        user=user,
        defaults={
            'address_street': '',
            'address_city': '',
            'address_state': '',
            'address_zip_code': '',
            'auth_email': normalized_email,
        },
    )
    if ramp_address.auth_email != normalized_email:
        ramp_address.auth_email = normalized_email
        ramp_address.save(update_fields=['auth_email', 'updated_at'])


def _get_user_phone_country_alpha3(user) -> str:
    iso2 = str(getattr(user, 'phone_country', '') or '').strip().upper()
    return ISO2_TO_ISO3.get(iso2, '')


def _get_latest_personal_verification(user):
    return (
        IdentityVerification.objects
        .filter(user=user, status='verified', risk_factors__account_type__isnull=True)
        .order_by('-verified_at', '-updated_at', '-created_at')
        .first()
    )


def _build_effective_ramp_address_snapshot(user):
    verification = _get_latest_personal_verification(user)
    ramp_address = RampUserAddress.objects.filter(user=user).first()
    address_country = _get_user_phone_country_alpha3(user) or (
        (verification.verified_country or '').strip() if verification else ''
    )
    address_street = (
        (ramp_address.address_street or '').strip()
        if ramp_address and ramp_address.address_street
        else (verification.verified_address or '').strip() if verification and verification.verified_address else ''
    )
    address_city = (
        (ramp_address.address_city or '').strip()
        if ramp_address and ramp_address.address_city
        else (verification.verified_city or '').strip() if verification and verification.verified_city else ''
    )
    address_state = (
        (ramp_address.address_state or '').strip()
        if ramp_address and ramp_address.address_state
        else (verification.verified_state or '').strip() if verification and verification.verified_state else ''
    )
    address_zip_code = (
        (ramp_address.address_zip_code or '').strip()
        if ramp_address and ramp_address.address_zip_code
        else (verification.verified_postal_code or '').strip() if verification and verification.verified_postal_code else ''
    )
    return SimpleNamespace(
        user=user,
        address_street=address_street,
        address_city=address_city,
        address_state=address_state,
        address_zip_code=address_zip_code,
        auth_email=(ramp_address.auth_email or '').strip() if ramp_address and getattr(ramp_address, 'auth_email', None) else '',
        address_country=address_country,
        updated_at=getattr(ramp_address, 'updated_at', None) or getattr(verification, 'updated_at', None),
    )


def _is_ramp_address_complete(value) -> bool:
    return bool(
        getattr(value, 'address_street', None)
        and getattr(value, 'address_city', None)
        and getattr(value, 'address_state', None)
        and getattr(value, 'address_zip_code', None)
        and _get_user_phone_country_alpha3(getattr(value, 'user', None))
    )


def _get_koywe_contact_profile(*, user, country_code: str, email_override: str | None = None) -> dict[str, str]:
    verification = _get_latest_personal_verification(user)
    override = _get_koywe_test_account_override(user=user, country_code=country_code)

    first_name = str(
        (override or {}).get('firstName')
        or getattr(verification, 'verified_first_name', None)
        or getattr(user, 'first_name', None)
        or ''
    ).strip()
    last_name = str(
        (override or {}).get('lastName')
        or getattr(verification, 'verified_last_name', None)
        or getattr(user, 'last_name', None)
        or ''
    ).strip()
    email = str(email_override or (override or {}).get('email') or getattr(user, 'email', None) or '').strip()
    phone_country_code = getattr(user, 'phone_country_code', None) or ''
    phone_number = (getattr(user, 'phone_number', None) or '').strip()
    phone = f'{phone_country_code}{phone_number}'.replace(' ', '') if phone_number else ''

    profile = {
        'firstName': first_name,
        'lastName': last_name,
        'email': email,
        'phone': phone,
    }
    if override:
        profile['documentNumber'] = str(override.get('documentNumber') or '').strip()
        profile['documentType'] = str(override.get('documentType') or '').strip()
    elif verification:
        profile['documentNumber'] = (verification.document_number or '').strip()
        profile['documentType'] = (verification.document_type or '').strip()
    if verification:
        profile['dob'] = verification.verified_date_of_birth.isoformat() if verification.verified_date_of_birth else ''
    effective_address = _build_effective_ramp_address_snapshot(user)
    if effective_address.address_street:
        profile['address'] = effective_address.address_street
        profile['addressStreet'] = effective_address.address_street
    if effective_address.address_city:
        profile['addressCity'] = effective_address.address_city
    if effective_address.address_state:
        profile['addressState'] = effective_address.address_state
    if effective_address.address_zip_code:
        profile['addressZipCode'] = effective_address.address_zip_code
    if effective_address.address_country:
        profile['addressCountry'] = effective_address.address_country
    return {key: value for key, value in profile.items() if value}


class Mutation(graphene.ObjectType):
    create_ramp_order = CreateRampOrder.Field()
    create_mock_ramp_order = CreateMockRampOrder.Field()
    upsert_ramp_user_address = UpsertRampUserAddress.Field()
