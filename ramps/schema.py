import logging
import re
import uuid
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from types import SimpleNamespace

import graphene
from graphene_django import DjangoObjectType
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from security.didit import ISO2_TO_ISO3
from security.models import IdentityVerification, normalize_document_number
from users.models import Account, BankInfo, Country
from ramps.models import KoyweBankInfo, RampPaymentMethod, RampTransaction, RampUserAddress
from ramps.koywe_sync import build_koywe_instruction_snapshot, sync_koywe_ramp_transaction_from_order, upsert_koywe_ramp_transaction
from ramps.mexico_economic_activities import MEXICO_ECONOMIC_ACTIVITIES, normalize_mexico_economic_activity

from ramps.koywe_client import (
    KoyweClient,
    KoyweConfigurationError,
    KoyweError,
    KoyweMaximumAmountError,
    KoyweMinimumAmountError,
    KoyweOrderCreationAmbiguousError,
)
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


def _format_minimum_amount_error(exc: 'KoyweMinimumAmountError', direction: str) -> str:
    action = 'recargar' if (direction or '').upper() == 'ON_RAMP' else 'retirar'
    minimum = (exc.minimum or '').strip()
    currency = (exc.currency or '').strip().upper()
    if minimum and currency:
        return (
            f'El monto es menor al mínimo permitido para {action}. '
            f'Ingresa al menos {minimum} {currency} para continuar.'
        )
    if minimum:
        return (
            f'El monto es menor al mínimo permitido para {action}. '
            f'Ingresa al menos {minimum} para continuar.'
        )
    return (
        f'El monto es menor al mínimo permitido para {action}. '
        f'Aumenta el monto e inténtalo nuevamente.'
    )


def _format_maximum_amount_error(exc: 'KoyweMaximumAmountError', direction: str) -> str:
    action = 'recargar' if (direction or '').upper() == 'ON_RAMP' else 'retirar'
    maximum = (exc.maximum or '').strip()
    currency = (exc.currency or '').strip().upper()
    if maximum and currency:
        return (
            f'El monto supera el máximo permitido para {action}. '
            f'Ingresa como máximo {maximum} {currency} para continuar.'
        )
    if maximum:
        return (
            f'El monto supera el máximo permitido para {action}. '
            f'Ingresa como máximo {maximum} para continuar.'
        )
    return (
        f'El monto supera el máximo permitido para {action}. '
        f'Reduce el monto e inténtalo nuevamente.'
    )


def _format_decimal_plain(value: Decimal) -> str:
    formatted = format(value, 'f')
    if '.' in formatted:
        formatted = formatted.rstrip('0').rstrip('.')
    return formatted or '0'


def _validate_koywe_on_ramp_quote_limits(*, client: KoyweClient, amount: Decimal, fiat_symbol: str) -> None:
    limits = client.get_public_ramp_limits(fiat_symbol=fiat_symbol)
    minimum = limits.get('on_ramp_min_amount')
    maximum = limits.get('on_ramp_max_amount')
    if minimum is not None and amount < minimum:
        raise KoyweMinimumAmountError(
            f'Currency amount is less than the minimum available for {fiat_symbol}. {amount} < {minimum}',
            currency=fiat_symbol,
            actual=_format_decimal_plain(amount),
            minimum=_format_decimal_plain(minimum),
        )
    if maximum is not None and amount > maximum:
        raise KoyweMaximumAmountError(
            f'Currency amount exceeds the maximum available for {fiat_symbol}. {amount} > {maximum}',
            currency=fiat_symbol,
            actual=_format_decimal_plain(amount),
            maximum=_format_decimal_plain(maximum),
        )


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
    instruction_snapshot = graphene.JSONString()

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
    instructionSnapshot = graphene.JSONString()

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

    def resolve_instructionSnapshot(self, info):
        return self.instruction_snapshot


class RampOrderStatusType(graphene.ObjectType):
    success = graphene.Boolean()
    error = graphene.String()
    order_id = graphene.String()
    status = graphene.String()
    status_details = graphene.String()
    next_action_url = graphene.String()
    payment_details = graphene.JSONString()
    instruction_snapshot = graphene.JSONString()
    instruction_snapshot_created = graphene.JSONString()
    instruction_snapshot_latest = graphene.JSONString()
    provider_payload_created = graphene.JSONString()
    provider_payload_latest = graphene.JSONString()

    orderId = graphene.String()
    statusDetails = graphene.String()
    nextActionUrl = graphene.String()
    paymentDetails = graphene.JSONString()
    instructionSnapshot = graphene.JSONString()
    instructionSnapshotCreated = graphene.JSONString()
    instructionSnapshotLatest = graphene.JSONString()
    providerPayloadCreated = graphene.JSONString()
    providerPayloadLatest = graphene.JSONString()

    def resolve_orderId(self, info):
        return self.order_id

    def resolve_statusDetails(self, info):
        return self.status_details

    def resolve_nextActionUrl(self, info):
        return self.next_action_url

    def resolve_paymentDetails(self, info):
        return self.payment_details

    def resolve_instructionSnapshot(self, info):
        return self.instruction_snapshot

    def resolve_instructionSnapshotCreated(self, info):
        return self.instruction_snapshot_created

    def resolve_instructionSnapshotLatest(self, info):
        return self.instruction_snapshot_latest

    def resolve_providerPayloadCreated(self, info):
        return self.provider_payload_created

    def resolve_providerPayloadLatest(self, info):
        return self.provider_payload_latest


class PendingRampTransactionType(graphene.ObjectType):
    internal_id = graphene.String()
    provider = graphene.String()
    direction = graphene.String()
    status = graphene.String()
    provider_order_id = graphene.String()
    external_id = graphene.String()
    country_code = graphene.String()
    created_at = graphene.DateTime()
    instruction_snapshot_created = graphene.JSONString()
    instruction_snapshot_latest = graphene.JSONString()
    provider_payload_created = graphene.JSONString()
    provider_payload_latest = graphene.JSONString()

    internalId = graphene.String()
    providerOrderId = graphene.String()
    externalId = graphene.String()
    countryCode = graphene.String()
    createdAt = graphene.DateTime()
    instructionSnapshotCreated = graphene.JSONString()
    instructionSnapshotLatest = graphene.JSONString()
    providerPayloadCreated = graphene.JSONString()
    providerPayloadLatest = graphene.JSONString()

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

    def resolve_instructionSnapshotCreated(self, info):
        return self.instruction_snapshot_created

    def resolve_instructionSnapshotLatest(self, info):
        return self.instruction_snapshot_latest

    def resolve_providerPayloadCreated(self, info):
        return self.provider_payload_created

    def resolve_providerPayloadLatest(self, info):
        return self.provider_payload_latest


class RampUserAddressType(graphene.ObjectType):
    address_street = graphene.String()
    address_neighborhood = graphene.String()
    address_city = graphene.String()
    address_state = graphene.String()
    address_zip_code = graphene.String()
    address_country = graphene.String()
    country_name = graphene.String()
    economic_activity = graphene.String()
    auth_email = graphene.String()
    is_complete = graphene.Boolean()
    updated_at = graphene.DateTime()

    addressStreet = graphene.String()
    addressNeighborhood = graphene.String()
    addressCity = graphene.String()
    addressState = graphene.String()
    addressZipCode = graphene.String()
    addressCountry = graphene.String()
    countryName = graphene.String()
    economicActivity = graphene.String()
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

    def resolve_addressNeighborhood(self, info):
        return str(getattr(self, 'address_neighborhood', '') or '').strip()

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

    def resolve_economicActivity(self, info):
        return str(getattr(self, 'economic_activity', '') or '').strip()

    def resolve_authEmail(self, info):
        return str(getattr(self, 'auth_email', '') or '').strip()

    def resolve_isComplete(self, info):
        return _is_ramp_address_complete(self)

    def resolve_updatedAt(self, info):
        return self.updated_at


class EconomicActivityOptionType(graphene.ObjectType):
    label = graphene.String()
    value = graphene.String()


class RampAddressRequirementType(graphene.ObjectType):
    requires_address_neighborhood = graphene.Boolean()
    address_neighborhood_label = graphene.String()
    address_neighborhood_placeholder = graphene.String()

    requiresAddressNeighborhood = graphene.Boolean()
    addressNeighborhoodLabel = graphene.String()
    addressNeighborhoodPlaceholder = graphene.String()

    def resolve_requiresAddressNeighborhood(self, info):
        return self.requires_address_neighborhood

    def resolve_addressNeighborhoodLabel(self, info):
        return self.address_neighborhood_label

    def resolve_addressNeighborhoodPlaceholder(self, info):
        return self.address_neighborhood_placeholder


class UpsertRampUserAddress(graphene.Mutation):
    class Arguments:
        address_street = graphene.String(required=True)
        address_neighborhood = graphene.String()
        address_city = graphene.String(required=True)
        address_state = graphene.String(required=True)
        address_zip_code = graphene.String(required=True)
        economic_activity = graphene.String()
        auth_email = graphene.String()

    success = graphene.Boolean()
    error = graphene.String()
    ramp_address = graphene.Field(RampUserAddressType)

    rampAddress = graphene.Field(RampUserAddressType)

    def resolve_rampAddress(self, info):
        return self.ramp_address

    @classmethod
    def mutate(
        cls,
        root,
        info,
        address_street,
        address_city,
        address_state,
        address_zip_code,
        address_neighborhood=None,
        economic_activity=None,
        auth_email=None,
    ):
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
            'address_neighborhood': str(address_neighborhood or '').strip(),
            'address_city': str(address_city or '').strip(),
            'address_state': str(address_state or '').strip(),
            'address_zip_code': str(address_zip_code or '').strip(),
            'economic_activity': normalize_mexico_economic_activity(economic_activity),
            'auth_email': normalized_auth_email,
        }
        if values['economic_activity'] and values['economic_activity'] not in MEXICO_ECONOMIC_ACTIVITIES:
            return cls(
                success=False,
                error='Selecciona una actividad económica válida del catálogo.',
                ramp_address=None,
            )
        missing = [label for label, value in (
            ('dirección', values['address_street']),
            ('ciudad', values['address_city']),
            ('provincia/estado', values['address_state']),
            ('código postal', values['address_zip_code']),
            ('actividad económica', values['economic_activity']),
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


def _release_proven_empty_koywe_reservation(reservation, *, account_id: int) -> None:
    """Remove a placeholder only when Koywe definitively created no order."""
    if reservation is None:
        return
    with transaction.atomic():
        Account.objects.select_for_update().filter(
            pk=account_id,
            deleted_at__isnull=True,
        ).first()
        RampTransaction.objects.filter(
            pk=reservation.pk,
            provider='koywe',
            provider_order_id='',
        ).delete()


def _mark_ambiguous_koywe_reservation(reservation) -> None:
    """Keep an unresolved create POST visible and searchable by external id."""
    if reservation is None:
        return
    metadata = dict(reservation.metadata or {})
    metadata.update({
        'wallet_address_reservation_state': 'ambiguous_order_creation',
        'ambiguous_at': timezone.now().isoformat(),
        'reconcile_key': reservation.external_id,
        'reconciliation': (
            'Koywe does not expose an external-id lookup in the current '
            'integration; verify this key with Koywe before release.'
        ),
    })
    # A webhook can recover the provider order while the original create-order
    # request is still waiting to time out. Only mark the stale reservation
    # ambiguous if it is still the untouched pre-order placeholder.
    updated = RampTransaction.objects.filter(
        pk=reservation.pk,
        provider='koywe',
        provider_order_id='',
        status='PENDING',
        metadata__wallet_address_reservation_state='creating_order',
    ).update(
        status_detail='Koywe order creation outcome unresolved',
        metadata=metadata,
        updated_at=timezone.now(),
    )
    if updated:
        logger.error(
            'Koywe create outcome ambiguous; retaining wallet reservation '
            'pk=%s external_id=%s',
            reservation.pk,
            reservation.external_id,
        )
    else:
        logger.info(
            'Koywe ambiguity marker skipped because reservation already changed: '
            'pk=%s external_id=%s',
            reservation.pk,
            reservation.external_id,
        )


class CreateRampOrder(graphene.Mutation):
    class Arguments:
        direction = graphene.String(required=True)
        amount = graphene.String(required=True)
        country_code = graphene.String()
        fiat_currency = graphene.String()
        payment_method_code = graphene.String(required=True)
        bank_info_id = graphene.ID()
        auth_email = graphene.String()
        destination = graphene.String(default_value='cusd', description="'cusd' (day-to-day) or 'cusd_plus' (savings: USDT-BSC to the account's BSC address)")

    Output = RampOrderType

    def mutate(self, info, direction, amount, payment_method_code, country_code=None, fiat_currency=None, bank_info_id=None, auth_email=None, destination='cusd'):
        user = getattr(info.context, "user", None)
        if not (user and getattr(user, 'is_authenticated', False)):
            return RampOrderType(success=False, error='Authentication required')

        employee_denial = _employee_ramp_denial(info)
        if employee_denial:
            return RampOrderType(success=False, error=employee_denial)

        resolved_country_code = _resolve_ramp_country_code(info, country_code)
        normalized_direction = (direction or '').strip().upper()
        if normalized_direction not in {'ON_RAMP', 'OFF_RAMP'}:
            return RampOrderType(success=False, error='direction must be ON_RAMP or OFF_RAMP')

        address_reservation = None
        try:
            # Canonicalize to the 6dp grain the on-chain transfer actually
            # moves, truncating. The client already sends a canonical value;
            # doing it here too means the quote, the order and the transfer
            # cannot disagree even for an older build (re-audit [P1] #4).
            decimal_amount = Decimal(str(amount)).quantize(
                Decimal('0.000001'), rounding=ROUND_DOWN)
        except (InvalidOperation, TypeError):
            return RampOrderType(success=False, error='Invalid amount')

        if decimal_amount <= 0:
            return RampOrderType(success=False, error='Amount must be greater than zero')

        current_account = _get_ramp_account_for_user(info, user)
        if not current_account:
            return RampOrderType(success=False, error='No active account available for ramp operations')

        # cUSD+ savings rail (Koywe 'USDT BSC' delivered to the account's own
        # BSC address). The address is client-derived and registered at
        # sign-in (UpdateAccountBscAddress) — the server cannot derive it.
        if destination not in ('cusd', 'cusd_plus'):
            return RampOrderType(success=False, error='destination must be cusd or cusd_plus')
        savings_rail = destination == 'cusd_plus'
        # Geo-eligibility moved to the MINT (cusd_plus mint gate, 2026-07-30):
        # everyone may receive USDT-BSC — ineligible users simply keep it raw
        # ("Confío Dollar"), the vault mint is refused server-side. Exits
        # (OFF_RAMP) were never gated and still aren't.
        if savings_rail and not getattr(current_account, 'bsc_address', None):
            return RampOrderType(
                success=False,
                error='Tu cuenta de ahorro aún no está activada en este dispositivo. Actualiza la app e inicia sesión de nuevo.',
            )

        wallet_upgrade_blocker = _get_wallet_upgrade_blocker(user=user, account=current_account)
        if wallet_upgrade_blocker:
            return RampOrderType(success=False, error=wallet_upgrade_blocker)

        if normalized_direction == 'OFF_RAMP' and resolved_country_code == 'BO':
            return RampOrderType(success=False, error='Retiro en BOB no está disponible por ahora. En Bolivia solo está habilitada la recarga.')

        bank_info = None
        if normalized_direction == 'OFF_RAMP':
            if not bank_info_id:
                return RampOrderType(success=False, error='A saved payout method is required')
            bank_info = _get_saved_bank_info(current_account=current_account, bank_info_id=bank_info_id)
            if not bank_info:
                return RampOrderType(success=False, error='Saved payout method not found for the active account')

        client = KoyweClient(crypto_symbol='USDT BSC') if savings_rail else KoyweClient()
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
            if normalized_direction == 'OFF_RAMP':
                if savings_rail:
                    from cusd_plus import vault as cusd_plus_vault
                    # The withdrawable dollar is the WHOLE BSC position, in
                    # whichever leg it currently sits: minted cUSD+ shares plus
                    # raw USDT that landed but hasn't minted (and never will,
                    # for an Ondo-ineligible user). Checking raw USDT alone
                    # refused users whose money was simply already earning —
                    # the funding batch redeems the shortfall and pays from
                    # both legs, so both are genuinely spendable.
                    #
                    # withdrawable_usdt_wei, not raw + position_usd: every read
                    # is fresh (no 30s cache, no 7-day last-known fallback) and
                    # the vault leg is the TRUE redeem output rather than
                    # shares x pPlus, which over-states it and authorized
                    # orders the client then could not fund (audit [P2] #11).
                    # RPC failure raises into the outer error handler.
                    raw_usdt = (
                        Decimal(cusd_plus_vault.usdt_balance_raw(
                            current_account.bsc_address, fresh=True))
                        / Decimal(10 ** 18)
                    )
                    available_usdt = (
                        Decimal(cusd_plus_vault.withdrawable_usdt_wei(current_account.bsc_address))
                        / Decimal(10 ** 18)
                    )
                    # Worth is not the same as withdrawable: redeemToUsdt is
                    # whenNotPaused and refuses while the oracle guard is
                    # tripped. Creating an order the client provably cannot
                    # fund just strands it (re-audit [P2] #9).
                    #
                    # ONLY when a redeem is actually required. Checking this
                    # unconditionally turned a vault pause into an EXIT GATE
                    # on people whose withdrawal never touches the vault — an
                    # Ondo-ineligible user holds raw USDT and their funding is
                    # a bare USDT.transfer (round 3 [P1] #2). Exits are never
                    # gated; that is the whole point of the raw-USDT leg.
                    if raw_usdt < decimal_amount:
                        blocked = cusd_plus_vault.redeem_blocked_reason()
                        if blocked:
                            logger.warning('savings off-ramp refused: %s', blocked)
                            return RampOrderType(
                                success=False,
                                error=('Los retiros desde tu ahorro están pausados por un momento. '
                                       'Vuelve a intentar en unos minutos.'),
                            )
                    if available_usdt < decimal_amount:
                        return RampOrderType(
                            success=False,
                            error=(
                                f'No tienes suficiente saldo disponible para este retiro. '
                                f'Disponible: {available_usdt:.6f}. Requerido: {decimal_amount:.6f}.'
                            ),
                        )
                else:
                    wallet_address = _get_koywe_destination_address(current_account=current_account)
                    available_cusd = _get_algorand_asset_balance(
                        wallet_address,
                        getattr(settings, 'ALGORAND_CUSD_ASSET_ID', None),
                    )
                    if available_cusd < decimal_amount:
                        return RampOrderType(
                            success=False,
                            error=(
                                f'No tienes suficiente cUSD para este retiro. '
                                f'Disponible: {available_cusd:.6f} cUSD. '
                                f'Requerido: {decimal_amount:.6f} cUSD.'
                            ),
                        )

            koywe_email = _get_koywe_auth_email(
                user=user,
                country_code=resolved_country_code,
                email_override=auth_email,
            )
            if (
                normalized_direction == 'ON_RAMP'
                and resolved_country_code == 'CO'
                and str(payment_method_code or '').strip().upper() in {'PSE', 'NEQUI', 'BANCOLOMBIA'}
                and (
                    _is_koywe_test_email(koywe_email)
                    or str(koywe_email).strip().lower().endswith('@privaterelay.appleid.com')
                )
            ):
                return RampOrderType(
                    success=False,
                    error='Ingresa un email real donde puedas recibir el código de PSE.',
                )
            # Koywe owns the profile under whichever email created it. Read the
            # stored inbox before overwriting it, or the migration path loses the
            # only pointer to the account it needs to rename.
            previous_auth_email = str(
                getattr(getattr(user, 'ramp_user_address', None), 'auth_email', '') or ''
            ).strip().lower()
            _store_koywe_auth_email(user=user, auth_email=koywe_email)
            external_id = (
                f'confio-ramp-{normalized_direction.lower()}-'
                f'{timezone.now().strftime("%Y%m%d%H%M%S")}-{uuid.uuid4().hex[:12]}'
            )
            contact_profile = _get_koywe_contact_profile(
                user=user,
                country_code=resolved_country_code,
                email_override=koywe_email,
            )
            missing_profile_fields = []
            if resolved_country_code == 'MX' and not contact_profile.get('addressNeighborhood'):
                missing_profile_fields.append('Colonia')
            if (
                not contact_profile.get('activity')
                or str(contact_profile.get('activity') or '').upper() == 'OTHER'
            ):
                missing_profile_fields.append('Actividad económica')
            if missing_profile_fields:
                return RampOrderType(
                    success=False,
                    error=f'Actualiza la app y completa {", ".join(missing_profile_fields)} en tu dirección para usar Koywe.',
                )

            actor_business = current_account.business if current_account.account_type == 'business' else None
            actor_type = 'business' if current_account.account_type == 'business' else 'user'
            actor_display_name = current_account.display_name or user.get_full_name() or user.username or ''
            actor_address = (
                current_account.bsc_address if savings_rail
                else current_account.algorand_address
            ) or ''

            # Koywe may accept an order before its HTTP response reaches us.
            # Persist the destination first while holding the same Account row
            # lock used by wallet reenrollment. That makes an in-flight order
            # visible to the destructive stale-address gate even while the
            # external request is still running.
            if savings_rail:
                with transaction.atomic():
                    locked_account = Account.objects.select_for_update().filter(
                        pk=current_account.pk,
                        deleted_at__isnull=True,
                    ).first()
                    locked_address = (
                        getattr(locked_account, 'bsc_address', None) or ''
                    ).lower()
                    if not locked_account or locked_address != actor_address.lower():
                        return RampOrderType(
                            success=False,
                            error='La dirección de ahorro cambió. Vuelve a intentar.',
                        )
                    # Serialize the check and insert with the Account row lock.
                    # Without this, two mutations a few milliseconds apart can
                    # both create reservations and both reach Koywe with distinct
                    # external ids. A blank provider id means the earlier create
                    # is either still running or has an ambiguous outcome; both
                    # cases must be reconciled before another order is attempted.
                    unresolved_reservation = RampTransaction.objects.filter(
                        provider='koywe',
                        direction=normalized_direction.lower(),
                        provider_order_id='',
                        actor_user=user,
                        actor_address__iexact=actor_address,
                        destination='cusd_plus',
                    ).exists()
                    if unresolved_reservation:
                        return RampOrderType(
                            success=False,
                            error=(
                                'Ya hay una operación de ahorro en proceso. '
                                'Espera su confirmación antes de volver a intentarlo; '
                                'si el mensaje persiste, contacta a soporte.'
                            ),
                        )
                    address_reservation = RampTransaction.objects.create(
                        provider='koywe',
                        direction=normalized_direction.lower(),
                        status='PENDING',
                        provider_order_id='',
                        external_id=external_id,
                        country_code=(resolved_country_code or '').upper(),
                        actor_user=user,
                        actor_business=actor_business,
                        actor_type=actor_type,
                        actor_display_name=actor_display_name,
                        actor_address=actor_address,
                        destination='cusd_plus',
                        fiat_currency=fiat_currency or _get_country_fiat_currency(resolved_country_code),
                        final_currency=('CUSD+' if normalized_direction == 'ON_RAMP' else 'USDT BSC'),
                        status_detail='Koywe order creation reserved',
                        metadata={
                            'wallet_address_reserved': True,
                            'wallet_address_reservation_state': 'creating_order',
                            'reconcile_key': external_id,
                        },
                    )
            result = client.create_ramp_order(
                direction=normalized_direction,
                amount=decimal_amount,
                fiat_symbol=fiat_currency or _get_country_fiat_currency(resolved_country_code),
                payment_method_code=payment_method_code,
                email=koywe_email,
                wallet_address=(current_account.bsc_address if savings_rail
                                else _get_koywe_destination_address(current_account=current_account)),
                country_code=resolved_country_code,
                bank_info=bank_info,
                external_id=external_id,
                contact_profile=contact_profile,
                previous_emails=_get_koywe_profile_previous_emails(
                    user=user,
                    country_code=resolved_country_code,
                    document_number=contact_profile.get('documentNumber') or '',
                    selected_email=koywe_email,
                    prior_auth_email=previous_auth_email,
                ),
            )
        except KoyweOrderCreationAmbiguousError as exc:
            _mark_ambiguous_koywe_reservation(address_reservation)
            return RampOrderType(
                success=False,
                error=(
                    'Koywe no confirmó si creó la orden. No vuelvas a intentarlo; '
                    'soporte debe verificarla primero.'
                ),
            )
        except KoyweConfigurationError as exc:
            _release_proven_empty_koywe_reservation(
                address_reservation, account_id=current_account.pk)
            return RampOrderType(success=False, error=str(exc))
        except KoyweMinimumAmountError as exc:
            _release_proven_empty_koywe_reservation(
                address_reservation, account_id=current_account.pk)
            logger.info('Koywe ramp order below minimum: %s', exc)
            return RampOrderType(
                success=False,
                error=_format_minimum_amount_error(exc, normalized_direction),
            )
        except KoyweMaximumAmountError as exc:
            _release_proven_empty_koywe_reservation(
                address_reservation, account_id=current_account.pk)
            logger.info('Koywe ramp order above maximum: %s', exc)
            return RampOrderType(
                success=False,
                error=_format_maximum_amount_error(exc, normalized_direction),
            )
        except KoyweError as exc:
            _release_proven_empty_koywe_reservation(
                address_reservation, account_id=current_account.pk)
            logger.warning('Koywe ramp order failed: %s', exc)
            return RampOrderType(success=False, error=str(exc))
        except Exception as exc:
            # Unknown application failures may happen after Koywe accepted the
            # POST. Fail closed exactly like a transport timeout.
            _mark_ambiguous_koywe_reservation(address_reservation)
            logger.exception('Unexpected Koywe ramp order failure')
            return RampOrderType(success=False, error='Unexpected Koywe error while creating the order')

        actor_business = current_account.business if current_account.account_type == 'business' else None
        actor_type = 'business' if current_account.account_type == 'business' else 'user'
        actor_display_name = current_account.display_name or user.get_full_name() or user.username or ''
        actor_address = (current_account.bsc_address if savings_rail else current_account.algorand_address) or ''
        upsert_koywe_ramp_transaction(
            destination=destination,
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
            payment_details=annotate_koywe_deposit_address(
                result.raw_response, savings_rail=savings_rail,
                allow_funding=_provider_amount_matches(
                    result.amount_in, decimal_amount,
                    enforce=(normalized_direction == 'OFF_RAMP'),
                ),
            ),
            instruction_snapshot=build_koywe_instruction_snapshot(
                order_payload=result.raw_response,
                next_action_url=result.next_action_url,
            ),
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

        employee_denial = _employee_ramp_denial(info)
        if employee_denial:
            return RampOrderType(success=False, error=employee_denial)

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

        if normalized_direction == "OFF_RAMP" and resolved_country_code == "BO":
            return RampOrderType(success=False, error='Retiro en BOB no está disponible por ahora. En Bolivia solo está habilitada la recarga.')

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
        if normalized_direction == "ON_RAMP":
            next_step = "SHOW_PAYMENT_INSTRUCTIONS"
        else:
            next_step = "MOCK_WAIT_FOR_USDC_TRANSFER"

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
            instruction_snapshot=None,
        )


class LandingStatsType(graphene.ObjectType):
    """Public traction numbers for the confio.lat landing page. Definitions
    mirror the admin dashboard so marketing and ops always quote the same
    figures (Koywe grey-box "On-chain Deposited Volume"; presale raised)."""
    deposited_volume_usd = graphene.Float()
    presale_raised_usd = graphene.Float()


class Query(graphene.ObjectType):
    landing_stats = graphene.Field(
        LandingStatsType,
        description='Public, unauthenticated; cached 10 min',
    )

    def resolve_landing_stats(self, info):
        from django.core.cache import cache
        from django.db.models import Sum

        cached = cache.get('landing_stats_v1')
        if cached:
            return LandingStatsType(**cached)

        deposited = RampTransaction.objects.filter(
            provider='koywe', direction='on_ramp', status='COMPLETED',
        ).aggregate(total=Sum('final_amount'))['total'] or Decimal('0')

        from presale.models import PresalePhase
        raised = sum((p.total_raised for p in PresalePhase.objects.all()), Decimal('0'))

        data = {
            'deposited_volume_usd': float(deposited),
            'presale_raised_usd': float(raised),
        }
        cache.set('landing_stats_v1', data, 600)
        return LandingStatsType(**data)

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
    economic_activities = graphene.List(
        EconomicActivityOptionType,
        country_code=graphene.String(),
    )
    ramp_address_requirements = graphene.Field(
        RampAddressRequirementType,
        country_code=graphene.String(),
    )

    def resolve_ramp_address_requirements(self, info, country_code=None):
        normalized_country = (country_code or _resolve_ramp_country_code(info)).strip().upper()
        if normalized_country == 'MX':
            return RampAddressRequirementType(
                requires_address_neighborhood=True,
                address_neighborhood_label='Colonia',
                address_neighborhood_placeholder='Colonia',
            )
        return RampAddressRequirementType(
            requires_address_neighborhood=False,
            address_neighborhood_label='Colonia o barrio',
            address_neighborhood_placeholder='Colonia o barrio',
        )

    def resolve_economic_activities(self, info, country_code=None):
        return [
            EconomicActivityOptionType(label=value, value=value)
            for value in sorted(MEXICO_ECONOMIC_ACTIVITIES)
        ]

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
            dynamic_limits = koywe_client.get_dynamic_ramp_limits(
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
            resolved_fiat_symbol = fiat_currency or _get_country_fiat_currency(resolved_country_code)
            if normalized_direction == "ON_RAMP":
                try:
                    _validate_koywe_on_ramp_quote_limits(
                        client=client,
                        amount=decimal_amount,
                        fiat_symbol=resolved_fiat_symbol,
                    )
                except KoyweError as exc:
                    if isinstance(exc, (KoyweMinimumAmountError, KoyweMaximumAmountError)):
                        raise
                    logger.warning(
                        "Koywe public limit preflight failed for %s %s: %s",
                        normalized_direction,
                        resolved_country_code,
                        exc,
                    )
            user = getattr(info.context, "user", None)
            koywe_email = _get_koywe_auth_email(
                user=user,
                country_code=resolved_country_code,
            ) if user and getattr(user, "is_authenticated", False) else None
            quote = client.get_ramp_quote(
                direction=normalized_direction,
                amount=decimal_amount,
                fiat_symbol=resolved_fiat_symbol,
                payment_method_code=payment_method_code,
                email=koywe_email,
            )
        except KoyweMinimumAmountError as exc:
            logger.info(
                "Koywe ramp quote below minimum for %s %s: %s",
                normalized_direction,
                resolved_country_code,
                exc,
            )
            raise ValidationError(_format_minimum_amount_error(exc, normalized_direction))
        except KoyweMaximumAmountError as exc:
            logger.info(
                "Koywe ramp quote above maximum for %s %s: %s",
                normalized_direction,
                resolved_country_code,
                exc,
            )
            raise ValidationError(_format_maximum_amount_error(exc, normalized_direction))
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
            payment_details=annotate_koywe_deposit_address(
                result.raw_response,
                savings_rail=(getattr(ramp_tx, 'destination', None) == 'cusd_plus'),
                # Re-verify on EVERY read, against the amount this order was
                # created for. Defaulting to allow_funding=True here handed a
                # fresh vouched address to any resume path and quietly undid
                # the creation-time refusal (round 3 [P2] #9).
                # No row means nothing to verify the provider's amount
                # against, so enforcement must stay ON and fail closed —
                # reading `direction` off a missing row yielded enforce=False,
                # which vouched for an address with no order behind it
                # (round 4 [P2] #11).
                allow_funding=_provider_amount_matches(
                    getattr(result, 'amount_in', None),
                    _ramp_tx_crypto_amount(ramp_tx),
                    enforce=(ramp_tx is None
                             or (getattr(ramp_tx, 'direction', '') or '').lower() == 'off_ramp'),
                ),
            ),
            instruction_snapshot=build_koywe_instruction_snapshot(
                order_payload=result.raw_response,
                next_action_url=result.next_action_url,
            ),
            instruction_snapshot_created=(ramp_tx.metadata or {}).get('instruction_snapshot_created') if ramp_tx else None,
            instruction_snapshot_latest=(ramp_tx.metadata or {}).get('instruction_snapshot_latest') if ramp_tx else None,
            provider_payload_created=(ramp_tx.metadata or {}).get('provider_payload_created') if ramp_tx else None,
            provider_payload_latest=(ramp_tx.metadata or {}).get('provider_payload_latest') if ramp_tx else None,
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
            instruction_snapshot_created=(ramp_tx.metadata or {}).get('instruction_snapshot_created'),
            instruction_snapshot_latest=(ramp_tx.metadata or {}).get('instruction_snapshot_latest'),
            provider_payload_created=(ramp_tx.metadata or {}).get('provider_payload_created'),
            provider_payload_latest=(ramp_tx.metadata or {}).get('provider_payload_latest'),
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


def _employee_ramp_denial(info):
    """API half of the owner-only ramp rule (users/jwt_context holds the
    primitive and the message, because the Guardarian REST proxy in
    config/views.py must enforce the same thing).

    Returns a user-facing error string when the caller must be blocked,
    otherwise None.
    """
    from users.jwt_context import (
        RAMP_OWNER_ONLY_MESSAGE,
        get_jwt_business_context_with_validation,
        is_business_employee,
    )

    jwt_context = get_jwt_business_context_with_validation(info, required_permission=None)
    if not jwt_context:
        return None
    if jwt_context.get('account_type') != 'business':
        return None
    # ONE source of truth, shared with the REST proxy: ask the table directly
    # rather than trusting a key on the context dict. Both read the same rows,
    # and a single code path means both entry points cannot drift.
    if is_business_employee(getattr(info.context, 'user', None),
                            jwt_context.get('business_id')):
        return RAMP_OWNER_ONLY_MESSAGE
    return None


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
    return getattr(current_account, 'algorand_address', None)


# The ONE key the client is allowed to fund from. Namespaced so it can never
# collide with a provider field.
CONFIO_DEPOSIT_ADDRESS_KEY = 'confioDepositAddress'
CONFIO_DEPOSIT_NETWORK_KEY = 'confioDepositNetwork'

# Documented Koywe fields that carry the deposit address, ORDER-SPECIFIC
# FIRST. `providedAddress` is ranked last on purpose: koywe_client's
# _merge_payment_provider_details copies paymentProvider.details into it, and
# paymentProvider is generic provider metadata rather than this order's
# deposit target. Ranking it first meant a response carrying both would fund
# the metadata instead of the order (re-audit [P1] #1).
_KOYWE_DEPOSIT_ADDRESS_FIELDS = (
    'depositAddress', 'walletAddress', 'address', 'providedAddress',
)

_EVM_ADDRESS_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')
_ALGO_ADDRESS_RE = re.compile(r'^[A-Z2-7]{58}$')

# Never a valid destination for a user's funds.
_EVM_FORBIDDEN_DESTINATIONS = frozenset({
    '0x0000000000000000000000000000000000000000',
    '0x55d398326f99059ff775485246999027b3197955',  # USDT-BSC itself
})


def _ramp_tx_crypto_amount(ramp_tx) -> Decimal | None:
    """The crypto amount an off-ramp order was created for, canonicalized.

    None when there is no row to compare against — the caller then cannot
    verify anything and must not vouch for funding.
    """
    if ramp_tx is None:
        return None
    raw = getattr(ramp_tx, 'crypto_amount_estimated', None)
    if raw is None:
        return None
    try:
        return Decimal(str(raw)).quantize(Decimal('0.000001'), rounding=ROUND_DOWN)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _provider_amount_matches(provider_amount_in, requested, *,
                             enforce: bool) -> bool:
    """Does the provider intend to charge exactly what we asked for?

    The client funds the amount IT ordered and never looked at what Koywe
    echoed back, so a provider-side normalization would have the transfer
    paying a different number than the order it funds (re-audit [P1] #4).
    Unreadable or mismatched => no auto-funding.

    `enforce` is False on ON_RAMP, where amount_in is the fiat the user pays
    a bank and no on-chain transfer of ours depends on it.
    """
    if not enforce:
        return True
    if requested is None:
        logger.error('No recorded order amount to verify against; refusing to auto-fund')
        return False
    try:
        echoed = Decimal(str(provider_amount_in)).quantize(
            Decimal('0.000001'), rounding=ROUND_DOWN)
    except (InvalidOperation, TypeError, ValueError):
        logger.error('Koywe returned an unreadable amount_in (%r); refusing to auto-fund',
                     provider_amount_in)
        return False
    if echoed != requested:
        logger.error(
            'Koywe amount_in %s != requested %s; refusing to auto-fund this order',
            echoed, requested,
        )
        return False
    return True


def annotate_koywe_deposit_address(raw_response, *, savings_rail: bool,
                                   allow_funding: bool = True):
    """Resolve the deposit address ONCE, server-side, from a documented field.

    The client used to walk every string in this blob and fund the first
    `0x…`-shaped match it found. Field order in a JSON object is not a
    contract: a response carrying `tokenAddress` (the USDT contract) before
    the deposit address would have sent the user's withdrawal to a token
    contract, unrecoverably (audit 2026-08-03 [P1] #5).

    Returns the payload with a namespaced, validated address attached, or
    without it when nothing valid was found — in which case the client
    refuses to fund rather than guessing.
    """
    if not isinstance(raw_response, dict):
        return raw_response

    annotated = dict(raw_response)
    annotated.pop(CONFIO_DEPOSIT_ADDRESS_KEY, None)   # never trust an echo
    annotated.pop(CONFIO_DEPOSIT_NETWORK_KEY, None)

    if not allow_funding:
        # The caller could not reconcile what the provider is charging with
        # what we asked for. Withhold the address so nothing is auto-funded:
        # paying a number nobody verified is how the deposit ends up
        # different from the order (re-audit [P1] #4).
        #
        # Be precise about what the user gets: automatic funding is REFUSED.
        # The instructions screen still shows the provider's own payload, so
        # a determined user can pay by hand, but there is no verified
        # in-app funding action behind this — the order should be treated as
        # needing support, not as merely "not funded yet" (round 3 [P2] #10).
        return annotated

    # Collect EVERY documented field, not just the first. Two documented
    # fields disagreeing means we cannot tell which one is the order's true
    # deposit target, and picking by priority would be a guess with the
    # user's money — so that case fails CLOSED (re-audit [P1] #1).
    # `providedAddress` is only trustworthy when it came from the ORDER. When
    # koywe_client synthesized it from paymentProvider.details it is generic
    # provider metadata wearing an order field's name, and paying it would be
    # paying whatever that free-text field happens to hold (round 3 [P1] #4).
    synthesized = bool(raw_response.get('providedAddressFromProviderDetails'))

    seen: list[tuple[str, str]] = []
    for field in _KOYWE_DEPOSIT_ADDRESS_FIELDS:
        if field == 'providedAddress' and synthesized:
            continue
        value = str(raw_response.get(field) or '').strip()
        if value:
            seen.append((field, value))

    if not seen:
        if synthesized:
            logger.error(
                'Koywe order has no order-specific deposit address — only '
                'paymentProvider.details. Refusing to auto-fund provider metadata; '
                'the user funds manually from the instructions screen.'
            )
        else:
            logger.warning('Koywe order carries no deposit address field; funding will be refused')
        return annotated

    distinct = {value.lower() for _, value in seen}
    if len(distinct) > 1:
        logger.error(
            'Koywe order returned conflicting deposit addresses %s; refusing to fund',
            [f'{field}={value}' for field, value in seen],
        )
        return annotated

    candidate = seen[0][1]

    if savings_rail:
        if not _EVM_ADDRESS_RE.match(candidate):
            logger.warning('Koywe savings deposit address is not a BSC address; refusing')
            return annotated
        if candidate.lower() in _EVM_FORBIDDEN_DESTINATIONS:
            logger.error('Koywe returned a forbidden BSC destination (%s); refusing', candidate)
            return annotated
        annotated[CONFIO_DEPOSIT_NETWORK_KEY] = 'BSC'
    else:
        if not _ALGO_ADDRESS_RE.match(candidate):
            logger.warning('Koywe deposit address is not an Algorand address; refusing')
            return annotated
        annotated[CONFIO_DEPOSIT_NETWORK_KEY] = 'ALGO'

    annotated[CONFIO_DEPOSIT_ADDRESS_KEY] = candidate
    return annotated


def _get_algorand_asset_balance(address: str | None, asset_id: int | None) -> Decimal:
    normalized_address = str(address or '').strip()
    if not normalized_address or not asset_id:
        return Decimal('0')

    from blockchain.algorand_client import get_algod_client

    algod_client = get_algod_client()
    account_info = algod_client.account_info(normalized_address)
    for asset in account_info.get('assets', []) or []:
        if int(asset.get('asset-id') or 0) == int(asset_id):
            amount = int(asset.get('amount') or 0)
            return (Decimal(amount) / Decimal('1000000')).quantize(Decimal('0.000001'))
    return Decimal('0')


def _get_koywe_test_account_override(*, user, country_code: str) -> dict[str, str] | None:
    if not user:
        return None
    username = str(getattr(user, 'username', '') or '').strip().lower()
    if username not in _KOYWE_TEST_OVERRIDE_USERNAMES:
        return None
    return _KOYWE_TEST_ACCOUNT_OVERRIDES.get((country_code or '').strip().upper())


def _is_koywe_test_email(value: str | None) -> bool:
    return str(value or '').strip().lower().endswith('@koywe-test.com')


def _get_koywe_previous_emails(*, country_code: str, document_number: str) -> list[str]:
    """Return emails that may hold an existing Koywe account for this document.

    Queries IdentityVerification for all users sharing the same document number
    and collects their user emails plus any stored ramp auth emails.
    """
    normalized_doc = normalize_document_number(document_number)
    emails: list[str] = []
    if normalized_doc:
        verifications = (
            IdentityVerification.objects
            .filter(document_number_normalized=normalized_doc, status='verified')
            .select_related('user', 'user__ramp_user_address')
        )
        for v in verifications:
            user = v.user
            if user:
                user_email = str(getattr(user, 'email', '') or '').strip().lower()
                if user_email:
                    emails.append(user_email)
                ramp_email = str(
                    getattr(getattr(user, 'ramp_user_address', None), 'auth_email', '') or ''
                ).strip().lower()
                if ramp_email:
                    emails.append(ramp_email)
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for e in emails:
        if e not in seen:
            seen.add(e)
            unique.append(e)
    return unique


def _get_koywe_profile_previous_emails(
    *,
    user,
    country_code: str,
    document_number: str,
    selected_email: str,
    prior_auth_email: str | None = None,
) -> list[str]:
    """Return prior account emails, including the test identity being migrated.

    Colombia's PSE email must be deliverable, so the designated test users
    authenticate with their real inbox while retaining the country-specific
    delegated-KYC identity. Koywe may already own that identity under the
    duende address; include it only for those designated users so updateEmail
    can migrate the existing profile.

    The designated test users share one delegated-KYC identity per country, and
    Koywe enforces document uniqueness, so the profile can only live under one
    of their inboxes at a time. Include the siblings' stored emails as well, or
    the second test user can never take the identity over.
    """
    previous_emails = _get_koywe_previous_emails(
        country_code=country_code,
        document_number=document_number,
    )
    override = _get_koywe_test_account_override(user=user, country_code=country_code)
    override_email = str((override or {}).get('email') or '').strip().lower()
    normalized_selected_email = str(selected_email or '').strip().lower()
    if override:
        for sibling_email in _get_koywe_test_sibling_emails(user=user):
            previous_emails.insert(0, sibling_email)
    if override_email and override_email != normalized_selected_email:
        previous_emails.insert(0, override_email)
    normalized_prior = str(prior_auth_email or '').strip().lower()
    if normalized_prior and not _is_koywe_test_email(normalized_prior):
        previous_emails.insert(0, normalized_prior)
    return [
        email for email in dict.fromkeys(previous_emails)
        if email and email != normalized_selected_email
    ]


def _get_koywe_test_sibling_emails(*, user) -> list[str]:
    """Emails of the other designated test users, newest stored inbox first."""
    username = str(getattr(user, 'username', '') or '').strip().lower()
    siblings = _KOYWE_TEST_OVERRIDE_USERNAMES - {username}
    if not siblings:
        return []
    username_filter = Q()
    for sibling_username in siblings:
        username_filter |= Q(username__iexact=sibling_username)
    emails: list[str] = []
    for sibling in (
        get_user_model().objects
        .filter(username_filter)
        .select_related('ramp_user_address')
    ):
        ramp_email = str(
            getattr(getattr(sibling, 'ramp_user_address', None), 'auth_email', '') or ''
        ).strip().lower()
        if ramp_email and not _is_koywe_test_email(ramp_email):
            emails.append(ramp_email)
        sibling_email = str(getattr(sibling, 'email', '') or '').strip().lower()
        if sibling_email and not sibling_email.endswith('@privaterelay.appleid.com'):
            emails.append(sibling_email)
    return list(dict.fromkeys(emails))


def _get_koywe_auth_email(*, user, country_code: str, email_override: str | None = None) -> str:
    normalized_country_code = str(country_code or '').strip().upper()
    override = _get_koywe_test_account_override(user=user, country_code=normalized_country_code)
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
    # duende addresses identify delegated-KYC test profiles, but cannot receive
    # Colombia PSE messages. Never reuse one as the persisted delivery inbox.
    if normalized_country_code == 'CO' and _is_koywe_test_email(stored_ramp_email):
        stored_ramp_email = ''
    country_default_email = (
        stored_ramp_email
        if normalized_country_code == 'CO'
        else str((override or {}).get('email') or '').strip()
        or stored_ramp_email
    )
    email = str(
        normalized_override
        or country_default_email
        or getattr(user, 'email', None)
        or ''
    ).strip()
    if not email:
        raise KoyweError('Tu cuenta debe tener un email para usar recargas y retiros')
    return email


def _store_koywe_auth_email(*, user, auth_email: str | None) -> None:
    normalized_email = str(auth_email or '').strip().lower()
    if not user or not normalized_email or _is_koywe_test_email(normalized_email):
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
    address_neighborhood = (
        (ramp_address.address_neighborhood or '').strip()
        if ramp_address and getattr(ramp_address, 'address_neighborhood', None)
        else (verification.verified_address_neighborhood or '').strip()
        if verification and getattr(verification, 'verified_address_neighborhood', None)
        else ''
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
        address_neighborhood=address_neighborhood,
        address_city=address_city,
        address_state=address_state,
        address_zip_code=address_zip_code,
        economic_activity=(ramp_address.economic_activity or '').strip() if ramp_address and getattr(ramp_address, 'economic_activity', None) else '',
        auth_email=(ramp_address.auth_email or '').strip() if ramp_address and getattr(ramp_address, 'auth_email', None) else '',
        address_country=address_country,
        updated_at=getattr(ramp_address, 'updated_at', None) or getattr(verification, 'updated_at', None),
    )


def _is_ramp_address_complete(value) -> bool:
    user = getattr(value, 'user', None)
    country = _get_user_phone_country_alpha3(user)
    base_complete = bool(
        getattr(value, 'address_street', None)
        and getattr(value, 'address_city', None)
        and getattr(value, 'address_state', None)
        and getattr(value, 'address_zip_code', None)
        and country
    )
    if not base_complete:
        return False

    economic_activity = str(getattr(value, 'economic_activity', '') or '').strip()
    if not economic_activity or economic_activity.upper() == 'OTHER':
        return False

    if country == 'MEX':
        return bool(str(getattr(value, 'address_neighborhood', '') or '').strip())

    return True


def _get_koywe_contact_profile(*, user, country_code: str, email_override: str | None = None) -> dict[str, str]:
    verification = _get_latest_personal_verification(user)
    override = _get_koywe_test_account_override(user=user, country_code=country_code)
    # The order email and delegated-KYC identity are separate concerns. In
    # Colombia the former must be a real inbox for PSE, while these explicitly
    # designated test users still use the country-specific test identity.
    use_override_identity = bool(override)

    if use_override_identity:
        first_name = str((override or {}).get('firstName') or '').strip()
        last_name = str((override or {}).get('lastName') or '').strip()
    else:
        if not verification:
            raise KoyweError('Completa la verificación de identidad antes de usar recargas y retiros')
        first_name = str(getattr(verification, 'verified_first_name', None) or '').strip()
        last_name = str(getattr(verification, 'verified_last_name', None) or '').strip()
        if not first_name or not last_name:
            raise KoyweError('No pudimos preparar la operación porque falta el nombre legal verificado. Contacta soporte')
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
    if use_override_identity:
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
    if effective_address.address_neighborhood:
        profile['addressNeighborhood'] = effective_address.address_neighborhood
    if effective_address.address_state:
        profile['addressState'] = effective_address.address_state
    if effective_address.address_zip_code:
        profile['addressZipCode'] = effective_address.address_zip_code
    if effective_address.address_country:
        profile['addressCountry'] = effective_address.address_country
    if use_override_identity:
        profile['addressCountry'] = ISO2_TO_ISO3.get(
            str(country_code or '').strip().upper(),
            str(country_code or '').strip().upper(),
        )
    if effective_address.economic_activity:
        profile['activity'] = effective_address.economic_activity
    return {key: value for key, value in profile.items() if value}


class Mutation(graphene.ObjectType):
    create_ramp_order = CreateRampOrder.Field()
    create_mock_ramp_order = CreateMockRampOrder.Field()
    upsert_ramp_user_address = UpsertRampUserAddress.Field()
