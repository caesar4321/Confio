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
from .eligibility import (
    EligibilityPolicyNotConfigured, blocked_for_everyone, context_from_identity, evaluate_active_policy,
)
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
    Method('br_qr', 'send', 'BRA', 'BR', 'BRL', 'QR Pix', 'Paga QR Pix de tiendas, apps y personas',
           kind='qr', destination_type='BR_CODE', field='brCode'),
    Method('co_breb', 'send', 'COL', 'CO', 'COP', 'Llave Bre-B', 'Nequi, Bancolombia, Daviplata y más',
           kind='breb_key', destination_type='BREB_KEY', field='brebKey'),
    Method('co_qr', 'send', 'COL', 'CO', 'COP', 'QR Bre-B', 'Escanea una llave Bre-B desde un QR',
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


def decode_breb_qr(value):
    """Decode supported key-bearing EMV profiles, not arbitrary Colombian QRs.

    The original payload is retained locally; only its key goes to BREB_KEY.
    QR merchant text is self-reported, never a verified holder identity.
    EASPBV industry v1.4 (2025), tags 26/50, 53/54, 58/59/60.
    """
    fields = emv_fields(value) if len(value) <= 4096 else None
    if (not fields or fields.get('00') != '01' or fields.get('58') != 'CO'
            or fields.get('53') != '170' or fields.get('01') not in {'11', '12'}
            or not value[-8:].startswith('6304') or value[-4:].upper() != emv_crc(value[:-4])):
        raise PaymentAccountError('Este código no es un QR Bre-B válido en pesos colombianos.')
    template = emv_fields(fields.get('26', '')) or {}
    if '26' in fields and not template:
        raise PaymentAccountError('La llave del QR está incompleta.')
    if template:
        if template.get('00') not in {'CO.COM.RBM.LLA', 'CO.COM.CRB.LLA'}:
            raise PaymentAccountError('Este formato de QR Bre-B aún no está disponible.')
        keys = [v for k, v in template.items() if k in {'01', '02', '03', '04', '05'} and v]
        if len(keys) != 1 or set(template) - {'00', '01', '02', '03', '04', '05'}:
            raise PaymentAccountError('El QR debe identificar una sola llave Bre-B.')
        key = keys[0]
    else:
        template = emv_fields(fields.get('50', '')) or {}
        if template.get('00') not in {'CO.COM.RBM.CU', 'CO.COM.CRB.CU'} or not template.get('01'):
            raise PaymentAccountError('Este QR no contiene una llave Bre-B compatible.')
        key = template['01']
    key = normalize_value(METHODS['co_breb'], key)
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in key):
        raise PaymentAccountError('La llave del QR no es válida.')
    amount = fields.get('54', '')
    if amount and (not re.fullmatch(r'[0-9]{1,13}(?:\.[0-9]{1,2})?', amount)
                   or Decimal(amount) <= 0):
        raise PaymentAccountError('El monto del QR no es válido.')
    if '54' in fields and not amount:
        raise PaymentAccountError('El monto del QR no es válido.')
    return {'payload': value, 'key': key, 'amount': amount,
            'merchant_name': fields.get('59', ''), 'merchant_city': fields.get('60', '')}


ISO_NUMERIC = {'ARS': '032', 'BRL': '986', 'COP': '170'}   # EMV tag 53 (ISO 4217)
FIXED_QR_METHODS = ('co_qr', 'ar_qr')   # Bre-B and Argentina's interoperable QR


def qr_amount(method, value):
    """The local amount a Bre-B or Argentine QR asks for (EMV tag 54), or ''."""
    if method.id == 'co_qr':
        return decode_breb_qr(value)['amount']
    if method.id == 'ar_qr':
        fields = emv_fields(value) or {}
        # Only an amount in Argentine pesos is an amount we pay (normalize_value).
        return fields.get('54', '') if fields.get('53') == '032' else ''
    return ''


def method_of(destination):
    """A recipient's rail: the one its check wrote, or for a QR whose check
    has not written it yet, the QR it holds (_qr_payload)."""
    method = METHODS.get(((destination.provider_data or {}) if destination is not None else {}).get('method_id'))
    return method or _qr_payload(destination)[0]


def _qr_payload(destination):
    data = (destination.provider_data or {}) if destination is not None else {}
    method = METHODS.get(data.get('method_id'))
    if method is None and destination is not None:
        # A row whose check has not written its rail yet is still the QR it
        # holds: read from its own fields, never taken for an open recipient.
        if data.get('breb_qr'):
            method = METHODS['co_qr']
        elif destination.country == 'ARG' and (destination.details or {}).get('type') == 'QR_CODE':
            method = METHODS['ar_qr']
    if method is None or method.id not in FIXED_QR_METHODS:
        return None, ''
    return method, _destination_value(destination, method)


def fixed_qr_amount(destination):
    """What a fixed-amount QR recipient must receive, exactly, or '' for an
    open one. Read straight from the stored payload's amount field (not by
    validating the key again): a payload that cannot be read, or an amount in
    another currency, is refused, never taken for an open QR."""
    method, payload = _qr_payload(destination)
    if method is None or not payload:
        return ''
    fields = emv_fields(payload) if len(payload) <= 4096 else None
    if fields is None:
        raise PaymentAccountError('No pudimos leer este QR. Escanéalo de nuevo.')
    amount = fields.get('54', '')
    if amount and (not re.fullmatch(r'[0-9]{1,13}(?:\.[0-9]{1,2})?', amount) or Decimal(amount) <= 0):
        raise PaymentAccountError('El monto del QR no es válido.')
    if amount and fields.get('53') != ISO_NUMERIC.get(method.asset):
        raise PaymentAccountError('El monto de este QR no está en la moneda del país.')
    return amount


def is_fixed_amount_qr(destination):
    """A QR recipient that asks for an exact local amount: paid exactly
    (store_order_snapshot), never offered again as a saved recipient. One
    that cannot be read counts as fixed: whatever pays it then refuses."""
    try:
        return bool(fixed_qr_amount(destination))
    except PaymentAccountError:
        return True


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
    if method.id == 'co_qr':
        # A fixed amount is paid exactly: the dollars are priced to cover it
        # and the payout is the QR's pesos (store_order_snapshot).
        decode_breb_qr(value)
    elif method.id == 'mx_clabe':
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
            pix_code(value)
            return value
        # A fixed amount is paid exactly (store_order_snapshot): the dollars
        # are priced to cover it and the payout is the QR's own amount.
        amount = fields.get('54')
        if amount is not None and (not re.fullmatch(r'[0-9]{1,13}(?:\.[0-9]{1,2})?', amount)
                                   or Decimal(amount) <= 0):
            raise PaymentAccountError('El monto del QR no es válido.')
        if amount is not None and not fields.get('53'):
            raise PaymentAccountError('Este QR no indica su moneda. Pide uno nuevo.')
        if amount is not None and fields.get('53') != ISO_NUMERIC.get(method.asset):
            # An amount in another currency is never paid as local pesos.
            raise PaymentAccountError('El monto de este QR no está en la moneda del país.')
    return value


PIX_GUI = 'br.gov.bcb.pix'


def pix_code(value):
    """What a well-formed Pix BR Code asks for, read from the code itself.

    Static codes carry the Pix key; dynamic codes carry the location of a
    charge (field 25) whose amount, receiver and expiry only the Pix network
    knows. Nothing here is trusted as the receiver's identity: the merchant
    shown to the person comes from the provider's DICT lookup (validation).
    BCB Manual de Padrões para Iniciação do Pix, BR Code fields 26/54/62.
    """
    fields = emv_fields(value) if len(value) <= 4096 else None
    if (not fields or fields.get('00') != '01' or fields.get('58') != 'BR'
            or not value[-8:].startswith('6304') or value[-4:].upper() != emv_crc(value[:-4])):
        raise PaymentAccountError('Este código no es un QR de pago válido para este país.')
    templates = {k: emv_fields(v) or {} for k, v in fields.items() if k.isdigit() and 26 <= int(k) <= 51}
    pix = [t for t in templates.values() if t.get('00', '').lower() == PIX_GUI]
    if fields.get('53') != '986' or len(pix) != 1:
        raise PaymentAccountError('Este código no es un QR Pix en reales.')
    # Pix Automático (recurring authorization) rides in field 80; it is a
    # mandate, not a payment, and the provider does not pay it.
    if any((emv_fields(v) or {}).get('00', '').lower() == PIX_GUI
           for k, v in fields.items() if k.isdigit() and 52 <= int(k) <= 99 and k not in {'62', '63'}):
        raise PaymentAccountError('Los QR de Pix Automático (pagos recurrentes) no están disponibles.')
    template = pix[0]
    key, location = template.get('01', ''), template.get('25', '')
    if bool(key) == bool(location):
        raise PaymentAccountError('Este QR Pix no indica a quién pagar.')
    if location and (any(ord(ch) <= 32 or ord(ch) == 127 for ch in location) or '/' not in location):
        raise PaymentAccountError('Este QR Pix tiene un cobro con formato inválido.')
    if key and _pix_key(key) != key and not _EVP.fullmatch(key):
        # Validate the very key sent inside the untouched QR. Do not
        # verify a cleaned CPF/CNPJ while paying a different raw value.
        raise PaymentAccountError('Este QR contiene una chave Pix con formato inválido.')
    amount = fields.get('54', '')
    if '54' in fields and (not re.fullmatch(r'[0-9]{1,13}(?:\.[0-9]{1,2})?', amount) or Decimal(amount) <= 0):
        raise PaymentAccountError('El monto del QR no es válido.')
    if fields.get('01') == '12' and not (amount or location):
        raise PaymentAccountError('Este QR Pix de un solo uso no indica un monto.')
    additional = emv_fields(fields.get('62', '')) or {}
    txid = additional.get('05', '')
    return {'dynamic': bool(location), 'key': key, 'location': location, 'amount': amount,
            # Point of initiation 12: the code itself says it is paid once.
            'single_use': fields.get('01') == '12',
            'txid': '' if txid == '***' else txid, 'fixed': bool(location or amount),
            'merchant_name': fields.get('59', ''), 'merchant_city': fields.get('60', '')}


def fixed_pix_charge(method, value):
    """A Pix code that names its own amount: paid at that exact amount in reais."""
    return method.id == 'br_qr' and pix_code(value)['fixed']


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
    destination = method.country if method.direction == 'send' else 'XXX'
    # The same scopes provisioning and InfiniaJourney.validate_accounts enforce,
    # so a rail shown as live cannot fail on a policy the user never saw.
    checks = (
        ('account_opening', method.country, ''), ('account_opening', 'XXX', ''),
        ('conversion', method.country, destination), ('payout', method.country, destination),
    )
    if identity is None:
        # A rail a rule switches off for everyone is off before verification
        # too: nobody verifies their identity for a rail they will be refused.
        # Rules about who the person is, and policy defaults, wait for the
        # verified document (eligibility.blocked_for_everyone).
        for scope, account_country, destination_country in checks:
            rule = blocked_for_everyone(provider='infinia', scope=scope, account_country=account_country,
                                        destination_country=destination_country)
            if rule is not None:
                return 'unavailable', rule.reason_code or rule.decision
        return 'needs_verification', 'identity_required'
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
# US and Canadian driver's licences open them too (2026-11-13), whether Didit's
# label stored them as national_id or drivers_license. Other countries'
# licences are kept out by Didit (both personal workflows allow licences from
# USA and CAN only) and by security.didit._unmet_request for 'DL' requests; a
# "Driver's License" stored as national_id before then is not re-judged here.
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
    if identity.document_type != 'drivers_license':
        return False
    # Didit's "Driving License"/"Driver License" labels are stored as such
    # (its "Driver's License" as national_id): a US/Canadian one still counts.
    from security.didit import LICENCE_COUNTRIES
    return identity.document_issuing_country in LICENCE_COUNTRIES or identity.document_issuing_country == country == 'BRA'


def document_requirement(country):
    """What to ask for when none of the person's documents fits (Didit codes).
    'DL' means a US or Canadian licence only: security.didit._unmet_request."""
    return {'id_country': '', 'document_types': ['DL', 'ID', 'P']}


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


# Refusals for who the person IS (a seeded eligibility policy's reason code),
# not for a missing document. Mirrors IDENTITY_BLOCKED_REASONS in
# apps/src/services/localMoney.ts, which lists these rails as blocked.
IDENTITY_BLOCKED_REASONS = frozenset({'infinia_nationality_not_supported', 'infinia_region_not_supported'})


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
    if reason not in ('not_enabled', 'policy_not_configured') and region_unsupported(owner):
        return 'unavailable', REGION_UNSUPPORTED_REASON, None
    if status != 'live':
        return status, reason, None
    if document is None:
        return 'needs_document', 'document_not_accepted', document_requirement(method.country)
    if document is not anchor:
        status, reason = method_status(document, method)
    return status, reason, None


REGION_UNSUPPORTED_REASON = 'infinia_region_not_supported'
REGION_UNSUPPORTED_MESSAGE = 'Por ahora este servicio no está disponible en tu país.'


def region_unsupported(owner):
    """The provider serves nobody whose country (where the person lives:
    security.geo.country_of, User.country with the legacy phone country as a
    fallback) is one of these. Location itself is only read for Bre-B, by its
    own gate (breb_location)."""
    regions = getattr(settings, 'INFINIA_UNSUPPORTED_REGIONS', '')
    if isinstance(regions, str):
        regions = regions.split(',')
    regions = {value.strip().upper() for value in regions if value.strip()}
    from security.geo import country_of
    return country_of(owner.user) in regions


def require_region(owner):
    """Guards every way to open an account or send money out through the
    provider, including the generic endpoints that never see a rail. Money
    already on its way in still reaches the person's balance."""
    if region_unsupported(owner):
        raise PaymentAccountError(REGION_UNSUPPORTED_MESSAGE)


def require_rail(owner, primary, method):
    status, reason, _ = rail_status(owner, primary, method)
    if reason in IDENTITY_BLOCKED_REASONS:
        raise PaymentAccountError(REGION_UNSUPPORTED_MESSAGE)
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
    return (method.instruction_kind, 'qr') if method.id in {'br_pix_receive', 'co_breb_receive'} else (method.instruction_kind,)


def receive_instructions(account, method):
    return account.funding_instructions.filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()),
        kind__in=receive_instruction_kinds(method), status='active',
    ).exclude(display_value='').order_by('-updated_at', '-pk')


def breb_receiving_details(instructions):
    """One readiness rule for both charging an opening and revealing its data."""
    rows = list(instructions)
    instruction = next((row for row in rows if row.kind == 'breb_key'), None)
    value = instruction.display_value if instruction else ''
    candidates = [(row, row.display_value) for row in rows if row.kind == 'qr']
    if instruction:
        embedded = (instruction.instruction_data or {}).get('qr_code')
        if isinstance(embedded, str) and embedded:
            candidates.append((instruction, embedded))
    for candidate, payload in candidates:
        try:
            decoded = decode_breb_qr(payload)
        except PaymentAccountError:
            continue
        # Receiving details are reusable. Do not display a one-order dynamic
        # QR or an amount-specific collection instruction as a permanent key.
        if (not decoded['amount'] and emv_fields(payload).get('01') == '11'
                and (not instruction or decoded['key'] == value.strip())):
            return instruction or candidate, decoded['key'], payload
    return instruction, value, ''


def receiving_ready(account, method):
    rows = receive_instructions(account, method)
    if method.id == 'co_breb_receive':
        return bool(breb_receiving_details(rows)[1])
    return rows.exists()


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
    qr_value = ''
    receiving_value = instruction.display_value if instruction else ''
    if local and method.id == 'co_breb_receive':
        instruction, receiving_value, qr_value = breb_receiving_details(receive_instructions(local, method))
    return {
        'method': method, 'status': public_status, 'local': local, 'crypto': crypto,
        'instruction_kind': instruction.kind if instruction else method.instruction_kind,
        'value': receiving_value,
        'qr_value': qr_value,
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
    if method.id == 'co_qr':
        return {'country': 'CO', 'account': {'dataType': 'BREB_KEY', 'brebKey': decode_breb_qr(value)['key']}}
    if method.id == 'br_qr':
        # A static Pix QR without an amount embeds the registered key: check
        # that key, as before charges were payable.
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
    for key in ('accountHolderName', 'ownerName', 'merchantName', 'name', 'holder'):
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
    summary = {
        'id': str(response.get('id') or ''),
        'status': str(response.get('status') or '').upper(),
        'holder_name': _find_name(data)[:255],
        'holder_document': _mask(first.get('documentNumber') or data.get('holderDocument')),
        'institution': str(account.get('bankName') or data.get('bankName') or '')[:120],
        'checked_at': timezone.now().isoformat(),
    }
    if data.get('type') in ('static', 'dynamic'):
        # A Pix code's charge as the Pix network answers it (QRValidationResponseBrazil).
        summary['charge'] = {'type': data['type'], 'amount': str(data.get('amount') or ''),
                             'expiration': str(data.get('expiration') or ''),
                             'txid': str(data.get('txid') or '')[:35]}
    return summary


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
    if method.id == 'co_qr':
        return f"QR Bre-B · {decode_breb_qr(value)['key']}"
    if method.kind == 'qr':
        # Merchant text comes from the QR itself, not an owner lookup. Include
        # a stable reference so two saved codes with the same name differ.
        fields = emv_fields(value) or {}
        name = (validation.get('holder_name') if verification_state(validation) == VERIFIED
                and validation.get('holder_source') not in ('qr', 'charge') else fields.get('59'))
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
        # A name a Pix charge or its QR carries is not a registered holder.
        destination.holder_name = (validation['holder_name'] if verification_state(validation) == VERIFIED
                                   and validation.get('holder_source') not in ('qr', 'charge') else '')
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


def charge_checked_recently(validation):
    """A Pix charge can be paid, cancelled or expire within minutes: its check
    is trusted for LOCAL_MONEY_PIX_CHARGE_CHECK_SECONDS only."""
    seconds = int(getattr(settings, 'LOCAL_MONEY_PIX_CHARGE_CHECK_SECONDS', 600))
    try:
        checked = datetime.fromisoformat(str((validation or {}).get('checked_at') or ''))
    except ValueError:
        return False
    if timezone.is_naive(checked):
        return False
    return timedelta(0) <= timezone.now() - checked < timedelta(seconds=seconds)


def _is_charge(destination):
    data = getattr(destination, 'provider_data', None) or {}
    if data.get('method_id') != 'br_qr':
        return False
    try:
        return fixed_pix_charge(METHODS['br_qr'], (destination.details or {}).get('brCode', ''))
    except PaymentAccountError:
        return False


def _current_verified(destination):
    validation = (destination.provider_data or {}).get('validation')
    if verification_state(validation) != VERIFIED:
        return False
    return charge_checked_recently(validation) if _is_charge(destination) else checked_recently(validation)


def _validate(method, value, client):
    if method.id == 'br_qr' and fixed_pix_charge(method, value):
        # A Pix charge is read from the code and, for a dynamic one, from the
        # Pix network itself (signed payload, pix_payload): no paid lookup.
        if not getattr(settings, 'LOCAL_MONEY_PIX_CHARGES_ENABLED', True):
            return {'id': '', 'status': 'DISABLED', 'holder_name': '', 'holder_document': '',
                    'institution': '', 'checked_at': timezone.now().isoformat()}
        from . import pix_payload
        return pix_payload.validation(pix_code(value))
    if not getattr(settings, 'INFINIA_ACCOUNT_VALIDATION_ENABLED', False):
        return {'id': '', 'status': 'DISABLED', 'holder_name': '', 'holder_document': '',
                'institution': '', 'checked_at': timezone.now().isoformat()}
    try:
        return summarize_validation(
            (client or InfiniaClient()).create_bank_account_validation(_validation_request(method, value)))
    except ProviderAPIError:
        return {'id': '', 'status': 'TEMPORARY_FAILURE', 'holder_name': '', 'holder_document': '',
                'institution': '', 'checked_at': timezone.now().isoformat()}


def resolve_destination(owner, method_id, raw_value, *, client=None, store_order=None):
    """`store_order` ({'amount', 'reference'}, SPEI only): one store order's
    account, paid once with the order's own reference. Its row is never a
    saved recipient and never another order's."""
    from django.db import transaction
    method = get_method(method_id, 'send')
    value = normalize_value(method, raw_value)
    details = {'type': method.destination_type, method.field: value, **dict(method.constants)}
    if store_order is not None:
        if method.id != 'mx_clabe':
            raise PaymentAccountError('Este medio no paga pedidos de tiendas.')
        details['reference'] = store_order['reference']
    qr_data = decode_breb_qr(value) if method.id == 'co_qr' else None
    if qr_data:
        details[method.field] = qr_data['key']
    with transaction.atomic():
        # One destination per owner and key, found or created under the owner's
        # lock, with its check claimed before the provider is asked: overlapping
        # first lookups share one row and only the latest check records its answer.
        # A new row stays out of the saved list until its answer lands.
        type(owner).objects.select_for_update().filter(pk=owner.pk).first()
        candidates = PayoutDestination.objects.filter(
            confio_account=owner, provider='infinia', kind=method.kind, country=method.country, details=details,
        )
        # Different QR amounts/references must never overwrite a saved intent.
        if qr_data:
            candidates = candidates.filter(provider_data__breb_qr__payload=value)
        elif store_order is not None:
            candidates = candidates.filter(provider_data__store_order=store_order)
        else:
            candidates = candidates.filter(Q(provider_data__method_id__isnull=True)
                                           | ~Q(provider_data__method_id='co_qr'))
        destination = candidates.order_by('-created_at').first()
        if destination and _current_verified(destination):
            return destination
        if destination is None:
            destination = create_payout_destination(
                confio_account=owner, provider='infinia', kind=method.kind, country=method.country,
                asset=method.asset, label=_label(method, value, {})[:100], holder_name='', details=details)
            if qr_data:
                destination.provider_data = {**(destination.provider_data or {}),
                                             'method_id': method.id, 'breb_qr': qr_data}
                destination.save(update_fields=['provider_data'])
            elif fixed_pix_charge(method, value):
                destination.provider_data = {**(destination.provider_data or {}), 'fixed_charge': True}
                destination.save(update_fields=['provider_data'])
            elif store_order is not None:
                # fixed_charge keeps it out of the saved list (saved_destinations).
                destination.provider_data = {**(destination.provider_data or {}), 'fixed_charge': True,
                                             'store_order': store_order}
                destination.save(update_fields=['provider_data'])
        check = _start_check(destination)
    validation = _validate(method, value, client)
    return _apply_validation(destination, method, value, validation, check=check)


def refresh_destination(destination, *, client=None):
    data = destination.provider_data or {}
    validation = data.get('validation') or {}
    method = METHODS.get(data.get('method_id'))
    if not method or verification_state(validation) != PENDING or not validation.get('id'):
        return destination
    value = _destination_value(destination, method)
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
    value = _destination_value(destination, method)
    check = _start_check(destination)
    return _apply_validation(destination, method, value, _validate(method, value, client), check=check)


def refresh_charge(destination, *, client=None):
    """Read a Pix charge again now: it can be paid, cancelled or revised within
    minutes, so a confirmation never rests on an earlier reading."""
    if not _is_charge(destination):
        return destination
    method = METHODS['br_qr']
    value = _destination_value(destination, method)
    check = _start_check(destination)
    return _apply_validation(destination, method, value, _validate(method, value, client), check=check)


def require_current_destination(destination):
    """Server-side guard for a new send: a holder verified long ago is checked again first."""
    validation = (destination.provider_data or {}).get('validation')
    if verification_state(validation) == VERIFIED and not _current_verified(destination):
        raise PaymentAccountError('Revisa de nuevo a quien recibe antes de enviar.')


def _destination_value(destination, method):
    if method.id == 'co_qr':
        return (destination.provider_data or {}).get('breb_qr', {}).get('payload', '')
    return destination.details.get(method.field, '')


def _shown_qr_amount(destination):
    try:
        return fixed_qr_amount(destination)
    except PaymentAccountError:
        return ''


def destination_view(destination):
    data = destination.provider_data or {}
    validation = data.get('validation') or {}
    state = verification_state(validation)
    if state == VERIFIED and validation.get('holder_source') in ('qr', 'charge'):
        # A Pix charge's name comes from the code or its payload, not from a
        # registered-holder lookup: never shown as a verified holder; the
        # person confirms it explicitly, as for any unchecked recipient.
        state = UNVERIFIED
    method = METHODS.get(data.get('method_id'))
    label = _label(method, _destination_value(destination, method), validation) if method else destination.label
    qr_data = data.get('breb_qr') or {}
    return {
        'id': destination.internal_id, 'method_id': str(data.get('method_id') or ''), 'label': label,
        'holder_name': validation.get('holder_name', '') if state == VERIFIED else '',
        'holder_document': validation.get('holder_document', '') if state == VERIFIED else '',
        'institution': validation.get('institution', ''), 'verification': state,
        'country': iso_alpha2(destination.country), 'asset': destination.asset,
        'qr_amount': _shown_qr_amount(destination), 'qr_merchant_name': qr_data.get('merchant_name', ''),
        'qr_merchant_city': qr_data.get('merchant_city', ''),
    }


def saved_destinations(owner, method_id):
    # A Pix charge is paid once: it is never offered again as a saved recipient
    # (excluded before the slice, so charges never crowd out real recipients).
    rows = PayoutDestination.objects.filter(
        confio_account=owner, provider='infinia', provider_data__method_id=get_method(method_id, 'send').id,
    # Containment, not a key lookup: rows without the key must stay (a key
    # lookup is NULL there and NOT NULL would drop every normal recipient).
    ).exclude(provider_data__contains={'fixed_charge': True}).order_by('-created_at')[:10]
    return [row for row in rows if verification_state((row.provider_data or {}).get('validation')) != NOT_FOUND
            and not _is_charge(row) and not is_fixed_amount_qr(row)]


# ---------------------------------------------------------------- Pix charges

def _charge_amount(value):
    amount = _decimal(value)
    if amount is None or amount <= 0 or amount != amount.quantize(FIAT_CENT) or amount >= Decimal('1e9'):
        return None
    return amount.quantize(FIAT_CENT)


def _aware(value):
    from django.utils.dateparse import parse_datetime
    try:
        stamp = parse_datetime(str(value or ''))
    except ValueError:
        return None
    if stamp is None:
        return None
    if timezone.is_naive(stamp):
        from datetime import timezone as dt_timezone
        stamp = stamp.replace(tzinfo=dt_timezone.utc)
    return stamp


def _sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def pix_charge(destination):
    """The charge behind a fixed-amount Pix code, as the Pix network answered
    it (provider validation), or None for any other recipient.

    `verified` holds only when the network answered for this very code: a
    receiver name, a positive amount in cents and the code's own kind. A
    static code's printed amount must match the answer; a dynamic code's
    amount is the network's (BCB: the charge payload prevails).
    """
    if not _is_charge(destination):
        return None
    value = destination.details.get('brCode', '')
    code = pix_code(value)
    validation = (destination.provider_data or {}).get('validation') or {}
    answer = validation.get('charge') or {}
    amount = _charge_amount(answer.get('amount'))
    expires_at = _aware(answer.get('expiration'))
    # A dynamic charge always expires; one whose expiry we cannot read is
    # refused rather than treated as never expiring (fail closed).
    verified = (verification_state(validation) == VERIFIED and amount is not None
                and answer.get('type') == ('dynamic' if code['dynamic'] else 'static')
                and (code['dynamic'] or Decimal(code['amount']) == amount)
                and (expires_at is not None or not code['dynamic']))
    txid = code['txid'] or ('' if code['dynamic'] else str(answer.get('txid') or '').strip('*'))
    if code['dynamic']:
        key, single_use = 'pix:loc:' + _sha(code['location'].lower()), True
    elif txid:
        # A static code is reusable by design (a shop's printed QR); its txid
        # is a reconciliation reference. Only a payment in flight blocks it.
        key, single_use = 'pix:txid:' + _sha(f"{code['key']}|{txid}"), code['single_use']
    else:
        key, single_use = 'pix:qr:' + _sha(value), code['single_use']
    return {'verified': verified, 'amount': amount, 'expires_at': expires_at,
            'expiration_raw': str(answer.get('expiration') or ''), 'key': key, 'single_use': single_use,
            'dynamic': code['dynamic'], 'validation': validation}


def charge_snapshot(destination):
    """The terms a journey pays a Pix charge on; None for any other recipient."""
    charge = pix_charge(destination)
    if charge is None:
        return None
    return {'key': charge['key'], 'single_use': charge['single_use'],
            'amount': str(charge['amount'] or ''), 'expires_at': charge['expiration_raw'],
            'holder': str(charge['validation'].get('holder_name') or ''),
            'holder_source': str(charge['validation'].get('holder_source') or 'dict')}


def store_order_snapshot(destination):
    """The terms a journey pays one store order on (SPEI: exact pesos with the
    order's reference); None for any other recipient. The key is the order:
    paid once, from any account."""
    amount = fixed_qr_amount(destination)
    if amount:
        # A QR with a fixed amount (Bre-B, Argentina): the payout is the QR's
        # exact local amount and what the conversion lands above it stays in
        # the person's own local account. A dynamic QR (01=12) is one charge,
        # paid once; a static one with an amount may be paid again.
        method, payload = _qr_payload(destination)
        return {'amount': str(Decimal(amount).quantize(FIAT_CENT)), 'reference': '',
                'key': f'{method.id}:qr:' + _sha(payload),
                # Only a QR that says it is static (01=11) may be paid again.
                'once': (emv_fields(payload) or {}).get('01') != '11'}
    order = (destination.provider_data or {}).get('store_order') if destination is not None else None
    if not order:
        return None
    clabe = (destination.details or {}).get('clabe', '')
    return {'amount': str(order['amount']), 'reference': str(order['reference']),
            # The order is its account and reference: a second reading with another amount is the same order.
            'key': 'spei:order:' + _sha(f"{clabe}|{order['reference']}")}


def _seconds_left(expires_at):
    return None if expires_at is None else (expires_at - timezone.now()).total_seconds()


def require_payable_charge(owner, destination, *, exclude_request_id=None):
    """Refuse a Pix charge that cannot be paid now: unverified, checked too
    long ago, too close to its expiry to settle, or already paid."""
    charge = pix_charge(destination)
    if charge is None:
        raise PaymentAccountError('Este QR no tiene un cobro para pagar.')
    if not charge['verified']:
        raise PaymentAccountError('No pudimos confirmar este cobro con el banco. Escanea el QR de nuevo.')
    if not charge_checked_recently(charge['validation']):
        raise PaymentAccountError('Revisa de nuevo el cobro antes de pagar.')
    left = _seconds_left(charge['expires_at'])
    if left is not None and left < int(getattr(settings, 'LOCAL_MONEY_PIX_MIN_SECONDS_LEFT', 600)):
        raise PaymentAccountError('Este cobro vence muy pronto para pagarlo con seguridad. Pide un QR nuevo.')
    from .infinia_bridge import live_journeys
    # A dynamic charge is one payment on the Pix network, whichever account
    # (personal, business, anyone's) pays it: never a second funding for it.
    journeys = InfiniaJourney.objects.filter(direction='to_bank',
                                             destination_snapshot__pix_charge__key=charge['key'])
    if not charge['single_use']:
        journeys = journeys.filter(confio_account=owner)
    if exclude_request_id:
        journeys = journeys.exclude(request_id=exclude_request_id)
    if live_journeys(journeys).exists():
        raise PaymentAccountError('Ya hay un pago en curso para este QR.')
    # A charge is paid once. Only a payment that ended without paying it
    # (refunded, or never funded) lets the person try again.
    if charge['single_use']:
        blocking = journeys.exclude(stage='failed')
        if blocking.filter(confio_account=owner, stage='completed').exists():
            raise PaymentAccountError('Ya pagaste este cobro.')
        if blocking.exists():
            # Another account's payment, or one under review: say no more than
            # that it cannot be paid again from Confío now.
            raise PaymentAccountError('Este cobro ya tiene un pago en Confío y no se puede pagar otra vez.')
    return charge


def _fx_buffer():
    return _tolerance('LOCAL_MONEY_PIX_FX_BUFFER_BPS', 100)


def usdc_for_target(client, crypto, local, target, *, external_id=None):
    """The dollars a provider FX quote asks for to land exactly `target` in the
    local account. Returns (source_amount, quote)."""
    from .infinia_journeys import provider_number, positive
    response = client.create_transfer_quote({
        'external_id': external_id or f'confio-estimate-{uuid.uuid4()}',
        'source_account_id': crypto.provider_account_id, 'target_account_id': local.provider_account_id,
        'target_amount': provider_number(target),
    })
    try:
        source = positive(response.get('source_amount'))
        if (response.get('status') != 'ACTIVE' or positive(response.get('target_amount')) != target
                or str(response.get('source_account_id') or crypto.provider_account_id) != crypto.provider_account_id
                or str(response.get('target_account_id') or local.provider_account_id) != local.provider_account_id):
            raise ValueError('quote does not match')
    except (AttributeError, TypeError, ValueError, ArithmeticError, PaymentAccountError) as exc:
        raise PaymentAccountError('No pudimos cotizar este pago. Intenta de nuevo.') from exc
    return source, response


def pix_charge_quote(owner, destination, *, client=None):
    """What paying a Pix charge costs the person, all in.

    The merchant receives exactly the charge amount. The dollars that leave
    the wallet cover the processor fee, the conversion and a buffer
    (LOCAL_MONEY_PIX_FX_BUFFER_BPS) against the rate moving before it runs;
    whatever the buffer does not use goes back to the person's own wallet.
    """
    charge = require_payable_charge(owner, destination)
    local, crypto = _active_pair(owner, destination.country, destination.asset)
    client = client or InfiniaClient()
    exact_source, _ = usdc_for_target(client, crypto, local, charge['amount'])
    needed = (exact_source * (1 + _fx_buffer())).quantize(FIAT_CENT, rounding=ROUND_UP)
    from .infinia_fee_policy import price as fee_price
    from .bridge import exceeds_bridge_cap
    fee = fee_price(local, 'to_bank', destination=destination)
    fee_usd = Decimal(fee['total_usd']) if fee else Decimal(0)
    total = (needed + fee_usd).quantize(FIAT_CENT, rounding=ROUND_UP)
    for _ in range(5):
        if exceeds_bridge_cap(total):
            raise PaymentAccountError('Este cobro supera el máximo por pago.')
        minimum, expected, instruction = _bridge_estimate(owner, crypto, total, fee)
        if minimum >= needed:
            break
        if minimum <= 0:
            raise PaymentAccountError('No pudimos cotizar este pago. Intenta de nuevo.')
        total = (total * needed / minimum).quantize(FIAT_CENT, rounding=ROUND_UP) + FIAT_CENT
    else:
        raise PaymentAccountError('No pudimos cotizar este pago. Intenta de nuevo.')
    if fee or getattr(settings, 'INFINIA_LEGACY_PAYOUT_FEES_ENABLED', False):
        from .infinia_legacy_fees import remember
        remember(owner, instruction, total, destination)
    validation = charge['validation']
    return {'amount': charge['amount'], 'asset': local.asset, 'total_usd': total, 'fee_usd': fee_usd,
            'estimated_return_usd': max(expected - exact_source, Decimal(0)).quantize(FIAT_CENT, rounding=ROUND_DOWN),
            'merchant_name': validation.get('holder_name', ''), 'merchant_document': validation.get('holder_document', ''),
            # Where the name comes from: 'dict' (provider lookup), 'charge'
            # (the signed payload) or 'qr' (the code's own, unsigned text).
            'merchant_source': str(validation.get('holder_source') or 'dict'),
            'institution': validation.get('institution', ''),
            'expires_at': charge['expires_at'].isoformat() if charge['expires_at'] else '',
            'dynamic': charge['dynamic'], 'rate': (charge['amount'] / total).quantize(Decimal('0.0001'))}


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


def fee_exceeds_amount_message(fee):
    total = Decimal(fee['total_usd']).quantize(FIAT_CENT, rounding=ROUND_UP)
    return (f'El monto no alcanza para la comisión del procesador de pagos (US${total}). '
            'Ingresa un monto mayor.')


def payout_fee(owner, destination, *, bridge=None):
    """The processor's fee for a send, split for display. None when none applies.

    With a prepared bridge it is the frozen fee that bridge collects.
    """
    from .infinia_fee_policy import disclosure, price as fee_price
    if bridge is not None:
        if bridge.quote.confio_account_id != owner.pk:
            raise PaymentAccountError('Este envío no corresponde a tu cuenta.')
        frozen_destination = bridge.quote.money_flow.metadata.get('local_destination_id')
        if frozen_destination and frozen_destination != str(destination.internal_id):
            raise PaymentAccountError('Este envío no corresponde al destinatario. Solicita una nueva cotización.')
        return disclosure(bridge.quote.money_flow.metadata.get('infinia_fee'))
    local, _ = _active_pair(owner, destination.country, destination.asset)
    return disclosure(fee_price(local, 'to_bank', destination=destination))


def _bridge_estimate(owner, crypto, total, fee):
    """(minimum, expected) USDC a bridge funded from a total USD spend lands
    in the provider dollar account, and that account's deposit instruction."""
    from .bridge import net_funding_units, executable_bridge_routes, bridge_route_minimum, verified_destination
    from .allbridge_next import to_units
    from .bridge_routing import quote_routes
    from .models import FundingInstruction
    if fee:
        from .infinia_fee_funding import quote_funding
        from .infinia_fees import FeePricingError
        budget = int(to_units(total, 'BSC:USDT'))
        if budget <= int(fee['units']):
            raise PaymentAccountError(fee_exceeds_amount_message(fee))
        try:
            units = quote_funding(owner, budget, int(fee['units']))['bridge_units']
        except FeePricingError as exc:
            if 'too small' in str(exc):
                raise PaymentAccountError(fee_exceeds_amount_message(fee)) from exc
            raise
    else:
        units = net_funding_units(owner, int(to_units(total, 'BSC:USDT')))
    instruction = FundingInstruction.objects.filter(financial_account=crypto,
        kind='crypto_address', status='active').first()
    if instruction is None:
        raise PaymentAccountError('An active crypto funding instruction is required')
    recipient = verified_destination(instruction, owner)
    route = executable_bridge_routes(quote_routes('BSC:USDT', 'POL:USDC', units,
                                                  owner.bsc_address, recipient))[0]
    return (Decimal(bridge_route_minimum(route)) / Decimal(10 ** 6),
            Decimal(int(route['amountOut'])) / Decimal(10 ** 6), instruction)


def _charge_review_quote(owner, destination, local, crypto, source, *, client=None):
    """A send to a Pix charge lands exactly the charge amount, never 'at least'.

    The bridge's guaranteed minimum must cover a fresh quote for that amount
    plus the buffer; otherwise the person reviews a new price instead of
    signing one that could fall short when it runs. Returns (exact dollars
    the conversion takes, charge amount, quote expiry).
    """
    charge = require_payable_charge(owner, destination)
    target = charge['amount']
    exact_source, response = usdc_for_target(client or InfiniaClient(), crypto, local, target)
    # The price shown carries the full buffer; the review gate asks for half
    # of it, so a small move between the two does not send the person back.
    if source < (exact_source * (1 + _fx_buffer() / 2)).quantize(FIAT_CENT, rounding=ROUND_UP):
        raise PaymentAccountError('El precio del cobro cambió. Revisa el pago de nuevo.')
    # Never far more than the charge needs: an app that predates charges lets
    # people type any amount, and the excess would only cost bridge fees.
    if source > (exact_source * (1 + 2 * _fx_buffer())).quantize(FIAT_CENT, rounding=ROUND_UP) + Decimal('0.50'):
        raise PaymentAccountError('Este QR cobra un monto exacto. Actualiza la app para pagarlo.')
    return exact_source, target, str(response.get('expire_at') or '')


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
        frozen_destination = bridge.quote.money_flow.metadata.get('local_destination_id')
        if frozen_destination and frozen_destination != str(destination.internal_id):
            raise PaymentAccountError('Este envío no corresponde al destinatario. Solicita una nueva cotización.')
        source = (Decimal(int(bridge.amount_out_min)) / Decimal(10 ** 6)).quantize(USDC_UNIT, rounding=ROUND_DOWN)
        expected_source = (Decimal(int(bridge.amount_out)) / Decimal(10 ** 6)).quantize(USDC_UNIT, rounding=ROUND_DOWN)
        spend = bridge.quote.money_flow.source_amount
    else:
        # The typed amount is the user's total budget, not the USDC principal.
        # Price the post-redemption USDT through the same bridge used at review.
        from .bridge import exceeds_bridge_cap
        total = _positive(amount, USDC_UNIT)
        if exceeds_bridge_cap(total):
            raise PaymentAccountError('Amount exceeds the configured bridge limit')
        from .infinia_fee_policy import price as fee_price
        fee = fee_price(local, 'to_bank', destination=destination)
        source, expected_source, instruction = _bridge_estimate(owner, crypto, total, fee)
        spend = total
    if charge_snapshot(destination) is not None:
        # Exact: the merchant receives the charge amount, and any dollars the
        # conversion does not use go back to the person (journey return leg).
        source, target, expires = _charge_review_quote(owner, destination, local, crypto, source, client=client)
        minimum = expected_target = target
    else:
        source = fx_source_amount(source)
        target, expires = _quote(client or InfiniaClient(), crypto, local, source)
        minimum = (target * (1 - _tolerance('LOCAL_MONEY_FX_TOLERANCE_BPS', 100))).quantize(FIAT_CENT, rounding=ROUND_DOWN)
        # Relay's tolerance is amount-aware, so the gap between what should land and
        # the minimum we authorize widens on small sends. Show both rather than
        # blocking the send: target_amount is already priced off the minimum.
        expected_target = (target * expected_source / source).quantize(FIAT_CENT, rounding=ROUND_DOWN)
    cost = ((spend - expected_source) / spend * 100).quantize(FIAT_CENT, rounding=ROUND_UP)
    if bridge is not None and bridge.quote.money_flow.metadata.get('legacy_fee_review_required'):
        from .infinia_legacy_fees import record_review
        record_review(bridge.quote.money_flow, destination)
    if bridge is None and (fee or getattr(settings, 'INFINIA_LEGACY_PAYOUT_FEES_ENABLED', False)):
        from .infinia_legacy_fees import remember
        remember(owner, instruction, total, destination)
    return {'source_amount': source, 'target_amount': target, 'minimum_target': minimum,
            'expected_source_amount': expected_source, 'expected_target': expected_target,
            'total_cost_percent': cost,
            'rate': (target / spend).quantize(Decimal('0.0001')),
            'asset': local.asset, 'expires_at': expires}


UPDATE_FOR_FIXED_QR = 'Este QR cobra un monto exacto. Actualiza la app para pagarlo.'


def _exact_amount(value):
    """A local amount to pay exactly: positive, whole cents, below 1e9."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        amount = None
    if amount is None or not amount.is_finite() or amount <= 0:
        raise PaymentAccountError('Escribe el monto en moneda local con hasta dos decimales.')
    if amount >= Decimal('1e9'):   # before quantizing: a huge exponent cannot be quantized
        raise PaymentAccountError('Ese monto es demasiado alto para un envío.')
    if amount != amount.quantize(FIAT_CENT):
        raise PaymentAccountError('Escribe el monto en moneda local con hasta dos decimales.')
    return amount.quantize(FIAT_CENT)


FIXED_QR_MIN_APP_VERSION = '5.4.0'   # the first build that shows a fixed-amount QR as one


def fixed_qr_build_supported(meta):
    """The build pays a fixed-amount QR as one (LOCAL_MONEY_FIXED_QR_MIN_APP_VERSION,
    5.4.0 by default): an older build is told to update before any bridge."""
    from ramps.ve_pagomovil import _version
    floor = _version(getattr(settings, 'LOCAL_MONEY_FIXED_QR_MIN_APP_VERSION', FIXED_QR_MIN_APP_VERSION))
    version = _version((meta or {}).get('HTTP_X_CONFIO_VERSION', ''))
    return floor is not None and version is not None and version >= floor


def require_exact_for_fixed(destination, exact):
    """A fixed-amount QR is quoted only with its own amount (asked before any
    provider is): an older build that types dollars is told to update."""
    # A QR that cannot be read says so (its own error), not "update the app".
    if exact is None and fixed_qr_amount(destination):
        raise PaymentAccountError(UPDATE_FOR_FIXED_QR)


def require_unpaid_qr(destination):
    """A dynamic fixed-amount QR is one charge: refused once a payment of it
    is running or has paid it, before any bridge is prepared."""
    order = store_order_snapshot(destination) if is_fixed_amount_qr(destination) else None
    if order is None or not order.get('once'):
        return
    if is_held(order['key'], destination=destination):
        raise PaymentAccountError('Este QR ya tiene un pago en Confío y no se puede pagar otra vez.')


SAME_QR_LIMIT = 500


def _same_qr_destinations(destination):
    """Every recipient row (any account) that holds this very QR, at most
    SAME_QR_LIMIT + 1 (is_held counts more than the limit as held)."""
    method, payload = _qr_payload(destination)
    if method is None or not payload:
        return []
    rows = PayoutDestination.objects.filter(provider='infinia', country=method.country)
    rows = (rows.filter(provider_data__breb_qr__payload=payload) if method.id == 'co_qr'
            else rows.filter(**{f'details__{method.field}': payload}))
    return [str(value) for value in rows.order_by('pk').values_list('internal_id', flat=True)[:SAME_QR_LIMIT + 1]]


def is_held(key, exclude_request_id=None, destination=None):
    """Whether a paid-once order or QR is held (holding_payments). Fails
    closed: more rows holding the same QR than can be checked count as held."""
    if destination is not None and ':qr:' in str(key) and len(_same_qr_destinations(destination)) > SAME_QR_LIMIT:
        return True
    return holding_payments(key, exclude_request_id=exclude_request_id, destination=destination).exists()


def holding_payments(key, exclude_request_id=None, destination=None):
    """The payments that hold a paid-once order or QR: any that is not
    failed, except one whose bridge was never signed and can no longer be
    (someone who only opened a payment does not block everyone else). For a
    QR (`destination`), also a payment of it made before QRs carried their
    amount (paid in dollars, with no order key)."""
    import time
    from .models import InfiniaJourney
    held = Q(destination_snapshot__store_order__key=key)
    if destination is not None and ':qr:' in str(key):
        legacy = _same_qr_destinations(destination)
        if legacy:
            held |= (Q(destination_snapshot__destination_internal_id__in=legacy)
                     & ~Q(destination_snapshot__has_key='store_order'))
    rows = InfiniaJourney.objects.filter(held, direction='to_bank') \
        .exclude(stage='failed').exclude(bridge__status='prepared', bridge__deadline__lt=int(time.time()))
    return rows.exclude(request_id=exclude_request_id) if exclude_request_id else rows


def exact_qr_quote(destination, quote, exact=None):
    """The Pagar screen's quote for a fixed-amount QR, or for an exact local
    amount the person typed (`exact`): the recipient receives exactly that, so
    it is what is shown and authorized as the journey's minimum. Refused when
    the dollars no longer cover it (the screen prices it again)."""
    if exact is not None and charge_snapshot(destination) is not None:
        # A Pix charge has its own amount and path: never a typed one.
        raise PaymentAccountError('Este cobro ya trae su monto.')
    order = store_order_snapshot(destination) if is_fixed_amount_qr(destination) else None
    if order is not None:
        # A fixed-amount QR is paid only by a build that shows it as one (it
        # asks with the QR's own amount); an older build would type dollars
        # and never be told the QR is paid exactly.
        if exact is None:
            raise PaymentAccountError(UPDATE_FOR_FIXED_QR)
        if _exact_amount(exact) != Decimal(order['amount']):
            raise PaymentAccountError('El monto no coincide con el del QR. Revisa el pago de nuevo.')
    if exact is None:
        return quote
    exact = _exact_amount(exact)
    if Decimal(quote['minimum_target']) < exact:
        # Priced again next time, not from the few seconds' memory.
        from .intent_rails import forget_order_price
        forget_order_price(destination, exact)
        raise PaymentAccountError('El precio cambió. Revisa el envío de nuevo.')
    return {**quote, 'target_amount': exact, 'minimum_target': exact, 'expected_target': exact}


def exact_send_quote(owner, destination, exact, *, client=None):
    """What sending an exact local amount the person typed costs, all in
    (the Pagar screen's charge view): the dollars whose guaranteed minimum
    covers it; the rest stays in the person's own local account."""
    from .intent_rails import _order_price
    if charge_snapshot(destination) is not None or is_fixed_amount_qr(destination):
        raise PaymentAccountError('Este QR ya trae su monto.')
    if (destination.provider_data or {}).get('store_order'):
        raise PaymentAccountError('Este pedido ya trae su monto.')
    exact = _exact_amount(exact)
    price = _order_price(owner, destination, exact, client=client)
    return {'amount': exact, 'asset': price['currency'], 'total_usd': price['total_usd'],
            'fee_usd': price['fee_usd'], 'estimated_return_usd': Decimal('0.00'),
            'merchant_name': '', 'merchant_document': '', 'merchant_source': 'typed',
            'institution': '', 'expires_at': '', 'dynamic': False,
            'rate': (exact / price['total_usd']).quantize(Decimal('0.0001'))}


def fixed_qr_charge_quote(owner, destination, *, client=None):
    """What paying a fixed-amount QR (Bre-B, Argentina) costs, all in (the Pagar screen's
    charge view, same shape as pix_charge_quote). Priced like the assistant's
    card: the dollars whose guaranteed minimum covers the QR's pesos; the
    payout is exactly those pesos and the rest stays in the person's own
    peso account."""
    from .intent_rails import _order_price
    require_unpaid_qr(destination)
    order = store_order_snapshot(destination)
    exact = Decimal(order['amount'])
    price = _order_price(owner, destination, exact, client=client)
    _, payload = _qr_payload(destination)
    return {'amount': exact, 'asset': price['currency'], 'total_usd': price['total_usd'],
            'fee_usd': price['fee_usd'], 'estimated_return_usd': Decimal('0.00'),
            'merchant_name': (emv_fields(payload) or {}).get('59', ''), 'merchant_document': '', 'merchant_source': 'qr',
            'institution': '', 'expires_at': '', 'dynamic': order['once'],
            'rate': (exact / price['total_usd']).quantize(Decimal('0.0001'))}


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
    from .infinia_fee_policy import price as fee_price
    fee = fee_price(local, 'to_wallet')
    net_wallet_receipt = None
    if fee:
        from cusd_plus import cusd_vault
        preview = cusd_vault.preview_mint_wei(int(wallet_minimum * 10**18))
        net_units = max(0, preview.net_wei - int(fee['units']))
        if not 0 <= preview.fee_bps <= 90 or preview.net_wei <= 0:
            raise PaymentAccountError('El monto no alcanza para cubrir los costos de conversión.')
        net_wallet_receipt = Decimal(net_units) / Decimal(10**18)
    return {'source_amount': source, 'asset': local.asset, 'target_amount': target,
            'minimum_fx_output': fx_minimum, 'minimum_wallet_output': wallet_minimum,
            'minimum_net_wallet_receipt': net_wallet_receipt,
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
