import uuid
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from payment_accounts.clients import ProviderAPIError
from payment_accounts.eligibility import (
    context_from_identity,
    enforce_and_record,
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
from payment_accounts.providers import get_provider
from payment_accounts.providers.base import ProviderCapabilityError
from payment_accounts.providers.common import same_country


class PaymentAccountError(RuntimeError):
    pass


def _require_provider_enabled(provider):
    setting_name = f'{provider.upper()}_PAYMENT_ACCOUNTS_ENABLED'
    if not getattr(settings, setting_name, False):
        raise PaymentAccountError(f'{provider.title()} payment accounts are not enabled')


PROVIDER_ACCOUNT_SHAPES = {
    'cobre': ('omnibus_subledger', {('COL', 'COP')}),
    'infinia': (
        'provider_named',
        {
            ('ARG', 'ARS'), ('BOL', 'BOB'), ('BRA', 'BRL'), ('CHL', 'CLP'),
            ('COL', 'COP'), ('MEX', 'MXN'), ('PER', 'PEN'), ('PRY', 'PYG'),
            ('URY', 'UYU'), ('USA', 'USD'), ('GBR', 'GBP'), ('GBR', 'EUR'),
            ('LUX', 'EUR'),
            ('XXX', 'USDT'), ('XXX', 'USDC'), ('XXX', 'USDC_POL'),
            ('XXX', 'USDT_POL'), ('XXX', 'EURC_BASE'), ('XXX', 'USDC_BASE'),
            ('XXX', 'USDT_BASE'), ('XXX', 'USDC_ETH'), ('XXX', 'USDT_ETH'),
            ('XXX', 'EURC_ETH'), ('XXX', 'USDC_TEMPO'), ('XXX', 'USDT_TEMPO'),
            ('XXX', 'EURC_TEMPO'), ('XXX', 'BRLA_ETH'), ('XXX', 'BRLA_POL'),
            ('XXX', 'BRLA_BASE'), ('XXX', 'TGBP_ETH'), ('XXX', 'TGBP_POL'),
            ('XXX', 'TGBP_BASE'),
        },
    ),
}


TERMINAL_OPERATION_STATUSES = {'succeeded', 'failed', 'reversed'}
ALLOWED_OPERATION_TRANSITIONS = {
    'created': {'submitted', 'processing', 'settling', 'succeeded', 'failed', 'needs_review', 'unknown'},
    'submitted': {'processing', 'settling', 'succeeded', 'failed', 'needs_review', 'unknown'},
    'processing': {'settling', 'succeeded', 'failed', 'needs_review', 'unknown'},
    'settling': {'succeeded', 'failed', 'reversed', 'needs_review', 'unknown'},
    'unknown': {'submitted', 'processing', 'settling', 'succeeded', 'failed', 'needs_review'},
    'needs_review': {'processing', 'settling', 'succeeded', 'failed', 'reversed'},
    'succeeded': {'reversed'},
    'failed': set(),
    'reversed': set(),
}

INFINIA_DESTINATION_REQUIREMENTS = {
    'CBU': {'cbu'},
    'ALIAS': {'alias'},
    'QR_CODE': {'qrCode'},
    'ACH': {'accountNumber', 'name', 'documentNumber', 'reference', 'bankCode', 'bankBranch'},
    'ACCOUNT_BRAZIL': {'ispb', 'number', 'issuer', 'accountType', 'documentNumber'},
    'BR_CODE': {'brCode'},
    'CHAVE PIX': {'chavePix'},
    'ACCOUNT_CHILE': {
        'currency', 'bankCode', 'accountType', 'accountNumber',
        'documentType', 'documentNumber', 'name',
    },
    'ACCOUNT_COLOMBIA': {
        'fullName', 'documentType', 'documentNumber', 'bankCode',
        'accountType', 'accountNumber',
    },
    'BREB_KEY': {'brebKey'},
    'CLABE': {'clabe', 'reference'},
    'ACCOUNT_PARAGUAY': {
        'bankCode', 'name', 'accountNumber', 'documentType', 'documentNumber',
    },
    'ACCOUNT_PERU': {
        'currency', 'bankCode', 'accountType', 'documentType',
        'documentNumber', 'name', 'state',
    },
    'ACCOUNT_EUROPE_SEPA': {
        'iban', 'beneficiaryType', 'beneficiaryFirstName', 'beneficiaryCountry',
    },
    'ACCOUNT_UNITED_KINGDOM_CHAPS_FPS': {
        'beneficiaryType', 'beneficiaryFirstName', 'beneficiaryCountry',
    },
    'ETHEREUM': {'address'},
    'POLYGON': {'address'},
    'TRON': {'address'},
    'TEMPO': {'address'},
}

INFINIA_DESTINATION_COUNTRIES = {
    'CBU': 'ARG', 'ALIAS': 'ARG', 'QR_CODE': 'ARG', 'ACH': 'BOL',
    'ACCOUNT_BRAZIL': 'BRA', 'BR_CODE': 'BRA', 'CHAVE PIX': 'BRA',
    'ACCOUNT_CHILE': 'CHL', 'ACCOUNT_COLOMBIA': 'COL', 'BREB_KEY': 'COL',
    'CLABE': 'MEX', 'ACCOUNT_PARAGUAY': 'PRY', 'ACCOUNT_PERU': 'PER',
    'ACCOUNT_UNITED_KINGDOM_CHAPS_FPS': 'GBR',
}


def _validate_infinia_destination(*, kind, country, details):
    destination_type = str(details.get('type') or '').strip().upper()
    required = INFINIA_DESTINATION_REQUIREMENTS.get(destination_type)
    if not required:
        raise PaymentAccountError('Unsupported Infinia payout destination type')
    details['type'] = destination_type
    missing = sorted(key for key in required if details.get(key) in (None, ''))
    if missing:
        raise PaymentAccountError(
            f'Infinia destination is missing required fields: {", ".join(missing)}'
        )
    expected_country = INFINIA_DESTINATION_COUNTRIES.get(destination_type)
    if expected_country and country != expected_country:
        raise PaymentAccountError('Infinia destination type does not match its country')
    crypto_types = {'ETHEREUM', 'POLYGON', 'TRON', 'TEMPO'}
    if kind == 'crypto_wallet' and destination_type not in crypto_types:
        raise PaymentAccountError('Crypto wallet destination requires a crypto network type')
    if kind != 'crypto_wallet' and destination_type in crypto_types:
        raise PaymentAccountError('Crypto network destination must use crypto_wallet kind')
    if kind == 'breb_key' and destination_type != 'BREB_KEY':
        raise PaymentAccountError('Bre-B destination requires BREB_KEY type')
    if destination_type == 'QR_CODE' and kind != 'qr':
        raise PaymentAccountError('QR_CODE destination must use qr kind')
    if kind == 'qr' and destination_type != 'QR_CODE':
        raise PaymentAccountError('QR destination requires QR_CODE type')
    if kind == 'bank_account' and destination_type in crypto_types | {'BREB_KEY', 'QR_CODE'}:
        raise PaymentAccountError('Bank account kind does not match destination type')
    if destination_type in {'ACCOUNT_COLOMBIA', 'ACCOUNT_PARAGUAY'}:
        try:
            details['bankCode'] = int(details['bankCode'])
        except (TypeError, ValueError) as exc:
            raise PaymentAccountError('Destination bankCode must be numeric') from exc


def identity_snapshot(identity):
    return {
        'full_name': f'{identity.verified_first_name} {identity.verified_last_name}'.strip(),
        'first_name': identity.verified_first_name,
        'last_name': identity.verified_last_name,
        'date_of_birth': identity.verified_date_of_birth.isoformat(),
        'nationality': identity.verified_nationality.upper(),
        'residence_country': identity.verified_country.upper(),
        'address': identity.verified_address,
        'city': identity.verified_city,
        'state': identity.verified_state,
        'postal_code': identity.verified_postal_code or '',
        'document_type': identity.document_type,
        'document_number': identity.document_number,
        'document_issuing_country': identity.document_issuing_country.upper(),
        'document_expiry_date': (
            identity.document_expiry_date.isoformat() if identity.document_expiry_date else None
        ),
    }


def _apply_profile_result(profile, result):
    existing_raw = (profile.provider_data or {}).get('latest') or {}
    existing_at = parse_datetime(str(existing_raw.get('updated_at') or ''))
    incoming_at = parse_datetime(str((result.raw or {}).get('updated_at') or ''))
    if existing_at and incoming_at and incoming_at < existing_at:
        return
    if profile.status == 'active' and result.status == 'pending':
        result = type(result)(
            result.resource_id,
            profile.status,
            result.provider_status,
            result.raw,
            result.available_balance,
            result.current_balance,
        )
    profile.provider_owner_id = result.resource_id or profile.provider_owner_id
    profile.status = result.status
    profile.provider_status = result.provider_status
    profile.provider_data = {**(profile.provider_data or {}), 'latest': result.raw}
    profile.save(
        update_fields=[
            'provider_owner_id', 'status', 'provider_status', 'provider_data', 'updated_at'
        ]
    )


def _apply_account_result(account, result):
    existing_raw = (account.provider_data or {}).get('latest') or {}
    existing_at = parse_datetime(str(existing_raw.get('updated_at') or ''))
    incoming_at = parse_datetime(str((result.raw or {}).get('updated_at') or ''))
    if existing_at and incoming_at and incoming_at < existing_at:
        return
    if account.status == 'active' and result.status == 'pending':
        result = type(result)(
            result.resource_id,
            account.status,
            result.provider_status,
            result.raw,
            result.available_balance,
            result.current_balance,
        )
    account.provider_account_id = result.resource_id or account.provider_account_id
    account.status = result.status
    account.provider_status = result.provider_status
    account.provider_data = {**(account.provider_data or {}), 'latest': result.raw}
    fields = ['provider_account_id', 'status', 'provider_status', 'provider_data', 'updated_at']
    if result.available_balance is not None:
        account.available_balance = result.available_balance
        fields.append('available_balance')
    if result.current_balance is not None:
        account.current_balance = result.current_balance
        fields.append('current_balance')
    if result.available_balance is not None or result.current_balance is not None:
        account.balance_updated_at = timezone.now()
        fields.append('balance_updated_at')
    account.save(update_fields=fields)


def _infinia_capabilities(account):
    raw = (account.provider_data or {}).get('latest') or {}
    values = raw.get('capabilities') or {}
    if isinstance(values, list):
        values = {str(value).lower(): True for value in values}
    if not isinstance(values, dict):
        values = {}
    mapping = {
        'payin_same_name': 'receive_same_name',
        'payin_third_party': 'receive_third_party',
        'payout_same_name': 'send_same_name',
        'payout_third_party': 'send_third_party',
        'payout_qr': 'send_qr',
    }
    identity = account.provider_profile.identity_snapshot or {}
    is_national = same_country(identity.get('nationality'), account.country)
    is_business = account.provider_profile.owner_type == 'business'
    documented_defaults = {
        'payin_same_name': 'enabled' if is_national else 'not_applicable',
        'payin_third_party': 'enabled' if is_business else 'pending',
        'payout_same_name': 'enabled' if is_national else 'not_applicable',
        'payout_third_party': 'enabled',
        'payout_qr': 'enabled',
    }
    for provider_name, canonical in mapping.items():
        value = values.get(provider_name, documented_defaults[provider_name])
        if isinstance(value, str):
            normalized = value.upper()
            status = 'pending' if normalized in {'PENDING', 'UPON_APPROVAL'} else (
                'enabled' if normalized in {'TRUE', 'ENABLED', 'SUPPORTED'} else 'disabled'
            )
            if normalized in {'NOT_APPLICABLE', 'N/A'}:
                status = 'not_applicable'
        else:
            status = 'enabled' if value is True else 'disabled'
        AccountCapability.objects.update_or_create(
            financial_account=account,
            capability=canonical,
            defaults={
                'status': status,
                'reason': (
                    'Provider response' if provider_name in values
                    else 'Infinia documented account-owner default'
                ),
                'provider_value': {'value': value},
            },
        )
    products = raw.get('products') or []
    if isinstance(products, list) and 'INTERNAL_TRANSFER' in {
        str(value).upper() for value in products
    }:
        AccountCapability.objects.update_or_create(
            financial_account=account,
            capability='convert',
            defaults={
                'status': 'enabled',
                'reason': 'Infinia account INTERNAL_TRANSFER product',
                'provider_value': {'product': 'INTERNAL_TRANSFER'},
            },
        )


def sync_capabilities(account):
    if account.provider == 'cobre':
        confirmed = {
            'receive_third_party': 'Cobre Bre-B salary receipt confirmed',
            'send_third_party': 'Cobre Colombia Bre-B payout supported',
        }
        for capability, reason in confirmed.items():
            AccountCapability.objects.update_or_create(
                financial_account=account,
                capability=capability,
                defaults={'status': 'enabled', 'reason': reason},
            )
    else:
        _infinia_capabilities(account)


def sync_embedded_funding_instructions(account):
    if account.provider != 'infinia':
        return
    raw = (account.provider_data or {}).get('latest') or {}
    instructions = raw.get('funding_instructions') or []
    if isinstance(instructions, dict):
        instructions = [instructions]
    for item in instructions:
        if not isinstance(item, dict):
            continue
        raw_kind = str(item.get('type') or '').lower()
        if raw_kind == 'crypto' or item.get('crypto_address'):
            kind = 'crypto_address'
        elif item.get('breb_key'):
            kind = 'breb_key'
        elif item.get('pix_key') or item.get('pix_key_brl'):
            kind = 'pix_key'
        elif raw_kind == 'qr' or item.get('qr_code'):
            kind = 'qr'
        else:
            kind = 'bank_details'
        resource_id = str(
            item.get('id')
            or item.get('reference')
            or f'embedded:{account.provider_account_id}:{kind}'
        )
        FundingInstruction.objects.update_or_create(
            financial_account=account,
            provider_resource_id=resource_id,
            defaults={
                'kind': kind,
                'status': 'active',
                'reusable': True,
                'display_value': str(
                    item.get('account_number')
                    or item.get('breb_key')
                    or item.get('crypto_address')
                    or item.get('pix_key')
                    or item.get('qr_code')
                    or item.get('address')
                    or item.get('value')
                    or ''
                ),
                'holder_display_name': account.provider_profile.identity_snapshot.get(
                    'full_name', ''
                ),
                'ownership_evidence_available': account.ownership_structure == 'provider_named',
                'instruction_data': item,
            },
        )


def provision_payment_account(
    *,
    confio_account,
    provider,
    identity,
    country,
    asset,
    ownership_structure,
    kyc_mode='',
    owner_payload=None,
    compliance_consent=False,
):
    provider = provider.strip().lower()
    country = country.strip().upper()
    asset = asset.strip().upper()
    if provider not in PROVIDER_ACCOUNT_SHAPES:
        raise PaymentAccountError('Unsupported provider')
    _require_provider_enabled(provider)
    expected_ownership, supported_pairs = PROVIDER_ACCOUNT_SHAPES[provider]
    if ownership_structure != expected_ownership:
        raise PaymentAccountError('Provider ownership structure mismatch')
    if (country, asset) not in supported_pairs:
        raise PaymentAccountError(
            f'{provider.title()} does not support the requested country/asset pair'
        )
    if provider == 'cobre' and confio_account.account_type != 'personal':
        raise PaymentAccountError('Cobre end-user Bre-B balances require a personal account')
    if provider == 'infinia':
        if kyc_mode != 'SELF_DECLARED':
            raise PaymentAccountError('Infinia requires SELF_DECLARED Didit onboarding')
        if not compliance_consent:
            raise PaymentAccountError(
                'Consent to share Didit compliance data with Infinia is required'
            )
    if identity.user_id != confio_account.user_id or identity.status != 'verified':
        raise PaymentAccountError('A verified identity belonging to the active account is required')
    context = context_from_identity(identity, account_country=country)
    enforce_and_record(
        confio_account=confio_account,
        provider=provider,
        scope='account_opening',
        context=context,
    )
    profile, _ = ProviderProfile.objects.get_or_create(
        confio_account=confio_account,
        provider=provider,
        defaults={
            'owner_type': 'business' if confio_account.account_type == 'business' else 'individual',
            'kyc_mode': kyc_mode,
            'identity_verification': identity,
            'identity_snapshot': identity_snapshot(identity),
            'provider_data': {
                'owner_payload': owner_payload or {},
                'compliance_consent': {
                    'granted': bool(compliance_consent),
                    'granted_at': timezone.now().isoformat() if compliance_consent else None,
                },
            },
        },
    )
    if provider == 'infinia' and profile.provider_owner_id and profile.kyc_mode != 'SELF_DECLARED':
        raise PaymentAccountError('Existing Infinia owner was not created from Didit SELF_DECLARED data')
    if not profile.provider_owner_id:
        provider_data = dict(profile.provider_data or {})
        if compliance_consent:
            provider_data['compliance_consent'] = {
                'granted': True,
                'granted_at': timezone.now().isoformat(),
            }
        profile.kyc_mode = kyc_mode
        profile.identity_verification = identity
        profile.identity_snapshot = identity_snapshot(identity)
        profile.provider_data = provider_data
        profile.save(update_fields=[
            'kyc_mode', 'identity_verification', 'identity_snapshot',
            'provider_data', 'updated_at',
        ])

    adapter = get_provider(provider)
    if profile.status != 'active':
        result = (
            adapter.sync_profile(profile)
            if profile.provider_owner_id
            else adapter.provision_profile(profile)
        )
        _apply_profile_result(profile, result)
    if profile.status != 'active':
        return profile, None

    account, _ = FinancialAccount.objects.get_or_create(
        provider_profile=profile,
        country=country,
        asset=asset,
        ownership_structure=ownership_structure,
    )
    if not account.provider_account_id:
        _apply_account_result(account, adapter.provision_account(account))
    else:
        _apply_account_result(account, adapter.sync_account(account))
    sync_capabilities(account)
    sync_embedded_funding_instructions(account)
    return profile, account


def create_funding_instruction(*, financial_account, kind, **kwargs):
    _require_provider_enabled(financial_account.provider)
    if financial_account.status != 'active':
        raise PaymentAccountError('Financial account is not active')
    if kind not in dict(FundingInstruction.KIND_CHOICES):
        raise PaymentAccountError('Unsupported funding instruction kind')
    if financial_account.provider == 'cobre':
        identity = financial_account.provider_profile.identity_verification
        if not identity or identity.status != 'verified':
            raise PaymentAccountError('Verified identity required')
        enforce_and_record(
            confio_account=financial_account.provider_profile.confio_account,
            provider='cobre',
            scope='funding_instruction',
            context=context_from_identity(identity, account_country=financial_account.country),
        )
    elif financial_account.provider == 'infinia':
        _apply_account_result(
            financial_account,
            get_provider('infinia').sync_account(financial_account),
        )
        sync_embedded_funding_instructions(financial_account)
    instruction = FundingInstruction.objects.filter(
        financial_account=financial_account,
        kind=kind,
        status__in=['pending', 'active'],
    ).order_by('created_at').first()
    if instruction and instruction.status == 'active':
        return instruction
    if financial_account.provider == 'infinia':
        raise PaymentAccountError(
            'The active Infinia account does not expose this funding instruction'
        )
    if not instruction:
        try:
            with transaction.atomic():
                instruction = FundingInstruction.objects.create(
                    financial_account=financial_account,
                    kind=kind,
                    status='pending',
                )
        except IntegrityError:
            instruction = FundingInstruction.objects.get(
                financial_account=financial_account,
                kind=kind,
                status__in=['pending', 'active'],
            )
    result = get_provider(financial_account.provider).create_funding_instruction(
        financial_account,
        kind=kind,
        alias=f'Confio {instruction.internal_id}',
        **kwargs,
    )
    instruction.provider_resource_id = result.resource_id
    instruction.status = result.status
    instruction.display_value = result.raw.get('key_value', '')
    instruction.holder_display_name = (
        financial_account.provider_profile.identity_snapshot.get('full_name', '')
    )
    instruction.ownership_evidence_available = False
    instruction.instruction_data = result.raw
    instruction.save(update_fields=[
        'provider_resource_id', 'status', 'display_value', 'holder_display_name',
        'ownership_evidence_available', 'instruction_data', 'updated_at',
    ])
    return instruction


def _require_capability(account, capability):
    row = AccountCapability.objects.filter(
        financial_account=account, capability=capability, status='enabled'
    ).first()
    if not row:
        raise PaymentAccountError(f'Account capability {capability} is not enabled')


def create_payout_destination(
    *, confio_account, provider, kind, country, asset, label, holder_name,
    holder_id_type='', holder_id_number='', details=None,
):
    provider = provider.strip().lower()
    country = country.strip().upper()
    asset = asset.strip().upper()
    details = details or {}
    if not isinstance(details, dict):
        raise PaymentAccountError('Destination details must be an object')
    if provider not in PROVIDER_ACCOUNT_SHAPES:
        raise PaymentAccountError('Unsupported provider')
    _require_provider_enabled(provider)
    if provider == 'cobre' and (kind != 'breb_key' or country != 'COL' or asset != 'COP'):
        raise PaymentAccountError('Cobre currently supports only Colombia Bre-B destinations')
    if kind == 'breb_key' and not details.get('key_value'):
        raise PaymentAccountError('Bre-B key value is required')
    if provider == 'infinia':
        _validate_infinia_destination(
            kind=kind, country=country, details=details
        )
    return PayoutDestination.objects.create(
        confio_account=confio_account,
        provider=provider,
        kind=kind,
        country=country,
        asset=asset,
        label=label,
        holder_name=holder_name,
        holder_id_type=holder_id_type,
        holder_id_number=holder_id_number,
        details=details,
    )


def provision_payout_destination(destination):
    if destination.status == 'active':
        return destination
    result = get_provider(destination.provider).provision_destination(destination)
    destination.provider_destination_id = result.resource_id or None
    destination.status = result.status
    destination.provider_data = result.raw
    destination.save(
        update_fields=['provider_destination_id', 'status', 'provider_data', 'updated_at']
    )
    return destination


@transaction.atomic
def create_money_operation(
    *,
    confio_account,
    provider,
    operation_type,
    source_asset,
    source_amount,
    target_asset='',
    source_account=None,
    destination_account=None,
    external_destination=None,
    kind=None,
    client_request_id=None,
):
    source_amount = Decimal(str(source_amount))
    if source_amount <= 0:
        raise PaymentAccountError('Amount must be positive')
    if source_account and source_account.provider_profile.confio_account_id != confio_account.id:
        raise PaymentAccountError('Source account does not belong to the active Confío account')
    if source_account and source_account.provider != provider:
        raise PaymentAccountError('Source account provider mismatch')
    if destination_account:
        if destination_account.provider_profile.confio_account_id != confio_account.id:
            raise PaymentAccountError(
                'Destination account does not belong to the active Confío account'
            )
        if destination_account.provider != provider:
            raise PaymentAccountError('Destination account provider mismatch')
    idempotency_key = (
        str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f'confio-payment:{confio_account.id}:{client_request_id}',
        ))
        if client_request_id
        else str(uuid.uuid4())
    )

    def existing_operation():
        existing = MoneyOperation.objects.filter(
            provider=provider, idempotency_key=idempotency_key
        ).first()
        if not existing:
            return None
        expected = (
            operation_type,
            source_account.pk if source_account else None,
            destination_account.pk if destination_account else None,
            source_asset.upper(),
            source_amount,
            (target_asset or '').upper(),
        )
        actual = (
            existing.operation_type,
            existing.source_account_id,
            existing.destination_account_id,
            existing.source_asset,
            existing.source_amount,
            existing.target_asset,
        )
        if actual != expected or existing.external_destination != (external_destination or {}):
            raise PaymentAccountError(
                'The request id was already used for different payment details'
            )
        return existing

    existing = existing_operation()
    if existing:
        return existing
    try:
        with transaction.atomic():
            flow = MoneyFlow.objects.create(
                confio_account=confio_account,
                kind=kind or ('withdraw' if operation_type == 'payout' else 'transfer'),
                source_asset=source_asset.upper(),
                source_amount=source_amount,
                target_asset=(target_asset or source_asset).upper(),
            )
            return MoneyOperation.objects.create(
                money_flow=flow,
                provider=provider,
                operation_type=operation_type,
                source_account=source_account,
                destination_account=destination_account,
                external_destination=external_destination or {},
                idempotency_key=idempotency_key,
                source_asset=source_asset.upper(),
                source_amount=source_amount,
                target_asset=(target_asset or '').upper(),
            )
    except IntegrityError:
        existing = existing_operation()
        if existing:
            return existing
        raise


def submit_money_operation(operation):
    with transaction.atomic():
        operation = MoneyOperation.objects.select_for_update(of=('self',)).select_related(
            'source_account', 'destination_account', 'money_flow'
        ).get(pk=operation.pk)
        if operation.status not in {'created', 'unknown'}:
            return operation
        if not operation.source_account or operation.source_account.status != 'active':
            raise PaymentAccountError('An active source account is required')
        if operation.operation_type == 'payout':
            _require_capability(operation.source_account, 'send_third_party')
        elif operation.operation_type in {'internal_transfer', 'conversion'}:
            _require_capability(operation.source_account, 'convert')
        operation.status = 'submitted'
        operation.submitted_at = operation.submitted_at or timezone.now()
        operation.save(update_fields=['status', 'submitted_at', 'updated_at'])
    adapter = get_provider(operation.provider)
    try:
        if operation.operation_type == 'payout':
            result = adapter.create_payout(operation)
        elif operation.operation_type in {'internal_transfer', 'conversion'}:
            result = adapter.create_transfer(operation)
        else:
            raise PaymentAccountError(f'Unsupported submitted operation {operation.operation_type}')
    except ProviderAPIError as exc:
        operation.status = 'unknown' if exc.retryable else 'failed'
        operation.failure_code = str(exc.status_code or 'provider_error')
        operation.failure_detail = str(exc)
        operation.provider_data = exc.payload or {}
        operation.save(
            update_fields=[
                'status', 'failure_code', 'failure_detail', 'provider_data', 'updated_at'
            ]
        )
        _sync_flow_status(operation.money_flow)
        if not exc.retryable:
            raise
        return operation
    except ProviderCapabilityError as exc:
        operation.status = 'failed'
        operation.failure_code = 'provider_capability_error'
        operation.failure_detail = str(exc)
        operation.save(
            update_fields=['status', 'failure_code', 'failure_detail', 'updated_at']
        )
        _sync_flow_status(operation.money_flow)
        raise PaymentAccountError(str(exc)) from exc
    return apply_operation_result(operation, result)


def create_and_submit_payout(
    *, confio_account, source_account, destination, amount, client_request_id=None
):
    _require_provider_enabled(source_account.provider)
    if destination.confio_account_id != confio_account.id:
        raise PaymentAccountError('Destination does not belong to the active Confío account')
    if destination.provider != source_account.provider:
        raise PaymentAccountError('Destination provider mismatch')
    if destination.asset != source_account.asset:
        raise PaymentAccountError('Destination asset must match the source account asset')
    identity = ProviderProfile.objects.get(
        confio_account=confio_account,
        provider=source_account.provider,
    ).identity_verification
    if not identity or identity.status != 'verified':
        raise PaymentAccountError('Verified identity required')
    enforce_and_record(
        confio_account=confio_account,
        provider=source_account.provider,
        scope='payout',
        context=context_from_identity(
            identity,
            account_country=source_account.country,
            destination_country=destination.country,
        ),
    )
    provision_payout_destination(destination)
    external_destination = {
        'destination_internal_id': str(destination.internal_id),
        'kind': destination.kind,
        'country': destination.country,
        'holder_name': destination.holder_name,
        'holder_id_type': destination.holder_id_type,
        'holder_id_number': destination.holder_id_number,
        'details': destination.details,
    }
    if source_account.provider == 'cobre':
        external_destination['provider_counterparty_id'] = destination.provider_destination_id
    else:
        external_destination['destination_account'] = destination.details
    operation = create_money_operation(
        confio_account=confio_account,
        provider=source_account.provider,
        operation_type='payout',
        source_asset=source_account.asset,
        source_amount=amount,
        source_account=source_account,
        external_destination=external_destination,
        kind='withdraw',
        client_request_id=client_request_id,
    )
    return submit_money_operation(operation)


def create_and_submit_transfer(
    *, confio_account, source_account, destination_account, amount, client_request_id=None
):
    _require_provider_enabled(source_account.provider)
    if source_account.pk == destination_account.pk:
        raise PaymentAccountError('Source and destination accounts must be different')
    if source_account.provider != destination_account.provider:
        raise PaymentAccountError('Transfers cannot cross provider boundaries')
    if source_account.status != 'active' or destination_account.status != 'active':
        raise PaymentAccountError('Both financial accounts must be active')
    if (
        source_account.provider_profile.confio_account_id != confio_account.id
        or destination_account.provider_profile.confio_account_id != confio_account.id
    ):
        raise PaymentAccountError('Both financial accounts must belong to the active account')
    identity = source_account.provider_profile.identity_verification
    if not identity or identity.status != 'verified':
        raise PaymentAccountError('Verified identity required')
    enforce_and_record(
        confio_account=confio_account,
        provider=source_account.provider,
        scope='conversion',
        context=context_from_identity(
            identity,
            account_country=source_account.country,
            destination_country=destination_account.country,
        ),
    )
    operation_type = (
        'internal_transfer'
        if source_account.asset == destination_account.asset
        else 'conversion'
    )
    operation = create_money_operation(
        confio_account=confio_account,
        provider=source_account.provider,
        operation_type=operation_type,
        source_asset=source_account.asset,
        source_amount=amount,
        target_asset=destination_account.asset,
        source_account=source_account,
        destination_account=destination_account,
        kind='transfer' if operation_type == 'internal_transfer' else 'convert',
        client_request_id=client_request_id,
    )
    return submit_money_operation(operation)


@transaction.atomic
def apply_operation_result(operation, result):
    operation = MoneyOperation.objects.select_for_update(of=('self',)).select_related(
        'money_flow'
    ).get(pk=operation.pk)
    if result.status != operation.status and result.status not in ALLOWED_OPERATION_TRANSITIONS.get(
        operation.status, set()
    ):
        operation.provider_status = result.provider_status
        operation.provider_data = result.raw
        operation.save(update_fields=['provider_status', 'provider_data', 'updated_at'])
        return operation
    operation.provider_operation_id = result.resource_id or operation.provider_operation_id
    operation.status = result.status
    operation.provider_status = result.provider_status
    operation.provider_data = result.raw
    for field, keys in {
        'target_amount': ('destination_amount', 'target_amount'),
        'provider_fee': ('fee', 'provider_fee'),
    }.items():
        for key in keys:
            value = result.raw.get(key) if isinstance(result.raw, dict) else None
            if value is not None:
                setattr(operation, field, Decimal(str(value)))
                break
    if result.status in {'succeeded', 'failed', 'reversed'}:
        operation.settled_at = timezone.now()
    operation.save(
        update_fields=[
            'provider_operation_id', 'status', 'provider_status', 'provider_data',
            'target_amount', 'provider_fee', 'settled_at', 'updated_at',
        ]
    )
    _sync_flow_status(operation.money_flow)
    return operation


def _sync_flow_status(flow):
    if not flow:
        return
    operations = list(flow.operations.all())
    statuses = {operation.status for operation in operations}
    if statuses and statuses <= {'succeeded'}:
        flow.status, flow.completed_at = 'succeeded', timezone.now()
    elif 'reversed' in statuses:
        flow.status, flow.completed_at = 'reversed', timezone.now()
    elif 'failed' in statuses:
        flow.status, flow.completed_at = 'failed', timezone.now()
    elif 'needs_review' in statuses:
        flow.status = 'needs_review'
    else:
        flow.status = 'processing'
    if operations:
        flow.provider_cost = sum(
            (operation.provider_fee for operation in operations), Decimal('0')
        )
        final_amount = next(
            (
                operation.target_amount
                for operation in reversed(operations)
                if operation.target_amount is not None
            ),
            None,
        )
        if final_amount is not None:
            flow.target_amount = final_amount
    flow.save(update_fields=[
        'status', 'completed_at', 'provider_cost',
        'target_amount', 'updated_at',
    ])
