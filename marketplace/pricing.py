"""Comprar pricing: local price → dollars, and the merchant fee.

The seller prices in local currency (Bs in Bolivia). At checkout the local
subtotal is converted at the current parallel-market rate and the USD amount
is what the escrow holds; that quote is frozen into the order and signed.
A stale or missing rate refuses checkout — never a guessed price.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_DOWN, ROUND_UP, Decimal

from django.conf import settings
from django.utils import timezone

WAD = 10**18


class QuoteUnavailable(Exception):
    pass


def fee_bps() -> int:
    return int(getattr(settings, 'MARKETPLACE_FEE_BPS', 800))


def fee_wei(amount_wei: int, bps: int) -> int:
    """ceil(amount * bps / 10000) — byte-for-byte ConfioMarketEscrow.feeFor."""
    return -(-int(amount_wei) * int(bps) // 10_000)


def local_per_usd(currency_code: str) -> Decimal:
    """Local currency units per 1 USD, from a fresh parallel-market row."""
    from exchange_rates.services import exchange_rate_service

    row = exchange_rate_service.get_current_rate_row(currency_code, 'USD', 'parallel')
    max_age = timedelta(hours=int(getattr(settings, 'MARKETPLACE_RATE_MAX_AGE_HOURS', 6)))
    if row is None or not row.rate or row.rate <= 0:
        raise QuoteUnavailable('rate_unavailable')
    fetched_at = getattr(row, 'fetched_at', None)
    if fetched_at is None or timezone.now() - fetched_at > max_age:
        raise QuoteUnavailable('rate_stale')
    return Decimal(row.rate)


@dataclass(frozen=True)
class Quote:
    subtotal_local: Decimal
    fx_rate: Decimal
    amount_usd: Decimal
    amount_wei: int
    fee_bps: int
    fee_usd: Decimal
    merchant_net_usd: Decimal


def quote(unit_price_local: Decimal, quantity: int, currency_code: str) -> Quote:
    subtotal = (Decimal(unit_price_local) * quantity).quantize(Decimal('0.01'))
    rate = local_per_usd(currency_code)
    # Round the buyer's dollars UP to the cent so the merchant never receives
    # less than the price they set at today's rate.
    amount_usd = (subtotal / rate).quantize(Decimal('0.01'), rounding=ROUND_UP)
    amount_wei = int(amount_usd * WAD)
    bps = fee_bps()
    fee = Decimal(fee_wei(amount_wei, bps)) / WAD
    return Quote(
        subtotal_local=subtotal,
        fx_rate=rate.quantize(Decimal('0.000001'), rounding=ROUND_DOWN),
        amount_usd=amount_usd,
        amount_wei=amount_wei,
        fee_bps=bps,
        fee_usd=fee,
        merchant_net_usd=amount_usd - fee,
    )
