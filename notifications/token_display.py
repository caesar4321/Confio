"""Wire token values → what a person should read.

The server had this table copied by hand at four call sites, each written as

    display_token = 'cUSD' if str(token).upper() == 'CUSD' else str(token)

which knows exactly one token. Every BSC token fell through it raw, so a
payroll payout in cUSD+ pushed the notification "Enviaste 1.089 CUSD_PLUS a
Julian Moon" — the database's wire value, in a sentence a user reads.

This is the same table the client already keeps in
apps/src/utils/tokenDisplay.ts, and it exists there for the same reason: it
was five private copies, none of which knew about the BSC tokens. One table,
one place to add the next token.
"""
from decimal import Decimal, ROUND_HALF_UP

TOKEN_LABELS = {
    'CUSD': 'cUSD',
    'CUSD_PLUS': 'cUSD+',
    'CONFIO': 'CONFIO',
    'USDC': 'USDC',
    'USDT': 'USDT',
}


def token_label(token) -> str:
    """'CUSD_PLUS' → 'cUSD+'.

    An unknown token passes through unchanged rather than vanishing: a new
    token added server-side should read as its own raw symbol in a message,
    not as an empty string. Already-formatted input ('cUSD+') also passes
    through, so this is safe to apply twice.
    """
    raw = str(token or '').strip()
    if not raw:
        return ''
    return TOKEN_LABELS.get(raw.upper().replace('-', '_').replace(' ', '_'), raw)


def amount_str(value) -> str:
    """Money as a person writes it: two decimals, trailing zeros trimmed.

    Notification copy was interpolating raw Decimals straight out of the ORM,
    so a DecimalField(decimal_places=6) rendered a wage as '1.089000' or
    '1.089'. Nobody writes a dollar amount with three decimal places.
    """
    if value is None:
        return '0'
    try:
        d = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except Exception:  # noqa: BLE001 — copy must never raise
        return str(value)
    out = f'{d:.2f}'
    return out.rstrip('0').rstrip('.') if '.' in out else out
