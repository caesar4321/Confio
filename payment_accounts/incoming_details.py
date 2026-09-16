"""Recipient-visible sender details from the original fiat receipt, never KYC."""
import unicodedata


def _text(value, limit=160):
    if not isinstance(value, str):
        return ''
    value = ' '.join(value.split())
    return ''.join(c for c in value if not unicodedata.category(c).startswith('C'))[:limit]


def sender_details(entry):
    if not entry or entry.provider != 'infinia' or entry.direction != 'credit':
        return None
    data = entry.provider_data if isinstance(entry.provider_data, dict) else {}
    sender = data.get('third_party')
    if not isinstance(sender, dict) or sender.get('type') != 'FIAT':
        return None
    account = ''.join(_text(sender.get('account_number'), 256).split())
    return {
        'name': _text(sender.get('full_name')),
        'bank_name': _text(sender.get('bank_name')),
        'bank_code': _text(sender.get('bank_code'), 40),
        'account_masked': ('•••• ' + account[-4:] if len(account) > 4 else '••••') if account else '',
        'reference': _text(sender.get('source_reference'), 200) or _text(sender.get('voucher_id'), 200),
    }


def incoming_credit(journey):
    """Never expose a bridge/FX counterparty as the fiat sender."""
    entry = journey.funding_credit if journey.direction == 'to_wallet' else None
    if entry and entry.financial_account_id == journey.local_account_id and entry.provider == 'infinia' and entry.direction == 'credit':
        return entry
    return None
