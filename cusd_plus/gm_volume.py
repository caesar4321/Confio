"""All-time U.S. stock volume traded in Confío, for Home's "Acciones" tile.

The sum of every confirmed stock trade's exact settlement (its unified
history row: what a buy debited, what a sale paid), buys and sales alike.
Stock trades never pass through conversions, so the money-flow totals
(Dinero en movimiento) don't include them and this never double counts.
Aggregate only; cached for five minutes like the holdings snapshot.
"""
import logging
from decimal import Decimal

from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_KEY = 'gm_traded_volume_v1'
CACHE_TTL = 300


def traded_usd() -> float | None:
    """All-time settled stock volume in USD; None when it can't be read."""
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    from django.db.models import DecimalField, Sum
    from django.db.models.functions import Cast

    from users.models_unified import UnifiedTransactionTable

    try:
        total = (
            UnifiedTransactionTable.objects.filter(
                sponsored_batch__kind__in=('stock_buy', 'stock_sell'),
                sponsored_batch__status='confirmed',
                deleted_at__isnull=True,
            )
            .annotate(usd=Cast('amount', DecimalField(max_digits=40, decimal_places=18)))
            .aggregate(total=Sum('usd'))['total']
        )
    except Exception:  # noqa: BLE001 — unknown, never a false zero
        logger.exception('gm traded volume unreadable')
        return None
    value = float(total or Decimal('0'))
    cache.set(CACHE_KEY, value, CACHE_TTL)
    return value
