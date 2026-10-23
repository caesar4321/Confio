"""Numbers in server-written text (notifications, pushes) the way the
RECIPIENT's country writes them, like the app does (apps/src/utils/
numberLocale.ts, keep both lists the same):

    VE, AR, CO, BO, CL, EC, PY, UY, BR, ES …  1.234,56
    MX, PE, DO, SV, GT, HN, NI, PA, US …      1,234.56

The country is the user's phone country. One notification can go to two
people in different countries, so format per recipient, never once."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

COMMA_DECIMAL_COUNTRIES = frozenset({
    'AR', 'BO', 'BR', 'CL', 'CO', 'CR', 'CU', 'EC', 'PY', 'UY', 'VE',
    'ES', 'PT', 'DE', 'IT', 'NL', 'FR', 'BE', 'AT', 'ID', 'TR', 'RU',
})


def separators_for(user=None, country: str | None = None) -> tuple[str, str]:
    """(group, decimal) for this user's (or this country's) format."""
    iso = (country or getattr(user, 'phone_country', None) or '').upper()
    return ('.', ',') if iso in COMMA_DECIMAL_COUNTRIES else (',', '.')


def format_amount(value, user=None, *, decimals: int = 2, trim: bool = True, country: str | None = None) -> str:
    """"1.234,5" / "1,234.5" for this user. Rounded half up at `decimals`;
    trailing zeros dropped unless `trim=False` ("5" vs "5,00"). Anything
    that is not a number comes back unchanged."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    if not number.is_finite():
        return str(value)
    rounded = number.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP) if decimals >= 0 else number
    text = f'{abs(rounded):f}'
    whole, _, fraction = text.partition('.')
    if trim:
        fraction = fraction.rstrip('0')
    group, decimal = separators_for(user, country)
    grouped = f'{int(whole):,}'.replace(',', group)
    body = f'{grouped}{decimal}{fraction}' if fraction else grouped
    return f'-{body}' if rounded < 0 and any(c in '123456789' for c in body) else body


def format_usd(value, user=None, *, trim: bool = False, country: str | None = None) -> str:
    """"$1.234,50" / "$1,234.50" (cents kept unless `trim`)."""
    body = format_amount(value, user, decimals=2, trim=trim, country=country)
    return f'-${body[1:]}' if body.startswith('-') else f'${body}'
