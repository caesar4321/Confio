"""
Shared cUSD platform metrics.

The cUSD contract is the source of truth for live supply and collateral values.
Database conversion rows are useful for product analytics, but they can drift
from on-chain state when admin mints, retries, or reconciliation paths happen.
"""
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q, Sum
from django.utils import timezone

from contracts.presale.state_utils import decode_global_state

logger = logging.getLogger(__name__)


MICRO_UNIT = Decimal("1000000")


@dataclass(frozen=True)
class CUSDPlatformMetrics:
    total_usdc_locked: Decimal
    circulating_cusd: Decimal
    tbills_backed_supply: Decimal
    total_supply: Decimal
    total_minted: Decimal
    total_burned: Decimal
    source: str
    as_of: object

    @property
    def tvl_cusd(self) -> Decimal:
        # cUSD is intended to track USDC 1:1, so USDC collateral is displayed as cUSD value.
        return self.total_usdc_locked


def _micro_to_decimal(value) -> Decimal:
    return Decimal(int(value or 0)) / MICRO_UNIT


def _conversion_fallback() -> CUSDPlatformMetrics:
    from conversion.models import Conversion

    aggregate = Conversion.objects.filter(status="COMPLETED").aggregate(
        total_usdc_to_cusd=Sum("to_amount", filter=Q(conversion_type="usdc_to_cusd")),
        total_cusd_to_usdc=Sum("from_amount", filter=Q(conversion_type="cusd_to_usdc")),
    )
    total_minted = aggregate["total_usdc_to_cusd"] or Decimal("0")
    total_burned = aggregate["total_cusd_to_usdc"] or Decimal("0")
    circulating = total_minted - total_burned
    return CUSDPlatformMetrics(
        total_usdc_locked=circulating,
        circulating_cusd=circulating,
        tbills_backed_supply=Decimal("0"),
        total_supply=circulating,
        total_minted=total_minted,
        total_burned=total_burned,
        source="database_fallback",
        as_of=timezone.now(),
    )


def get_cusd_platform_metrics(*, use_cache: bool = True) -> CUSDPlatformMetrics:
    """
    Return live cUSD supply/collateral metrics from the Algorand app global state.

    Falls back to completed conversion rows if algod is unavailable so dashboards
    stay usable, but callers can inspect `source` before labeling the value live.
    """
    cache_key = "cusd_platform_metrics:v1"
    if use_cache:
        cached = cache.get(cache_key)
        if cached:
            return cached

    try:
        app_id: Optional[int] = getattr(settings, "ALGORAND_CUSD_APP_ID", None)
        if not app_id:
            raise ValueError("ALGORAND_CUSD_APP_ID is not configured")

        from blockchain.algorand_client import get_algod_client

        client = get_algod_client()
        app_info = client.application_info(int(app_id))
        state = decode_global_state(app_info)

        total_usdc_locked = _micro_to_decimal(state.get("total_usdc_locked"))
        circulating_cusd = _micro_to_decimal(state.get("cusd_circulating_supply"))
        tbills_backed_supply = _micro_to_decimal(state.get("tbills_backed_supply"))
        total_supply = circulating_cusd + tbills_backed_supply

        metrics = CUSDPlatformMetrics(
            total_usdc_locked=total_usdc_locked,
            circulating_cusd=circulating_cusd,
            tbills_backed_supply=tbills_backed_supply,
            total_supply=total_supply,
            total_minted=_micro_to_decimal(state.get("total_minted")),
            total_burned=_micro_to_decimal(state.get("total_burned")),
            source="algorand",
            as_of=timezone.now(),
        )
    except Exception as exc:
        logger.warning("Unable to fetch live cUSD metrics from Algorand: %s", exc)
        metrics = _conversion_fallback()

    if use_cache:
        cache.set(cache_key, metrics, 30)
    return metrics
