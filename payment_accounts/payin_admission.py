"""Fail-closed fiat admission. Provider capability is not a Confío user grant."""
import unicodedata
from decimal import Decimal

from django.db.models import Q

from .models import AccountCapability, MoneyOperation, PayinAdmission, ThirdPartyPayinSwitch
from .providers.common import iso_alpha2, same_country


def normalized(value):
    if not isinstance(value, str):
        return ''
    return ''.join(c for c in unicodedata.normalize('NFKD', value).upper()
                   if c.isalnum() and not unicodedata.combining(c))


def normalized_name(value):
    if not isinstance(value, str):
        return ''
    value = ''.join(c for c in unicodedata.normalize('NFKD', value).upper()
                    if not unicodedata.combining(c))
    return ' '.join(value.split())


def sender_matches(sender, identity, document_country):
    """No fuzzy names, no matching document numbers across jurisdictions/types."""
    if not isinstance(sender, dict) or sender.get('type') != 'FIAT':
        return False
    if not same_country(document_country, identity.get('document_issuing_country')):
        return False
    return (bool(normalized_name(sender.get('full_name')))
            and normalized_name(sender.get('full_name')) == normalized_name(identity.get('full_name'))
            and all(normalized(sender.get(key)) and normalized(sender.get(key)) == normalized(identity.get(key))
                    for key in ('document_number', 'document_type')))


def is_external_fiat_credit(entry):
    # Only authenticated movements of known fiat accounts. Unknown credit kinds
    # are conservatively screened, while internal conversions/refunds are not payins.
    if entry.provider != 'infinia' or entry.direction != 'credit' or Decimal(str(entry.amount)) <= 0:
        return False
    if same_country(entry.financial_account.country, 'XX') and entry.financial_account.asset not in {
            'ARS', 'BOB', 'BRL', 'CLP', 'COP', 'MXN', 'PEN', 'PYG', 'UYU', 'USD', 'EUR', 'GBP', 'SGD'}:
        return False
    payload = entry.provider_data if isinstance(entry.provider_data, dict) else {}
    operation = payload.get('operation') or {}
    kind = operation.get('type') if isinstance(operation, dict) else None
    operation_id = operation.get('operation_id') if isinstance(operation, dict) else None
    # Fiat conversion proceeds may use vouchers instead of operation_id. Reuse
    # the full settlement proof; a voucher string alone is not an exemption.
    third_party = payload.get('third_party') or {}
    voucher = third_party.get('voucher_id') if isinstance(third_party, dict) else None
    if not operation and isinstance(voucher, str) and voucher.strip():
        from .infinia_journeys import _credit_for_operation
        owner_id = entry.financial_account.provider_profile.confio_account_id
        candidates = MoneyOperation.objects.filter(provider='infinia',
            operation_type__in=['conversion', 'internal_transfer'],
            destination_account=entry.financial_account,
            money_flow__confio_account_id=owner_id,
            source_account__provider_profile__confio_account_id=owner_id,
            provider_data__voucher_ids__contains=[voucher])
        if any(_credit_for_operation(op, entry.financial_account, voucher_entry=entry) > 0 for op in candidates):
            return False
    if kind not in {'INTERNAL_TRANSFER', 'CREDIT', 'PAYOUT_REFUND', 'INTERNAL_TRANSFER_REFUND'} or not operation_id:
        return True
    # A provider label is not ownership evidence: another user's internal
    # transfer is still a third-party receipt. Only our correlated operations
    # returning to the same owner are exempt.
    operations = MoneyOperation.objects.filter(provider='infinia', provider_operation_id=operation_id,
        money_flow__confio_account_id=entry.financial_account.provider_profile.confio_account_id)
    if kind in {'INTERNAL_TRANSFER', 'CREDIT'}:
        return not operations.filter(operation_type__in=['conversion', 'internal_transfer'],
            destination_account=entry.financial_account,
            source_account__provider_profile__confio_account_id=entry.financial_account.provider_profile.confio_account_id).exists()
    expected_type = ['payout'] if kind == 'PAYOUT_REFUND' else ['conversion', 'internal_transfer']
    return not operations.filter(operation_type__in=expected_type, source_account=entry.financial_account).exists()


def decision(entry):
    account = entry.financial_account
    profile = account.provider_profile
    try:
        country = iso_alpha2(account.country)
    except ValueError:
        return False, 'unknown_country', '', ''
    rail = account.payin_rail.strip().upper()
    if entry.asset != account.asset:
        return False, 'asset_mismatch', country, rail
    identity = profile.identity_verification
    if not identity or identity.status != 'verified' or profile.status != 'active':
        return False, 'identity_not_verified', country, rail
    payload = entry.provider_data if isinstance(entry.provider_data, dict) else {}
    sender = payload.get('third_party')
    # Snapshot identifies the actual provisioned owner. Do not compare a business
    # bank sender against the personal identity of its representative.
    if profile.owner_type == 'individual' and rail not in {'', '*'} and sender_matches(
            sender, profile.identity_snapshot or {}, account.payin_document_country):
        permitted = AccountCapability.objects.filter(financial_account=account,
            capability='receive_same_name', status='enabled').exists()
        return permitted, 'same_owner' if permitted else 'provider_same_name_not_enabled', country, rail
    if rail in {'', '*'}:
        return False, 'unverified_rail', country, rail
    # One SQL snapshot: independent EXISTS calls could combine approvals that
    # were never enabled simultaneously while an operator changes the rollout.
    switches = {(row.rail, row.confio_account_id): row.enabled and bool(row.evidence.strip())
        for row in ThirdPartyPayinSwitch.objects.filter(
        Q(confio_account__isnull=True) | Q(confio_account_id=profile.confio_account_id),
        provider=profile.provider, country=country, rail__in=['', '*', rail])}
    # An explicit rail decision (including a stop) wins over an all-rails
    # grant. Wildcards never fill in missing/ambiguous account rail evidence.
    def allows(rail_code, owner):
        exact = (rail_code, owner)
        if exact in switches:
            return switches[exact]
        return bool(rail_code and switches.get(('*', owner), False))
    scopes = (
        ('country_not_enabled', ('', None)),
        ('rail_not_enabled', (rail, None)),
        ('user_not_enabled', (rail, profile.confio_account_id)),
    )
    for reason, filters in scopes:
        if not allows(*filters):
            return False, reason, country, rail
    # Missing/ambiguous sender evidence never becomes an implied match or a
    # blanket bypass, even for an approved third-party recipient.
    if not isinstance(sender, dict) or sender.get('type') != 'FIAT' or not normalized(sender.get('full_name')) or not normalized(sender.get('document_number')):
        return False, 'sender_identity_missing', country, rail
    permitted = AccountCapability.objects.filter(financial_account=account,
        capability='receive_third_party', status='enabled').exists()
    return permitted, 'third_party_enabled' if permitted else 'provider_third_party_not_enabled', country, rail


def assess(entry):
    if not is_external_fiat_credit(entry):
        return None
    allowed, reason, country, rail = decision(entry)
    admission, _ = PayinAdmission.objects.update_or_create(entry=entry,
        defaults=dict(allowed=allowed, reason=reason, country=country, rail=rail))
    return admission


def require_admitted(entry):
    from .services import PaymentAccountError
    admission = assess(entry)
    if admission and not admission.allowed:
        raise PaymentAccountError(f'Pay-in requires review: {admission.reason}')


def require_source_admitted(account):
    """Prevent generic operations from bypassing a held deposit via pooled balance."""
    for entry in account.ledger_entries.filter(provider='infinia', direction='credit').exclude(
            funded_journey__stage='completed').select_related('financial_account__provider_profile__identity_verification'):
        require_admitted(entry)
