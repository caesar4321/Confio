"""Comprar pricing: products are priced in US dollars — the escrow's unit
and what the merchant receives — so a sale involves no exchange rate.

Local currency is a display convenience only ("≈ 1.470 Bs"): computed from a
fresh parallel-market rate when one exists, and simply absent otherwise. It
never blocks, quotes or changes a payment.
"""

from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.utils import timezone

WAD = 10**18
CENT = Decimal('0.01')


def fee_bps() -> int:
    return int(getattr(settings, 'MARKETPLACE_FEE_BPS', 800))


def fee_wei(amount_wei: int, bps: int) -> int:
    """ceil(amount * bps / 10000) — byte-for-byte ConfioMarketEscrow.feeFor."""
    return -(-int(amount_wei) * int(bps) // 10_000)


def local_per_usd(currency_code: str) -> Decimal | None:
    """Local units per 1 USD from a fresh parallel-market row, or None.
    Display only: a missing or stale rate just hides the reference line."""
    if not currency_code or currency_code == 'USD':
        return None
    from django.core.cache import cache

    # 60s cache: a page of products costs one rate read, not one per card. The
    # cache is an optimization: if it is down, read the rate directly.
    key = f'comprar:ref-rate:{currency_code}'
    try:
        cached = cache.get(key)
        if cached is not None:
            return Decimal(cached) if cached else None
    except Exception:  # noqa: BLE001
        pass
    rate = None
    try:
        from exchange_rates.services import exchange_rate_service

        row = exchange_rate_service.get_current_rate_row(currency_code, 'USD', 'parallel')
        max_age = timedelta(hours=int(getattr(settings, 'MARKETPLACE_RATE_MAX_AGE_HOURS', 6)))
        fetched_at = getattr(row, 'fetched_at', None) if row else None
        if (row is not None and row.rate and row.rate > 0 and fetched_at is not None
                and timezone.now() - fetched_at <= max_age):
            rate = Decimal(row.rate)
    except Exception:  # noqa: BLE001 — a reference line is never worth an error
        rate = None
    try:
        cache.set(key, str(rate) if rate else '', 60)
    except Exception:  # noqa: BLE001
        pass
    return rate


def currency_for_country(country_code: str) -> str:
    from exchange_rates.currency_mapping import COUNTRY_TO_CURRENCY
    return COUNTRY_TO_CURRENCY.get((country_code or '').upper(), 'USD')


def reference_local(amount_usd, country_code: str) -> tuple[Decimal, str] | None:
    """(≈ amount in the country's currency, currency code), or None. Any
    failure on the way (cache outage, bad row) hides the line — it is computed
    while building products, quotes and orders, and must never break them."""
    try:
        currency = currency_for_country(country_code)
        rate = local_per_usd(currency)
        if rate is None:
            return None
        return (Decimal(amount_usd) * rate).quantize(CENT, rounding=ROUND_HALF_UP), currency
    except Exception:  # noqa: BLE001
        return None


@dataclass(frozen=True)
class Quote:
    unit_price_usd: Decimal
    amount_usd: Decimal
    amount_wei: int
    fee_bps: int
    fee_usd: Decimal
    merchant_net_usd: Decimal
    product_usd: Decimal = Decimal('0')
    delivery_usd: Decimal = Decimal('0')


def quote(unit_price_usd: Decimal, quantity: int, delivery_usd=Decimal('0')) -> Quote:
    """Product × quantity plus the store's delivery price: ONE amount the
    buyer pays into the escrow. The seller books and pays the courier, and the
    delivery comes back to them in the payout. The fee is on the whole order
    (the contract takes it on the deposited amount), like Etsy or eBay."""
    unit = Decimal(unit_price_usd).quantize(CENT)
    product_usd = (unit * quantity).quantize(CENT)
    delivery = Decimal(delivery_usd or 0).quantize(CENT)
    amount_usd = product_usd + delivery
    amount_wei = int(amount_usd * WAD)
    bps = fee_bps()
    fee = Decimal(fee_wei(amount_wei, bps)) / WAD
    return Quote(unit_price_usd=unit, amount_usd=amount_usd, amount_wei=amount_wei, fee_bps=bps,
                 fee_usd=fee, merchant_net_usd=amount_usd - fee, product_usd=product_usd,
                 delivery_usd=delivery)


MAX_DELIVERY_USD = Decimal('100')
DELIVERY_FALLBACK_USD = Decimal('2.00')


def suggested_delivery_usd(country_code: str, city: str) -> Decimal:
    """A starting delivery price for a store: the city's same-city courier
    estimate (local currency) at today's reference rate, rounded UP to 10
    cents. The store owns the price after that; this only pre-fills it."""
    import math

    from .models import MarketplaceCity

    known = MarketplaceCity.objects.filter(country_code=(country_code or '').upper(),
                                           city__iexact=(city or '').strip()).first()
    rate = local_per_usd(known.currency_code) if known and known.delivery_estimate else None
    if not rate:
        return DELIVERY_FALLBACK_USD
    usd = Decimal(known.delivery_estimate) / rate
    return (Decimal(math.ceil(usd * 10)) / 10).quantize(CENT)
