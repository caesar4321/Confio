"""Leveraged and inverse funds (TQQQ, SQQQ, SOXL, SOXS, PSQ).

They reset their exposure every day, so held for longer they can lose value
even when the market ends where it started. The curated list and each fund's
daily factor live in gm_highlights.json ("leverage"), next to their warnings,
so a new listing needs no app release.

A person confirms they understand that once, before their first purchase of
any of them. The app asks; PrepareGmTrade refuses a purchase without it, so
an older app (no confirmation screen) gets a readable message instead of a
silent pass. Selling never asks.
"""
import json
from pathlib import Path

# Raise when the disclosure the app shows changes materially: everyone is
# asked again.
ACK_VERSION = 1

# What the person confirms, served to the app (never hard-coded there), so
# the version they accept is always the text they read.
DISCLOSURE_TITLE = 'Antes de tu primer fondo apalancado o inverso'
DISCLOSURE_POINTS = (
    'Estos fondos multiplican (3x) o invierten (\u22121x, \u22123x) el movimiento de un solo día de un índice.',
    'Se reajustan cada día. Si los mantienes varios días, el resultado puede ser muy distinto de lo que '
    'hizo el índice, y pueden perder valor aunque el índice termine donde empezó.',
    'En un día malo caen mucho más que el índice: un fondo 3x pierde cerca de un 30% si el índice baja un 10%.',
    'Puedes perder gran parte de lo que inviertas, aunque nunca más de lo que pusiste.',
    'Están pensados para plazos cortos y para quien sigue el mercado a diario, no para ahorrar.',
)

ACK_REQUIRED_CODE = 'COMPLEX_PRODUCT_ACK_REQUIRED'
ACK_REQUIRED_MESSAGE = (
    'Para comprar fondos apalancados o inversos, actualiza la app y confirma '
    'que entiendes cómo funcionan.'
)


def factors() -> dict[str, int]:
    """{ticker: daily factor}, e.g. {'TQQQ': 3, 'SQQQ': -3, 'PSQ': -1}."""
    path = Path(__file__).parent / 'gm_highlights.json'
    raw = json.loads(path.read_text(encoding='utf-8')).get('leverage') or {}
    return {str(ticker).upper(): int(factor) for ticker, factor in raw.items()}


def factor_for_symbol(symbol: str) -> int | None:
    """The factor of a GM token symbol (TQQQon), or None for a plain stock."""
    symbol = (symbol or '').strip()
    ticker = symbol[:-2] if symbol.endswith('on') else symbol
    return factors().get(ticker.upper())


def buys_complex_product(calls) -> bool:
    """True when a sponsored batch buys one of these funds.

    Matched by the GM token address inside the signed router call, never by
    a client-supplied symbol: a quote requested by someone else (or by this
    person before a disclosure change) still names its asset on chain. The
    static registry always holds these addresses, so an Ondo outage cannot
    hide one. An undecodable router call counts as one (fail closed); the
    batch policy has already refused anything malformed."""
    from .sponsor_7702 import PolicyError, _decode_stock_call
    from .stock_month import _symbol_by_address

    complex_addresses = {address for address, symbol in _symbol_by_address().items()
                         if factor_for_symbol(symbol) is not None}
    for call in calls:
        try:
            action = _decode_stock_call(call, historical=True)
        except PolicyError:
            return True
        if action and action['kind'] == 'stock_buy' and action['asset'] in complex_addresses:
            return True
    return False


def acknowledged(user) -> bool:
    from blockchain.models import StockRiskAcknowledgement

    return StockRiskAcknowledgement.objects.filter(user=user, version__gte=ACK_VERSION).exists()


def acknowledge(user) -> None:
    from blockchain.models import StockRiskAcknowledgement

    StockRiskAcknowledgement.objects.update_or_create(
        user=user, defaults={'version': ACK_VERSION, 'acknowledged_at': _now()})


def _now():
    from django.utils import timezone

    return timezone.now()
