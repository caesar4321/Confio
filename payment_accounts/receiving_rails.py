"""Receiving-only evidence. Candidates are diagnostic, never authorization.

Sources: Infinia Get Account Details and Fiat Virtual Accounts (2026-09-16).
The coverage table is not evidence that a specific account supports a rail.
Do not reuse payout destination enums to classify receiving instructions.
"""
from .providers.common import iso_alpha2


CANDIDATES = {
    ('AR', 'ARS'): ['CBU', 'CVU'], ('BO', 'BOB'): ['QR', 'YAPE'],
    ('BR', 'BRL'): ['PIX', 'TED'], ('CL', 'CLP'): ['TEF'],
    ('CO', 'COP'): ['ACH', 'BREB'], ('MX', 'MXN'): ['SPEI'],
    ('PE', 'PEN'): ['QR', 'YAPE'], ('PY', 'PYG'): ['ACH', 'SIPAP'],
    ('UY', 'UYU'): ['ACH', 'SPI'], ('US', 'USD'): ['ACH', 'FEDWIRE'],
    ('GB', 'GBP'): ['CHAPS', 'FPS'], ('GB', 'EUR'): ['SEPA'],
    ('LU', 'EUR'): ['SEPA'], ('EU', 'EUR'): ['SEPA'],
}


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _digits(value, length):
    value = _text(value)
    return len(value) == length and value.isascii() and value.isdigit()


def detect_receiving_rail(account):
    """Return a PII-free assessment of the latest authenticated snapshot."""
    from .local_money import clabe_valid, cbu_valid
    try:
        country = iso_alpha2(account.country)
    except ValueError:
        country = 'EU' if account.country == 'EU' else ''
    pair = (country, account.asset)
    fallback = CANDIDATES.get(pair, [])
    data = account.provider_data if isinstance(account.provider_data, dict) else {}
    raw = data.get('latest')
    result = dict(version=1, status='unknown', verified_rail='', candidates=list(fallback),
                  evidence=[], reason='snapshot_missing')
    if not isinstance(raw, dict) or 'funding_instructions' not in raw:
        return result
    items = raw['funding_instructions']
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list) or any(not isinstance(i, dict) for i in items):
        result['reason'] = 'instructions_malformed'
        return result
    if not fallback:
        result['reason'] = 'unsupported_country_currency'
        return result
    rails, evidence = set(), set()
    unknown = False
    for item in items:
        # A crypto address on a fiat pair is conflicting evidence, not a fiat rail.
        if item.get('type') not in (None, 'fiat', 'qr'):
            unknown = True
            continue
        found = set()
        def accept(rail, field):
            found.add(rail)
            evidence.add(field)
        number = _text(item.get('account_number'))
        if pair == ('MX', 'MXN') and item.get('type') == 'fiat':
            if _digits(number, 18) and clabe_valid(number):
                accept('SPEI', 'account_number:clabe_checksum')
        elif pair == ('AR', 'ARS') and item.get('type') == 'fiat':
            if _digits(number, 22) and cbu_valid(number):
                accept('CVU' if number.startswith('000') else 'CBU', 'account_number:cbu_checksum')
        elif pair == ('BR', 'BRL'):
            for field, child in [('pix_key', None), ('br_code', None),
                                 ('pix_key_brl', 'pix_key'), ('br_code_brl', 'br_code')]:
                value = item.get(field)
                if isinstance(value, dict) and child:
                    value = value.get(child)
                if _text(value):
                    accept('PIX', field)
            ted = item.get('ted_brl')
            if isinstance(ted, dict) and all(_text(ted.get(k)) for k in
                    ('bank_code', 'branch_number', 'account_number', 'account_type')):
                accept('TED', 'ted_brl')
            elif ted:
                unknown = True
        elif pair == ('CO', 'COP') and _text(item.get('breb_key')):
            accept('BREB', 'breb_key')
        elif pair == ('GB', 'GBP'):
            fps = item.get('fps_gbp')
            if isinstance(fps, dict) and _digits(fps.get('account_number'), 8) and _digits(
                    _text(fps.get('sort_code')).replace('-', '').replace(' ', ''), 6):
                accept('FPS', 'fps_gbp')
        # Extra generic bank details can represent another rail on these pairs.
        if number and pair in {('BR', 'BRL'), ('CO', 'COP'), ('GB', 'GBP')}:
            unknown = True
        if not found and any(v not in (None, '', {}, []) for k, v in item.items() if k != 'type'):
            unknown = True
        known_fields = {'type', 'id', 'reference', 'account_number', 'bank_name', 'bank_code', 'iban', 'bic'}
        known_fields |= {
            ('BR', 'BRL'): {'br_code', 'ted_brl', 'pix_key', 'pix_key_brl', 'br_code_brl'},
            ('CO', 'COP'): {'breb_key'},
            ('GB', 'GBP'): {'fps_gbp'},
        }.get(pair, set())
        if any(v not in (None, '', {}, []) for k, v in item.items() if k not in known_fields):
            unknown = True
        rails.update(found)
    result['evidence'] = sorted(evidence)
    if len(rails) == 1 and not unknown:
        result.update(status='verified', verified_rail=next(iter(rails)), candidates=sorted(rails),
                      reason='unambiguous_provider_instructions')
    elif len(rails) > 1 or (rails and unknown):
        result.update(status='ambiguous', candidates=sorted(rails | (set(fallback) if unknown else set())),
                      reason='multiple_or_unclassified_instructions')
    else:
        result.update(status='inferred' if unknown else 'unknown',
                      reason='country_currency_candidates' if unknown else 'instructions_empty_or_invalid')
    return result


def sync_verified_rail(account):
    if account.provider != 'infinia':
        return
    from django.db import transaction
    from .models import FinancialAccount
    # Merge diagnostic metadata under the row lock; never overwrite another
    # worker's refreshed provider snapshot with this caller's older instance.
    with transaction.atomic():
        current = FinancialAccount.objects.select_for_update().get(pk=account.pk)
        assessment = detect_receiving_rail(current)
        data = dict(current.provider_data) if isinstance(current.provider_data, dict) else {}
        previous = data.get('receiving_rail_detection')
        rail = assessment['verified_rail']
        # A partial snapshot does not revoke an explicit operator-set rail.
        # A previously auto-detected rail, however, must not survive lost evidence.
        if assessment['reason'] == 'snapshot_missing' and not (
                isinstance(previous, dict) and previous.get('verified_rail')):
            rail = current.payin_rail
        data['receiving_rail_detection'] = assessment
        if previous != assessment or current.payin_rail != rail:
            current.provider_data, current.payin_rail = data, rail
            current.save(update_fields=['provider_data', 'payin_rail', 'updated_at'])
        account.provider_data, account.payin_rail = current.provider_data, rail
