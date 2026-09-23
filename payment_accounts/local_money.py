"""Provider-neutral local money rails for Enviar/Recibir.

The app picks a consumer rail (Pix, Bre-B, CLABE, CVU, QR) and never names a
provider; Infinia serves all of them today. Nothing here moves money: payouts
and conversions stay inside the owner-authorized InfiniaJourney. This module
answers "can I use this rail", opens the accounts a rail needs, resolves and
verifies a recipient, prices a transfer, reports the monthly limit, and takes
enhanced-due-diligence (EDD) requests to raise it.
"""
import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal, InvalidOperation

from django.conf import settings
from django.db.models import Q, Sum
from django.utils import timezone

from .clients import InfiniaClient, ProviderAPIError
from .eligibility import EligibilityPolicyNotConfigured, context_from_identity, evaluate_active_policy
from .models import FinancialAccount, InfiniaJourney, PayoutDestination, ProviderProfile
from .providers.common import iso_alpha2
from .services import PaymentAccountError, create_payout_destination, provision_payment_account

FIAT_CENT = Decimal('0.01')
USDC_UNIT = Decimal('0.000001')


@dataclass(frozen=True)
class Method:
    id: str
    direction: str
    country: str
    iso2: str
    asset: str
    title: str
    subtitle: str
    kind: str = ''
    destination_type: str = ''
    field: str = ''
    instruction_kind: str = ''
    constants: tuple = ()


METHODS = {m.id: m for m in (
    Method('br_pix', 'send', 'BRA', 'BR', 'BRL', 'Pix', 'Chave Pix: CPF, celular, e-mail o aleatoria',
           kind='bank_account', destination_type='CHAVE PIX', field='chavePix'),
    Method('br_qr', 'send', 'BRA', 'BR', 'BRL', 'QR Pix', 'Escanea o importa un QR Pix sin monto fijo',
           kind='qr', destination_type='BR_CODE', field='brCode'),
    Method('co_breb', 'send', 'COL', 'CO', 'COP', 'Llave Bre-B', 'Nequi, Bancolombia, Daviplata y más',
           kind='breb_key', destination_type='BREB_KEY', field='brebKey'),
    # Infinia requires a CLABE reference: it is the SPEI concept the recipient sees.
    Method('mx_clabe', 'send', 'MEX', 'MX', 'MXN', 'CLABE', 'Transferencia SPEI a cualquier banco',
           kind='bank_account', destination_type='CLABE', field='clabe', constants=(('reference', 'Confio'),)),
    # A CVU and a CBU share one 22-digit format and Infinia's CBU payout type.
    Method('ar_cvu', 'send', 'ARG', 'AR', 'ARS', 'CVU o CBU', 'Mercado Pago, Ualá, Naranja X y bancos',
           kind='bank_account', destination_type='CBU', field='cbu'),
    Method('ar_qr', 'send', 'ARG', 'AR', 'ARS', 'QR', 'QR interoperable de comercios y billeteras',
           kind='qr', destination_type='QR_CODE', field='qrCode'),
    Method('br_pix_receive', 'receive', 'BRA', 'BR', 'BRL', 'Pix', 'Recibe reales con tus datos Pix',
           instruction_kind='pix_key'),
    Method('co_breb_receive', 'receive', 'COL', 'CO', 'COP', 'Llave Bre-B', 'Tu propia llave para recibir pesos',
           instruction_kind='breb_key'),
    Method('mx_clabe_receive', 'receive', 'MEX', 'MX', 'MXN', 'CLABE', 'Tu propia CLABE para recibir pesos',
           instruction_kind='bank_details'),
    Method('ar_cvu_receive', 'receive', 'ARG', 'AR', 'ARS', 'CVU', 'Tu propio CVU para recibir pesos',
           instruction_kind='bank_details'),
)}


def get_method(method_id, direction=None):
    method = METHODS.get(str(method_id or ''))
    if not method or (direction and method.direction != direction):
        raise PaymentAccountError('Este medio no está disponible.')
    return method


# ---------------------------------------------------------------- identifiers

def _digits(value):
    return re.sub(r'[\s.\-/]', '', value)


def clabe_valid(value):
    if not re.fullmatch(r'\d{18}', value):
        return False
    total = sum((int(d) * w) % 10 for d, w in zip(value[:17], (3, 7, 1) * 6))
    return (10 - total % 10) % 10 == int(value[17])


def cbu_valid(value):
    if not re.fullmatch(r'\d{22}', value):
        return False

    def check(block, weights):
        return (10 - sum(int(d) * w for d, w in zip(block, weights)) % 10) % 10
    return (check(value[:7], (7, 1, 3, 9, 7, 1, 3)) == int(value[7])
            and check(value[8:21], (3, 9, 7, 1, 3, 9, 7, 1, 3, 9, 7, 1, 3)) == int(value[21]))


def emv_fields(payload):
    """Top-level EMVCo TLV map, or None when the payload is not well formed."""
    fields, index = {}, 0
    while index < len(payload):
        tag, size = payload[index:index + 2], payload[index + 2:index + 4]
        if not re.fullmatch(r'[0-9]{2}', tag) or tag in fields or not re.fullmatch(r'[0-9]{2}', size):
            return None
        value = payload[index + 4:index + 4 + int(size)]
        if len(value) != int(size):
            return None
        fields[tag] = value
        index += 4 + int(size)
    return fields


def emv_crc(data):
    crc = 0xFFFF
    for byte in data.encode('utf-8'):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return f'{crc:04X}'


_EVP = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')


def _pix_key(value):
    if _EVP.fullmatch(value):
        return value.lower()
    if '@' in value:
        if re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', value) and len(value) <= 77:
            return value
    elif value.startswith('+'):
        if re.fullmatch(r'\+55\d{10,11}', value):
            return value
    elif re.fullmatch(r'\d{11}|\d{14}', _digits(value)):
        return _digits(value)
    raise PaymentAccountError(
        'Ingresa una chave Pix válida: CPF, CNPJ, celular con +55, e-mail o clave aleatoria.'
    )


def normalize_value(method, raw):
    value = str(raw or '').strip()
    if not value:
        raise PaymentAccountError('Ingresa los datos de quien recibe.')
    if method.id == 'mx_clabe':
        value = _digits(value)
        if not clabe_valid(value):
            raise PaymentAccountError('Revisa la CLABE: son 18 dígitos.')
    elif method.id == 'ar_cvu':
        value = _digits(value)
        if not cbu_valid(value):
            raise PaymentAccountError('Revisa el CVU o CBU: son 22 dígitos.')
    elif method.id == 'co_breb':
        from ramps.breb import validate_breb_key
        try:
            value = validate_breb_key(account_number=value, account_type='llave', country_code='CO')
        except ValueError as exc:
            raise PaymentAccountError(str(exc)) from exc
    elif method.id == 'br_pix':
        value = _pix_key(value)
    elif method.kind == 'qr':
        if len(value) > 4096:
            raise PaymentAccountError('Este código QR es demasiado largo.')
        fields = emv_fields(value)
        if (not fields or fields.get('00') != '01' or fields.get('58') != method.iso2
                or not value[-8:].startswith('6304')
                or value[-4:].upper() != emv_crc(value[:-4])):
            raise PaymentAccountError('Este código no es un QR de pago válido para este país.')
        if method.id == 'br_qr':
            templates = [emv_fields(v) or {} for k, v in fields.items() if k.isdigit() and 26 <= int(k) <= 51]
            pix = [t for t in templates if t.get('00', '').lower() == 'br.gov.bcb.pix']
            if fields.get('53') != '986' or len(pix) != 1:
                raise PaymentAccountError('Este código no es un QR Pix en reales.')
            if fields.get('01') == '12' or '25' in pix[0]:
                raise PaymentAccountError('Por ahora solo puedes pagar QR Pix estáticos y sin monto.')
            key = pix[0].get('01', '')
            # Validate the very key sent inside the untouched QR. Do not
            # verify a cleaned CPF/CNPJ while paying a different raw value.
            if _pix_key(key) != key and not _EVP.fullmatch(key):
                raise PaymentAccountError('Este QR contiene una chave Pix con formato inválido.')
        # The journey is dollar-driven, so an exact peso amount cannot be
        # guaranteed; a fixed-amount QR would be underpaid or rejected.
        if '54' in fields:
            raise PaymentAccountError('Este QR tiene un monto fijo. Por ahora solo puedes pagar QR sin monto.')
    return value


# --------------------------------------------------------------- availability

def _flags_enabled():
    return bool(getattr(settings, 'INFINIA_PAYMENT_ACCOUNTS_ENABLED', False)
                and getattr(settings, 'INFINIA_JOURNEYS_ENABLED', False))


def _enabled_method_ids():
    configured = getattr(settings, 'LOCAL_MONEY_METHODS', None)
    return set(METHODS) if configured is None else set(configured)


def method_status(identity, method):
    """(status, reason) from flags and verified KYC — never from phone country."""
    if not _flags_enabled() or method.id not in _enabled_method_ids():
        return 'unavailable', 'not_enabled'
    if identity is None:
        return 'needs_verification', 'identity_required'
    destination = method.country if method.direction == 'send' else 'XXX'
    # The same scopes provisioning and InfiniaJourney.validate_accounts enforce,
    # so a rail shown as live cannot fail on a policy the user never saw.
    checks = (
        ('account_opening', method.country, ''), ('account_opening', 'XXX', ''),
        ('conversion', method.country, destination), ('payout', method.country, destination),
    )
    for scope, account_country, destination_country in checks:
        try:
            result = evaluate_active_policy(provider='infinia', scope=scope, context=context_from_identity(
                identity, account_country=account_country, destination_country=destination_country))
        except EligibilityPolicyNotConfigured:
            return 'unavailable', 'policy_not_configured'
        if not result.allowed:
            return 'unavailable', result.reason_code or result.decision
    return 'live', ''


# Any country's national ID (DNI/cédula) or passport opens any local account,
# except Venezuelan documents (product rule 2026-09-14; supersedes the
# per-country table of Infinia's Required Documents page). Brazil also keeps
# the CNH. Nationality is still decided by eligibility, not by the document.
LOCAL_ACCOUNT_COUNTRIES = {'COL', 'MEX', 'BRA', 'ARG'}
BLOCKED_DOCUMENT_COUNTRIES = {'VEN'}


def accepts_identity(identity, country):
    if identity is None:
        return False
    if country not in LOCAL_ACCOUNT_COUNTRIES:
        return True  # the dollar transit account follows the owner's document
    if identity.document_issuing_country in BLOCKED_DOCUMENT_COUNTRIES:
        return False
    if identity.document_type in ('national_id', 'passport'):
        return True
    return identity.document_type == 'drivers_license' and identity.document_issuing_country == country == 'BRA'


def document_requirement(country):
    """What to ask for when none of the person's documents fits (Didit codes)."""
    return {'id_country': '', 'document_types': ['ID', 'P']}


def _verified_documents(owner):
    # Every verified personal document, primary first: all_documents, never
    # the default manager, which hides additional documents on purpose.
    from django.db.models import Q
    from security.models import IdentityVerification
    # Null-safe: .exclude() on a JSON key value also drops rows missing the key.
    return list(
        IdentityVerification.all_documents.filter(user=owner.user, status='verified')
        .filter(risk_factors__provider='didit')
        .filter(Q(risk_factors__account_type__isnull=True) | ~Q(risk_factors__account_type='business'))
        .order_by('is_additional_document', '-verified_at', '-updated_at')
    )


def document_for(owner, country):
    """The document the provider owner uses (or would use) for this country.

    One Infinia account owner holds every country account, and its identity is
    fixed when it is created; a country whose rules that document does not
    satisfy cannot silently switch to another one.
    """
    profile = ProviderProfile.objects.filter(confio_account=owner, provider='infinia').select_related(
        'identity_verification').first()
    # Pinned once a provider owner exists, or while a creation attempt may still
    # have landed (pending). A profile that failed or was rejected before any
    # owner existed pins nothing: provisioning re-reads the identity then.
    if profile and profile.identity_verification_id and (
            profile.provider_owner_id or profile.status not in ('failed', 'rejected')):
        return profile.identity_verification if accepts_identity(profile.identity_verification, country) else None
    return next((doc for doc in _verified_documents(owner) if accepts_identity(doc, country)), None)


def rail_status(owner, primary, method):
    """(status, reason, document requirement) for this person and rail.

    Eligibility first — nationality is the person's, so no document fixes a
    blocked one and nobody is asked for a passport only to be refused — then
    whether a verified document satisfies the account country.
    """
    personal = owner.account_type != 'business'
    document = document_for(owner, method.country) if personal else primary
    anchor = primary or document or (next(iter(_verified_documents(owner)), None) if personal else None)
    status, reason = method_status(anchor, method)
    if status != 'live':
        return status, reason, None
    if document is None:
        return 'needs_document', 'document_not_accepted', document_requirement(method.country)
    if document is not anchor:
        status, reason = method_status(document, method)
    return status, reason, None


def require_rail(owner, primary, method):
    status, _, _ = rail_status(owner, primary, method)
    if status == 'needs_verification':
        raise PaymentAccountError('Verifica tu identidad para usar transferencias locales.')
    if status == 'needs_document':
        raise PaymentAccountError('Para este medio necesitamos otro documento de identidad.')
    if status != 'live':
        raise PaymentAccountError('Este medio aún no está disponible para tu cuenta.')


def require_live(identity, method):
    status, _ = method_status(identity, method)
    if status == 'needs_verification':
        raise PaymentAccountError('Verifica tu identidad para usar transferencias locales.')
    if status != 'live':
        raise PaymentAccountError('Este medio aún no está disponible para tu cuenta.')


def _owned(owner):
    return FinancialAccount.objects.filter(
        provider_profile__confio_account=owner, provider_profile__provider='infinia',
        ownership_structure='provider_named',
    ).select_related('provider_profile')


def accounts_for(owner, country, asset):
    accounts = _owned(owner)
    return (accounts.filter(country=country, asset=asset).first(),
            accounts.filter(country='XXX', asset='USDC_POL').first())


def pair_status(local, crypto):
    if not local or not crypto:
        return 'none'
    statuses = {local.status, crypto.status}
    if statuses == {'active'}:
        return 'active'
    for terminal in ('rejected', 'suspended', 'closed', 'failed'):
        if terminal in statuses:
            return terminal
    return 'provisioning'


def _public_pair_status(owner, method):
    from .activation import public_status, PAID_STATES
    status = public_status(owner, method.country, method.asset)
    if status in PAID_STATES:
        return pair_status(*accounts_for(owner, method.country, method.asset))
    return 'awaiting_payment' if status == 'payment_pending' else status


def methods(owner, identity, direction):
    rows = []
    for method in METHODS.values():
        if method.direction != direction:
            continue
        status, reason, requirement = rail_status(owner, identity, method)
        rows.append({'method': method, 'status': status, 'reason': reason, 'requirement': requirement,
                     'account_status': _public_pair_status(owner, method)})
    return rows


def activation_preflight(owner, identity, method_id):
    """Open (or re-sync) the dollar and local accounts a rail needs. Idempotent."""
    method = get_method(method_id)
    require_rail(owner, identity, method)
    # The document the provider owner is opened with: for a person, the one
    # this country accepts (a passport can serve a Colombian account; an
    # additional document never replaces the primary one anywhere else).
    document = document_for(owner, method.country) if owner.account_type != 'business' else identity
    if owner.account_type != 'business':
        # The owner address is self-declared, exactly as for Koywe; check it
        # before any provider account (and its fee) is created.
        from ramps.schema import _build_effective_ramp_address_snapshot, _is_ramp_address_complete
        if not _is_ramp_address_complete(_build_effective_ramp_address_snapshot(owner.user)):
            raise PaymentAccountError('Completa tu dirección para abrir tu cuenta local.')
    return method, document


def activate(owner, identity, method_id):
    method, document = activation_preflight(owner, identity, method_id)
    from .activation import require_opening_intent
    require_opening_intent(owner, method.country, method.asset)
    # Sharing verification data with the regulated payment processor is the
    # precondition of the service and is disclosed in the Privacy Policy
    # ("Procesar recargas, retiros y otras integraciones con proveedores de
    # pago"). A per-screen checkbox added fear, not information (product
    # decision 2026-09-14), so opening a rail records that basis instead.
    common = dict(confio_account=owner, provider='infinia', identity=document,
                  ownership_structure='provider_named', kyc_mode=getattr(settings, 'INFINIA_KYC_MODE', ''),
                  compliance_consent=True)
    _, crypto = provision_payment_account(country='XXX', asset='USDC_POL', **common)
    if not crypto:
        return 'provisioning'
    if crypto.status != 'active':
        return crypto.status if crypto.status in {'rejected', 'failed', 'suspended', 'closed'} else 'provisioning'
    _, local = provision_payment_account(country=method.country, asset=method.asset, **common)
    return pair_status(local, crypto)


def receive_instruction_kinds(method):
    return ('pix_key', 'qr') if method.id == 'br_pix_receive' else (method.instruction_kind,)


def receive_instructions(account, method):
    return account.funding_instructions.filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()),
        kind__in=receive_instruction_kinds(method), status='active',
    ).exclude(display_value='').order_by('-updated_at', '-pk')


def receive_account(owner, method_id):
    method = get_method(method_id, 'receive')
    local, crypto = accounts_for(owner, method.country, method.asset)
    instruction, capabilities = None, {}
    from .activation import usable
    public_status = _public_pair_status(owner, method)
    if not local or not usable(local):
        local, crypto = None, None
    if local:
        instruction = receive_instructions(local, method).first()
        from .payin_admission import receiving_capabilities
        capabilities = receiving_capabilities(local)
    return {
        'method': method, 'status': public_status, 'local': local, 'crypto': crypto,
        'instruction_kind': instruction.kind if instruction else method.instruction_kind,
        'value': instruction.display_value if instruction else '',
        'holder_name': instruction.holder_display_name if instruction else '',
        'institution': str(((instruction.instruction_data or {}) if instruction else {}).get('bank_name') or ''),
        'receive_same_name': capabilities.get('receive_same_name', ''),
        'receive_third_party': capabilities.get('receive_third_party', ''),
    }


# ---------------------------------------------------------------- recipients

VERIFIED, PENDING, UNVERIFIED, NOT_FOUND = 'verified', 'pending', 'unverified', 'not_found'
_VALIDATION_TYPES = {
    'br_pix': ('PIX_KEY', 'pixKey'), 'co_breb': ('BREB_KEY', 'brebKey'),
    'mx_clabe': ('CLABE', 'clabe'), 'ar_qr': ('QR_CODE', 'qrCode'),
}


def _validation_request(method, value):
    if method.id == 'br_qr':
        # Static Pix QR embeds the registered key; the live validation API
        # accepts PIX_KEY, not a BR_CODE/QR_CODE validation request.
        fields = emv_fields(value) or {}
        for tag, raw in fields.items():
            if tag.isdigit() and 26 <= int(tag) <= 51:
                nested = emv_fields(raw) or {}
                if nested.get('00', '').lower() == 'br.gov.bcb.pix':
                    return {'country': 'BR', 'account': {'dataType': 'PIX_KEY', 'pixKey': _pix_key(nested.get('01', ''))}}
        raise PaymentAccountError('Este código no contiene una chave Pix válida.')
    if method.id == 'ar_cvu':
        data_type, field = ('CVU', 'cvu') if value.startswith('000') else ('CBU', 'cbu')
    else:
        data_type, field = _VALIDATION_TYPES[method.id]
    return {'country': method.iso2, 'account': {'dataType': data_type, field: value}}


def _find_name(node, depth=0):
    """First holder or merchant name in a provider result, owners first."""
    if depth > 3 or not isinstance(node, dict):
        return ''
    owners = node.get('owners')
    if isinstance(owners, list):
        for item in owners:
            if isinstance(item, dict) and str(item.get('name') or '').strip():
                return str(item['name']).strip()
    for key in ('accountHolderName', 'ownerName', 'merchantName', 'name'):
        if isinstance(node.get(key), str) and node[key].strip():
            return node[key].strip()
    for value in node.values():
        found = _find_name(value, depth + 1)
        if found:
            return found
    return ''


def _mask(value):
    value = str(value or '')
    return f'•••• {value[-4:]}' if len(value) > 4 else value


def summarize_validation(response):
    response = response if isinstance(response, dict) else {}
    data = response.get('countryData') if isinstance(response.get('countryData'), dict) else {}
    account = data.get('account') if isinstance(data.get('account'), dict) else {}
    owners = data.get('owners') if isinstance(data.get('owners'), list) else []
    first = owners[0] if owners and isinstance(owners[0], dict) else {}
    return {
        'id': str(response.get('id') or ''),
        'status': str(response.get('status') or '').upper(),
        'holder_name': _find_name(data)[:255],
        'holder_document': _mask(first.get('documentNumber')),
        'institution': str(account.get('bankName') or '')[:120],
        'checked_at': timezone.now().isoformat(),
    }


def verification_state(validation):
    status = (validation or {}).get('status')
    if status == 'DISABLED':
        return 'not_checked'
    if status == 'SUCCESSFUL' and validation.get('holder_name'):
        return VERIFIED
    if status == 'IN_PROGRESS':
        return PENDING
    if status == 'ERROR':
        return NOT_FOUND
    # TEMPORARY_FAILURE, found-without-a-name, or a check we could not run:
    # the app must ask for an explicit confirmation, never assume a match.
    return UNVERIFIED


def _label(method, value, validation):
    if method.kind == 'qr':
        # Merchant text comes from the QR itself, not an owner lookup. Include
        # a stable reference so two saved codes with the same name differ.
        fields = emv_fields(value) or {}
        name = validation.get('holder_name') if verification_state(validation) == VERIFIED else fields.get('59')
        name = ' '.join(str(name or 'Código de pago').split())[:60]
        reference = hashlib.sha256(value.encode('utf-8')).hexdigest()[:10].upper()
        return f'QR · {name} · {reference}'
    # The account identifier is the recipient's primary identity when paid
    # holder lookups are off. Keep it visible for the final send review.
    return f'{method.title} · {value}'


def _start_check(destination):
    """Claim the next check of this destination, under its lock, before the
    provider is asked: only the latest claimed check may record its answer."""
    import uuid
    from django.db import transaction
    token = uuid.uuid4().hex
    with transaction.atomic():
        row = PayoutDestination.objects.select_for_update().get(pk=destination.pk)
        row.provider_data = {**(row.provider_data or {}), 'check': token}
        row.save(update_fields=['provider_data', 'updated_at'])
    return token


def _apply_validation(destination, method, value, validation, *, answers=None, check=None):
    """Record a check's answer on the locked, re-read destination, never over a
    newer one (the key may now belong to someone else): a poll (`answers` = the
    validation id it polled) lands only while that validation is current, a
    fresh check (`check` = its claim) only while no later check was claimed."""
    from django.db import transaction
    with transaction.atomic():
        destination = PayoutDestination.objects.select_for_update().get(pk=destination.pk)
        data = destination.provider_data or {}
        if answers is not None and (data.get('validation') or {}).get('id') != answers:
            return destination
        if check is not None and data.get('check') != check:
            return destination
        destination.holder_name = validation['holder_name'] if verification_state(validation) == VERIFIED else ''
        destination.label = _label(method, value, validation)[:100]
        destination.provider_data = {**(destination.provider_data or {}), 'method_id': method.id,
                                     'validation': validation}
        destination.save(update_fields=['holder_name', 'label', 'provider_data', 'updated_at'])
    return destination


def checked_recently(validation):
    """A verified holder is trusted for a limited time: a payment key can be
    re-registered to someone else (LOCAL_MONEY_RECIPIENT_CHECK_TTL_HOURS)."""
    hours = getattr(settings, 'LOCAL_MONEY_RECIPIENT_CHECK_TTL_HOURS', 24)
    try:
        checked = datetime.fromisoformat(str((validation or {}).get('checked_at') or ''))
    except ValueError:
        return False
    if timezone.is_naive(checked):
        return False
    return timezone.now() - checked < timedelta(hours=hours)


def _current_verified(destination):
    validation = (destination.provider_data or {}).get('validation')
    return verification_state(validation) == VERIFIED and checked_recently(validation)


def _validate(method, value, client):
    if not getattr(settings, 'INFINIA_ACCOUNT_VALIDATION_ENABLED', False):
        return {'id': '', 'status': 'DISABLED', 'holder_name': '', 'holder_document': '',
                'institution': '', 'checked_at': timezone.now().isoformat()}
    try:
        return summarize_validation(
            (client or InfiniaClient()).create_bank_account_validation(_validation_request(method, value)))
    except ProviderAPIError:
        return {'id': '', 'status': 'TEMPORARY_FAILURE', 'holder_name': '', 'holder_document': '',
                'institution': '', 'checked_at': timezone.now().isoformat()}


def resolve_destination(owner, method_id, raw_value, *, client=None):
    from django.db import transaction
    method = get_method(method_id, 'send')
    value = normalize_value(method, raw_value)
    details = {'type': method.destination_type, method.field: value, **dict(method.constants)}
    with transaction.atomic():
        # One destination per owner and key, found or created under the owner's
        # lock, with its check claimed before the provider is asked: overlapping
        # first lookups share one row and only the latest check records its answer.
        # A new row stays out of the saved list until its answer lands.
        type(owner).objects.select_for_update().filter(pk=owner.pk).first()
        destination = PayoutDestination.objects.filter(
            confio_account=owner, provider='infinia', kind=method.kind, country=method.country, details=details,
        ).order_by('-created_at').first()
        if destination and _current_verified(destination):
            return destination
        if destination is None:
            destination = create_payout_destination(
                confio_account=owner, provider='infinia', kind=method.kind, country=method.country,
                asset=method.asset, label=_label(method, value, {})[:100], holder_name='', details=details)
        check = _start_check(destination)
    validation = _validate(method, value, client)
    return _apply_validation(destination, method, value, validation, check=check)


def refresh_destination(destination, *, client=None):
    data = destination.provider_data or {}
    validation = data.get('validation') or {}
    method = METHODS.get(data.get('method_id'))
    if not method or verification_state(validation) != PENDING or not validation.get('id'):
        return destination
    value = destination.details.get(method.field, '')
    if not getattr(settings, 'INFINIA_ACCOUNT_VALIDATION_ENABLED', False):
        check = _start_check(destination)
        return _apply_validation(destination, method, value, _validate(method, value, client), check=check)
    if not checked_recently(validation):
        # An abandoned check answers about the holder back then, not today.
        check = _start_check(destination)
        return _apply_validation(destination, method, value, _validate(method, value, client), check=check)
    try:
        result = summarize_validation((client or InfiniaClient()).get_bank_account_validation(validation['id']))
    except ProviderAPIError:
        return destination
    # The answer is about the moment the check started; the TTL counts from there.
    result['checked_at'] = validation.get('checked_at') or result['checked_at']
    return _apply_validation(destination, method, value, result, answers=validation['id'])


def recheck_destination(destination, *, client=None):
    """Before reusing a saved recipient: a check older than the TTL (or one
    that could not run) is done again, so a re-registered key shows its new
    holder instead of the old verified name."""
    data = destination.provider_data or {}
    method = METHODS.get(data.get('method_id'))
    if not method or _current_verified(destination):
        return destination
    if verification_state(data.get('validation')) == PENDING:
        return refresh_destination(destination, client=client)
    value = destination.details.get(method.field, '')
    check = _start_check(destination)
    return _apply_validation(destination, method, value, _validate(method, value, client), check=check)


def require_current_destination(destination):
    """Server-side guard for a new send: a holder verified long ago is checked again first."""
    validation = (destination.provider_data or {}).get('validation')
    if verification_state(validation) == VERIFIED and not checked_recently(validation):
        raise PaymentAccountError('Revisa de nuevo a quien recibe antes de enviar.')


def destination_view(destination):
    data = destination.provider_data or {}
    validation = data.get('validation') or {}
    state = verification_state(validation)
    method = METHODS.get(data.get('method_id'))
    label = _label(method, destination.details.get(method.field, ''), validation) if method else destination.label
    return {
        'id': destination.internal_id, 'method_id': str(data.get('method_id') or ''), 'label': label,
        'holder_name': validation.get('holder_name', '') if state == VERIFIED else '',
        'holder_document': validation.get('holder_document', '') if state == VERIFIED else '',
        'institution': validation.get('institution', ''), 'verification': state,
        'country': iso_alpha2(destination.country), 'asset': destination.asset,
    }


def saved_destinations(owner, method_id):
    rows = PayoutDestination.objects.filter(
        confio_account=owner, provider='infinia', provider_data__method_id=get_method(method_id, 'send').id,
    ).order_by('-created_at')[:10]
    return [row for row in rows if verification_state((row.provider_data or {}).get('validation')) != NOT_FOUND]


# --------------------------------------------------------------------- quotes

def _tolerance(name, default_bps):
    bps = Decimal(str(getattr(settings, name, default_bps)))
    if not bps.is_finite() or bps < 0 or bps >= 10000:
        raise PaymentAccountError('Invalid quote tolerance')
    return bps / Decimal(10000)


def _active_pair(owner, country, asset):
    local, crypto = accounts_for(owner, country, asset)
    if pair_status(local, crypto) != 'active':
        raise PaymentAccountError('Tu cuenta local todavía no está activa.')
    from .activation import require_paid
    require_paid(owner, country, asset)
    return local, crypto


def _quote(client, source, target, amount):
    from .infinia_journeys import provider_number
    response = client.create_transfer_quote({
        # Estimates never execute: a fresh external id keeps them out of any
        # journey's idempotency space.
        'external_id': f'confio-estimate-{uuid.uuid4()}',
        'source_account_id': source.provider_account_id, 'target_account_id': target.provider_account_id,
        # Use the provider's default expiry. An explicit lock duration requires
        # separately configured LONGER_QUOTE_TIME commercial terms.
        'source_amount': provider_number(amount),
    })
    try:
        target_amount = Decimal(str(response['target_amount']))
        if response.get('status') != 'ACTIVE' or not target_amount.is_finite() or target_amount <= 0:
            raise ValueError('inactive quote')
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise PaymentAccountError('No pudimos cotizar esta transferencia. Intenta de nuevo.') from exc
    return target_amount, str(response.get('expire_at') or '')


def _positive(value, quantum):
    try:
        amount = Decimal(str(value)).quantize(quantum, rounding=ROUND_DOWN)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaymentAccountError('Ingresa un monto válido.') from exc
    if not amount.is_finite() or amount <= 0:
        raise PaymentAccountError('Ingresa un monto válido.')
    return amount


def payout_quote(owner, destination, *, amount=None, bridge=None, client=None):
    """Estimate for a send. With a prepared bridge, price exactly what will land.

    The minimum is the owner's authorization for the journey's fresh FX quote;
    it is server-derived so the user never has to type one.
    """
    from .infinia_journeys import fx_source_amount
    local, crypto = _active_pair(owner, destination.country, destination.asset)
    if bridge is not None:
        if (bridge.quote.confio_account_id != owner.pk
                or bridge.quote.source_token_id != 'BSC:USDT'
                or bridge.quote.funding_instruction.financial_account_id != crypto.pk):
            raise PaymentAccountError('Este envío no corresponde a tu cuenta.')
        source = (Decimal(int(bridge.amount_out_min)) / Decimal(10 ** 6)).quantize(USDC_UNIT, rounding=ROUND_DOWN)
        expected_source = (Decimal(int(bridge.amount_out)) / Decimal(10 ** 6)).quantize(USDC_UNIT, rounding=ROUND_DOWN)
        spend = bridge.quote.money_flow.source_amount
    else:
        # The typed amount is the user's total budget, not the USDC principal.
        # Price the post-redemption USDT through the same bridge used at review.
        from .bridge import net_funding_units, executable_bridge_routes, bridge_route_minimum, exceeds_bridge_cap
        from .allbridge_next import to_units
        from .bridge_routing import quote_routes
        from .bridge import verified_destination
        from .models import FundingInstruction
        total = _positive(amount, USDC_UNIT)
        if exceeds_bridge_cap(total):
            raise PaymentAccountError('Amount exceeds the configured bridge limit')
        units = net_funding_units(owner, int(to_units(total, 'BSC:USDT')))
        instruction = FundingInstruction.objects.filter(financial_account=crypto,
            kind='crypto_address', status='active').first()
        if instruction is None:
            raise PaymentAccountError('An active crypto funding instruction is required')
        recipient = verified_destination(instruction, owner)
        routes = executable_bridge_routes(quote_routes('BSC:USDT', 'POL:USDC', units,
                                                       owner.bsc_address, recipient))
        route = routes[0]
        source = Decimal(bridge_route_minimum(route)) / Decimal(10 ** 6)
        expected_source = Decimal(int(route['amountOut'])) / Decimal(10 ** 6)
        spend = total
    source = fx_source_amount(source)
    target, expires = _quote(client or InfiniaClient(), crypto, local, source)
    minimum = (target * (1 - _tolerance('LOCAL_MONEY_FX_TOLERANCE_BPS', 100))).quantize(FIAT_CENT, rounding=ROUND_DOWN)
    # Relay's tolerance is amount-aware, so the gap between what should land and
    # the minimum we authorize widens on small sends. Show both rather than
    # blocking the send: target_amount is already priced off the minimum.
    expected_target = (target * expected_source / source).quantize(FIAT_CENT, rounding=ROUND_DOWN)
    cost = ((spend - expected_source) / spend * 100).quantize(FIAT_CENT, rounding=ROUND_UP)
    return {'source_amount': source, 'target_amount': target, 'minimum_target': minimum,
            'expected_source_amount': expected_source, 'expected_target': expected_target,
            'total_cost_percent': cost,
            'rate': (target / spend).quantize(Decimal('0.0001')),
            'asset': local.asset, 'expires_at': expires}


def deposit_quote(owner, credit, *, client=None):
    """Estimate for converting a received deposit straight to the user's wallet."""
    local = credit.financial_account
    if (local.provider_profile.confio_account_id != owner.pk or credit.provider != 'infinia'
            or credit.direction != 'credit'):
        raise PaymentAccountError('Este depósito no corresponde a tu cuenta.')
    from .payin_admission import decision, is_external_fiat_credit
    if is_external_fiat_credit(credit) and not decision(credit)[0]:
        raise PaymentAccountError('Este depósito está en revisión.')
    _, crypto = _active_pair(owner, local.country, local.asset)
    from .infinia_journeys import fx_source_amount
    source = fx_source_amount(credit.amount)
    target, expires = _quote(client or InfiniaClient(), local, crypto, source)
    from .bridge import bridge_cap, exceeds_bridge_cap
    if exceeds_bridge_cap(target):
        # The direct bridge preflight would send the journey to review.
        maximum = bridge_cap()
        shown = f'{maximum:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
        raise PaymentAccountError(f'Este depósito supera el máximo por conversión (US${shown}).')
    fx_minimum = (target * (1 - _tolerance('LOCAL_MONEY_FX_TOLERANCE_BPS', 100))).quantize(USDC_UNIT, rounding=ROUND_DOWN)
    from .bridge import executable_bridge_routes, bridge_route_minimum
    from .bridge_routing import quote_routes
    from .allbridge_next import to_units, address
    wallet = address(owner.bsc_address)
    # Price deposit-address overhead at the lowest authorized FX proceeds.
    # A percentage-only estimate misses fixed bridge costs on small deposits.
    routes = executable_bridge_routes(quote_routes(
        'POL:USDC', 'BSC:USDT', to_units(fx_minimum, 'POL:USDC'), wallet, wallet))
    bridge_minimum = Decimal(bridge_route_minimum(routes[0])) / Decimal(10 ** 18)
    wallet_minimum = (bridge_minimum * (1 - _tolerance('LOCAL_MONEY_BRIDGE_TOLERANCE_BPS', 150))).quantize(
        USDC_UNIT, rounding=ROUND_DOWN)
    return {'source_amount': source, 'asset': local.asset, 'target_amount': target,
            'minimum_fx_output': fx_minimum, 'minimum_wallet_output': wallet_minimum,
            'rate': (source / target).quantize(Decimal('0.0001')), 'expires_at': expires}


# --------------------------------------------------------------------- limits

def _decimal(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def account_limits(account, client):
    """Infinia /limits/ for one account, or None when it cannot be trusted."""
    try:
        data = client.get_account_limits(account.provider_account_id)
    except ProviderAPIError:
        return None
    monthly = data.get('monthly') if isinstance(data, dict) else None
    if not isinstance(monthly, dict):
        return None
    used, limit, remaining = (_decimal(monthly.get(key)) for key in ('used', 'limit', 'remaining'))
    # A successful explicit null is not an API failure. Infinia owns its
    # limits; without a numeric cap there is no monthly allowance to pre-check.
    # Keep missing/malformed responses distinct, and never advertise infinity.
    if 'limit' in monthly and monthly['limit'] is None and used is not None:
        return {'used': used, 'limit': None, 'remaining': None,
                'resets_at': str(monthly.get('resets_at') or '')}
    if remaining is None and limit is not None and used is not None:
        remaining = max(limit - used, Decimal(0))
    # Missing or malformed fields are still an untrustworthy response.
    if used is None or limit is None or remaining is None:
        return None
    return {'used': used, 'limit': limit, 'remaining': remaining, 'resets_at': str(monthly.get('resets_at') or '')}


def in_flight_usd(owner, exclude_request_id=None):
    # Infinia's `used` moves only when movements post, so a send still
    # bridging is invisible to it.
    journeys = InfiniaJourney.objects.filter(confio_account=owner, direction='to_bank').exclude(
        stage__in=['completed', 'failed'])
    if exclude_request_id:
        journeys = journeys.exclude(request_id=exclude_request_id)
    return journeys.aggregate(total=Sum('money_flow__source_amount'))['total'] or Decimal(0)


def _dollar_account(owner):
    return _owned(owner).filter(country='XXX', asset='USDC_POL', status='active').exclude(
        provider_account_id__isnull=True).exclude(provider_account_id='').first()


def limits(owner, *, client=None):
    """Display the shared dollar account's monthly usage as guidance only.

    Infinia enforces limits when processing transactions. This snapshot never
    blocks a send, even when the limit is exhausted or unavailable.
    """
    from .bridge import bridge_cap
    per_transfer = bridge_cap()  # None: no per-transfer cap
    crypto = _dollar_account(owner)
    empty = {'known': False, 'has_account': bool(crypto), 'per_transfer_max': per_transfer, 'limit': None,
             'used': None, 'available': None, 'resets_at': '', 'near_limit': False}
    if not crypto:
        return empty
    # Count before the provider snapshot so a send completed during the HTTP
    # request does not disappear from both counters in the displayed allowance.
    in_flight = in_flight_usd(owner)
    row = account_limits(crypto, client or InfiniaClient())
    if row is None or row['limit'] is None:
        return empty
    available = max(row['remaining'] - in_flight, Decimal(0))
    return {'known': True, 'has_account': True, 'per_transfer_max': per_transfer, 'limit': row['limit'],
            'used': max(row['limit'] - available, Decimal(0)), 'available': available,
            'resets_at': row['resets_at'], 'near_limit': available < row['limit'] * Decimal('0.2')}


# ------------------------------------------------------------------------ EDD

# What to have at hand before the Didit EDD session (see payment_accounts.edd).
_BANK = ('bank_statements', 'Estados de cuenta', 'Últimos 3 meses de tu banco o billetera')
# Infinia's documented increase requirements (Transaction Limits, 2026-06-25).
EDD_REQUIREMENTS = {
    'employed': (_BANK, ('income_proof', 'Recibos de sueldo o constancia de ingresos', 'Últimos 3 meses')),
    'self_employed': (_BANK, ('tax_returns', 'Declaraciones de impuestos', 'Últimos 2 años')),
    'not_employed': (_BANK, ('wealth_proof', 'Comprobante de ingresos o patrimonio',
                             'Inversiones, propiedades, herencia o pensión')),
    'business': (('financial_statements', 'Estados financieros', 'Últimos 2 años, auditados o de gestión'), _BANK),
}
# Brazil replaces the standard individual list.
BRAZIL_INDIVIDUAL = (
    ('irpf', 'Declaración del IRPF', 'La más reciente'),
    ('irpf_receipt', 'Recibo de entrega del IRPF', 'De esa misma declaración'),
    _BANK,
)


_PROOF_OF_ADDRESS = ('proof_of_address', 'Comprobante de domicilio',
                     'Factura de servicios, estado de cuenta o carta oficial reciente')


def edd_requirements(owner, income_type):
    """What to have at hand: proof of address, then the source-of-funds documents."""
    if owner.account_type == 'business':
        rows = EDD_REQUIREMENTS['business']
    elif income_type not in EDD_REQUIREMENTS or income_type == 'business':
        raise PaymentAccountError('Elige cómo generas tus ingresos.')
    elif _owned(owner).filter(country='BRA').exists():
        rows = BRAZIL_INDIVIDUAL
    else:
        rows = EDD_REQUIREMENTS[income_type]
    return (_PROOF_OF_ADDRESS, *rows)
