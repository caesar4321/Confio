"""Local Bre-B destination checks; these do not verify key ownership."""
import re

BREB_RAIL = 'BREB'
BREB_KEY_MAX_LENGTH = 254


def payout_rail(metadata):
    return str((metadata or {}).get('rail') or '').strip().upper()


def validate_breb_key(*, account_number, account_type, country_code, fiat_symbol='COP'):
    if str(country_code or '').upper() not in {'CO', 'COL'} or str(fiat_symbol or '').upper() != 'COP':
        raise ValueError('Bre-B solo está disponible para retiros en Colombia (COP).')
    key = str(account_number or '').strip()
    if not key or any(ch.isspace() for ch in key):
        raise ValueError('Ingresa una llave Bre-B válida, sin espacios.')
    if len(key) > BREB_KEY_MAX_LENGTH:
        raise ValueError('La llave Bre-B debe tener máximo 254 caracteres.')
    # A leading plus is also valid in an email local part. Keys are opaque;
    # never strip punctuation, lowercase aliases, or infer a NIT is a phone.
    if key.startswith('+') and '@' not in key and not re.fullmatch(r'\+573[0-9]{9}', key):
        raise ValueError('El celular Bre-B debe incluir +57 y 10 dígitos.')
    if not str(account_type or '').strip():
        raise ValueError('Selecciona el tipo de cuenta asociado a tu llave Bre-B.')
    return key


def validate_saved_payout_rail(*, metadata, payment_method, account_number, account_type):
    """Reject unusable rail destinations before saving; return canonical metadata."""
    metadata = dict(metadata)
    code = str(getattr(payment_method, 'code', None) or getattr(payment_method, 'name', '')).upper()
    if code == 'BREB':
        if payout_rail(metadata) not in {'', BREB_RAIL}:
            raise ValueError('La vía de retiro seleccionada no es válida.')
        metadata['rail'] = BREB_RAIL
    rail = payout_rail(metadata)
    if not rail:
        return metadata
    if rail != BREB_RAIL:
        raise ValueError('La vía de retiro seleccionada no es válida.')
    validate_breb_key(
        account_number=account_number, account_type=account_type,
        country_code=getattr(payment_method, 'country_code', None),
    )
    if code not in {'BREB', 'WIRECO', 'BANCOLOMBIA'}:
        raise ValueError('Selecciona Bre-B para usar una llave.')
    if code == 'BANCOLOMBIA' and not metadata.get('bankCode'):
        metadata['bankCode'] = 'co_bancolombia'
    if not metadata.get('bankCode'):
        raise ValueError('Selecciona el banco asociado a tu llave Bre-B.')
    metadata['rail'] = BREB_RAIL
    return metadata
