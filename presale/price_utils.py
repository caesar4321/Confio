"""
CONFIO price for holdings valuation.

Historically the app valued CONFIO at the FIXED price of the last presale
phase (DB). With the BSC ConfioPresaleVault the price is a moving on-chain
curve — `currentPrice()` rises with every purchase — so valuation must
reference the contract, cached so wallet screens don't fan out RPC calls.

Resolution order:
  1. fresh cache (60s TTL)
  2. live eth_call currentPrice() on BSC_PRESALE_VAULT_ADDRESS
     (also refreshes a long-TTL last-known backup)
  3. last-known backup (RPC outage: serve the stale-but-real price
     rather than dropping to a fallback that would misprice holdings)
  4. active/latest presale phase price (DB — the pre-vault behavior)
  5. 0.20 floor
"""
import logging
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_KEY = 'presale:curve_price'
LAST_KNOWN_KEY = 'presale:curve_price:last_known'
CACHE_TTL_SEC = 60
LAST_KNOWN_TTL_SEC = 7 * 24 * 3600

FLOOR_PRICE = Decimal('0.2')

# currentPrice() selector — keccak('currentPrice()')[:4]
_CURRENT_PRICE_SELECTOR = '0x9d1b464a'


def _phase_fallback_price() -> Decimal:
    """Pre-vault behavior: the active (else latest usable) phase price."""
    try:
        from presale.models import PresalePhase
        phase = (
            PresalePhase.objects.filter(status='active').first()
            or PresalePhase.objects.filter(
                status__in=['active', 'completed', 'paused', 'coming_soon']
            ).order_by('-phase_number').first()
        )
        if phase and phase.price_per_token and phase.price_per_token > 0:
            return Decimal(phase.price_per_token)
    except Exception:
        pass
    return FLOOR_PRICE


def _cache_get(key):
    try:
        return cache.get(key)
    except Exception:
        return None


def _cache_set(key, value, ttl):
    try:
        cache.set(key, value, ttl)
    except Exception:
        pass


# Curve endpoints as locked in the vault's constructor (no setter exists on
# chain; mirrored here for display only — the contract is the authority).
CURVE_START_PRICE = Decimal('0.20')
CURVE_FINAL_PRICE = Decimal('1.30')

# Recaudado-axis milestones for user-facing progress. Deliberately absolute
# amounts, never a % of the $61M full sale (a fraction-of-goal bar reads as
# "stalled" early on and resurrects the phase-goal framing we removed).
RAISE_MILESTONES_USD = [
    250_000, 500_000, 1_000_000, 2_500_000, 5_000_000,
    10_000_000, 25_000_000, 50_000_000, 61_000_000,
]

STATS_CACHE_KEY = 'presale:curve_stats'
STATS_CACHE_TTL_SEC = 60


def get_presale_curve_stats() -> dict:
    """
    One authoritative stats object for the presale screens.

    totalRaised/participants come from the DB (every purchase on any chain
    creates a PresalePurchase row — buys are sponsor-gated, so nothing can
    reach the vault without passing through Django), which avoids
    double-counting against the vault's on-chain totalRaised.
    """
    cached = _cache_get(STATS_CACHE_KEY)
    if cached is not None:
        return cached

    from django.db.models import Sum, Count
    from presale.models import PresalePurchase

    agg = PresalePurchase.objects.filter(status='completed').aggregate(
        raised=Sum('cusd_amount'),
        participants=Count('user', distinct=True),
    )
    raised = agg['raised'] or Decimal('0')
    next_milestone = next(
        (Decimal(m) for m in RAISE_MILESTONES_USD if Decimal(m) > raised),
        Decimal(RAISE_MILESTONES_USD[-1]),
    )
    stats = {
        'current_price': get_confio_current_price(),
        'start_price': CURVE_START_PRICE,
        'final_price': CURVE_FINAL_PRICE,
        'total_raised_usd': raised,
        'next_milestone_usd': next_milestone,
        'participants': int(agg['participants'] or 0),
    }
    _cache_set(STATS_CACHE_KEY, stats, STATS_CACHE_TTL_SEC)
    return stats


def get_confio_current_price() -> Decimal:
    """Current CONFIO price in dollars (USDT/cUSD ≈ $1), cached."""
    cached = _cache_get(CACHE_KEY)
    if cached is not None:
        return Decimal(cached)

    vault = getattr(settings, 'BSC_PRESALE_VAULT_ADDRESS', None)
    if vault:
        try:
            from cusd_plus.tasks import _rpc
            raw = _rpc('eth_call', [{'to': vault, 'data': _CURRENT_PRICE_SELECTOR}, 'latest'])
            wei = int(raw, 16) if raw and raw != '0x' else 0
            if wei > 0:
                price = (Decimal(wei) / Decimal(10) ** 18).quantize(Decimal('0.000001'))
                _cache_set(CACHE_KEY, str(price), CACHE_TTL_SEC)
                _cache_set(LAST_KNOWN_KEY, str(price), LAST_KNOWN_TTL_SEC)
                return price
        except Exception as e:
            logger.warning(f"[PRESALE][PRICE] currentPrice() read failed: {e}")

        last_known = _cache_get(LAST_KNOWN_KEY)
        if last_known is not None:
            return Decimal(last_known)

    return _phase_fallback_price()
